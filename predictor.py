import json
import os
import sys
import re
import unicodedata
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PICKS_DIR, MIN_EV_THRESHOLD, MIN_EV_REEMISSION, LEAGUES
from src.data_fetcher import (
    get_all_today_fixtures, extract_team_features, get_h2h
)
from src.odds_fetcher import (
    get_odds, extract_best_odds, extract_totals, calculate_no_vig_probability
)
from src.model import PoissonGoalModel, EVCalculator, FormAdjuster, evaluate_pick
from src.deduplication import DeduplicationManager
from src.telegram_sender import send_pick, send_parlay


def normalize_team_name(name):
    """
    Normaliza los nombres de los equipos para mejorar la tasa de coincidencia (match-rate)
    eliminando acentos, caracteres especiales, espacios y sufijos comunes de clubes.
    """
    if not name:
        return ""
    # Eliminar acentos
    name = "".join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = name.lower()
    # Eliminar términos de clubes comunes para evitar desajustes
    terms_to_remove = [
        r"\bfc\b", r"\bcf\b", r"\bsd\b", r"\bud\b", r"\brc\b", r"\bsc\b", 
        r"\bunited\b", r"\butd\b", r"\bde\b", r"\batletico\b", r"\bclub\b", 
        r"\bdeportivo\b", r"\bas\b", r"\bafc\b"
    ]
    for term in terms_to_remove:
        name = re.sub(term, "", name)
    # Eliminar cualquier caracter no alfanumérico y espacios sobrantes
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def run_prediction_window():
    """
    Ejecuta una ventana de predicción completa con control de errores robusto.
    Flujo: Obtener datos → Calcular probabilidades → Filtrar valor → Deduplicar → Enviar
    """
    print(f"\n{'='*60}")
    print(f"  VENTANA DE PREDICCIÓN - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    try:
        poisson_model = PoissonGoalModel()
        poisson_model.load_league_averages()
    except Exception as e:
        print(f"      [ERROR] No se pudo inicializar el modelo Poisson: {e}")
        return []

    form_adjuster = FormAdjuster()
    dedup = DeduplicationManager()

    # 1. Obtener partidos del día
    print("[1/5] Obteniendo partidos del día...")
    try:
        fixtures = get_all_today_fixtures()
        if not fixtures:
            print("      No hay partidos hoy o no se pudieron recuperar. Saliendo.")
            return []
        print(f"      Encontrados: {len(fixtures)} partidos\n")
    except Exception as e:
        print(f"      [ERROR] Al obtener partidos del día: {e}")
        return []

    # 2. Obtener cuotas
    print("[2/5] Obteniendo cuotas en vivo...")
    all_odds = {}
    for league_name, league_info in LEAGUES.items():
        odds_key = league_info.get("odds_key")
        if not odds_key:
            continue
        try:
            odds_data = get_odds(odds_key)
            if not odds_data:
                continue
            for event in odds_data:
                home = normalize_team_name(event.get('home_team', ''))
                away = normalize_team_name(event.get('away_team', ''))
                if home and away:
                    key = f"{home}_{away}"
                    all_odds[key] = event
        except Exception as e:
            print(f"      [ERROR] No se pudieron obtener cuotas para {league_name}: {e}")
            continue
    print(f"      Cuotas obtenidas para {len(all_odds)} eventos\n")

    # 3. Analizar cada partido
    print("[3/5] Analizando partidos con modelo Poisson + ML...")
    value_picks = []

    for fixture in fixtures:
        try:
            teams = fixture.get("teams", {})
            home_team = teams.get("home")
            away_team = teams.get("away")

            if not home_team or not away_team:
                continue

            home_name = home_team.get("name", "")
            away_name = away_team.get("name", "")
            home_id = home_team.get("id")
            away_id = away_team.get("id")

            if not home_id or not away_id:
                continue

            league_name = fixture.get("_league_name", "unknown")
            league_id = LEAGUES.get(league_name, {}).get("id", 0)

            # Extraer features de forma segura
            home_features = extract_team_features(home_id, league_id, is_home=True)
            away_features = extract_team_features(away_id, league_id, is_home=False)

            if not home_features or not away_features:
                continue

            # Obtención de H2H con manejo de excepciones
            try:
                h2h = get_h2h(home_id, away_id)
            except Exception:
                h2h = []

            # Modelo Poisson
            league_avg = poisson_model.league_averages.get(league_name, {}).get("avg_total_goals", 2.65)
            
            poisson_result = poisson_model.predict_goals(
                home_attack=home_features.get("avg_goals_for", 1.2),
                home_defense=home_features.get("avg_goals_against", 1.2),
                away_attack=away_features.get("avg_goals_for", 1.2),
                away_defense=away_features.get("avg_goals_against", 1.2),
                league_avg_goals=league_avg
            )
            
            if not poisson_result or "prob_matrix" not in poisson_result:
                continue

            probs = poisson_model.get_match_probabilities(poisson_result["prob_matrix"])
            if not probs:
                continue

            # Ajustar con forma y H2H
            probs["home_win"] = form_adjuster.adjust_probability(
                probs.get("home_win", 0.33), home_features, h2h
            )
            probs["away_win"] = form_adjuster.adjust_probability(
                probs.get("away_win", 0.33), away_features, h2h
            )
            
            # Renormalizar probabilidades previniendo división por cero
            total = probs.get("home_win", 0) + probs.get("draw", 0) + probs.get("away_win", 0)
            if total > 0:
                probs["home_win"] /= total
                probs["draw"] /= total
                probs["away_win"] /= total
            else:
                probs["home_win"], probs["draw"], probs["away_win"] = 0.333, 0.334, 0.333

            # Buscar cuotas del partido mediante nombres normalizados
            match_key = f"{normalize_team_name(home_name)}_{normalize_team_name(away_name)}"
            odds_event = all_odds.get(match_key)

            if not odds_event:
                continue

            best_odds = extract_best_odds(odds_event) or {}
            totals = extract_totals(odds_event) or {}

            home_odds = best_odds.get("home", {}).get("odds", 0)
            away_odds = best_odds.get("away", {}).get("odds", 0)
            over_odds = totals.get("over_2.5", {}).get("odds", 0)
            under_odds = totals.get("under_2.5", {}).get("odds", 0)

            # Evaluar todos los mercados configurados
            markets_to_check = [
                ("home_win", home_odds, f"{home_name} gana"),
                ("away_win", away_odds, f"{away_name} gana"),
                ("over_2.5", over_odds, "Over 2.5 goles"),
                ("under_2.5", under_odds, "Under 2.5 goles"),
            ]

            for market_key, odds, description in markets_to_check:
                if odds <= 1.0:
                    continue

                model_prob = probs.get(market_key, 0)
                if model_prob <= 0:
                    continue

                evaluation = evaluate_pick(model_prob, odds)

                if evaluation and evaluation.get("is_value_bet"):
                    pick = {
                        "match": f"{home_name} vs {away_name}",
                        "league": league_name,
                        "market": description,
                        "odds": odds,
                        "model_prob": model_prob,
                        "ev": evaluation.get("ev", 0.0),
                        "ev_pct": evaluation.get("ev_pct", "+0.0%"),
                        "kelly": evaluation.get("kelly", 0.0),
                        "kelly_pct": evaluation.get("kelly_pct", "0.0%"),
                        "rating": evaluation.get("rating", "⭐"),
                        "lambda_home": poisson_result.get("lambda_home", 0.0),
                        "lambda_away": poisson_result.get("lambda_away", 0.0),
                        "timestamp": datetime.now().isoformat(),
                        "fixture_id": fixture.get("fixture", {}).get("id", 0)
                    }
                    value_picks.append(pick)
        except Exception as e:
            print(f"      [ADVERTENCIA] Error procesando fixture individual: {e}")
            continue

    print(f"      Picks con valor encontrados: {len(value_picks)}\n")

    # 4. Deduplicar
    print("[4/5] Verificando deduplicación...")
    new_picks = []
    for pick in value_picks:
        try:
            status = dedup.check_pick(pick)
            if status == "new":
                new_picks.append(pick)
                dedup.register_pick(pick)
            elif status == "improved" and pick.get("ev", 0.0) >= MIN_EV_REEMISSION:
                pick["_reemission"] = True
                new_picks.append(pick)
                dedup.update_pick(pick)
        except Exception as e:
            print(f"      [ERROR] Fallo en la fase de deduplicación para el pick {pick.get('match')}: {e}")
            # En caso de fallo crítico en el motor de deduplicación, conservar el pick como de seguridad
            new_picks.append(pick)

    print(f"      Picks nuevos para enviar: {len(new_picks)}\n")

    # 5. Enviar a Telegram
    print("[5/5] Enviando picks a Telegram...")
    sent_count = 0
    for pick in sorted(new_picks, key=lambda x: x.get("ev", 0.0), reverse=True)[:5]:
        try:
            send_pick(pick)
            sent_count += 1
            print(f"      ✅ Enviado: {pick['match']} - {pick['market']} @ {pick['odds']}")
        except Exception as e:
            print(f"      ❌ Error al enviar pick {pick.get('match')} a Telegram: {e}")

    # Generar parlay de forma segura si hay suficientes nuevos picks
    if len(new_picks) >= 3:
        try:
            parlay = generate_best_parlay(new_picks)
            if parlay:
                send_parlay(parlay)
                print(f"      ✅ Parlay enviado: {len(parlay['legs'])} piernas @ {parlay['combined_odds']:.2f}")
        except Exception as e:
            print(f"      ❌ Error al procesar o enviar parlay: {e}")

    # Guardar picks del día de manera segura
    if new_picks:
        try:
            save_daily_picks(new_picks)
        except Exception as e:
            print(f"      ❌ Error al guardar copia local de picks: {e}")

    print(f"\n{'='*60}")
    print(f"  VENTANA COMPLETADA - {sent_count} de {len(new_picks)} picks emitidos con éxito")
    print(f"{'='*60}\n")

    return new_picks


def generate_best_parlay(picks: list, target_odds: float = 5.0, legs: int = 3) -> dict:
    """
    Genera el mejor parlay de N piernas apuntando a una cuota combinada óptima.
    Filtra por valor y previene la duplicación de partidos en el mismo boleto.
    """
    if not picks or len(picks) < legs:
        return None

    # Filtrar solo picks con métricas válidas y ordenar por EV descendente
    sorted_picks = sorted(
        [p for p in picks if p.get("ev", 0) > 0], 
        key=lambda x: x["ev"], 
        reverse=True
    )

    selected = []
    used_matches = set()

    for pick in sorted_picks:
        match_identifier = pick.get("match")
        if match_identifier not in used_matches and len(selected) < legs:
            selected.append(pick)
            used_matches.add(match_identifier)

    if len(selected) < legs:
        return None

    # Calcular cuota combinada y probabilidad acumulada con seguridad matemática
    combined_odds = 1.0
    combined_prob = 1.0
    for pick in selected:
        combined_odds *= max(pick.get("odds", 1.0), 1.0)
        combined_prob *= max(pick.get("model_prob", 0.0), 0.0)

    try:
        parlay_ev = EVCalculator.calculate_ev(combined_prob, combined_odds)
        kelly_value = EVCalculator.calculate_kelly(combined_prob, combined_odds)
    except Exception:
        parlay_ev = 0.0
        kelly_value = 0.0

    return {
        "legs": selected,
        "combined_odds": round(combined_odds, 2),
        "combined_prob": round(combined_prob, 4),
        "ev": parlay_ev,
        "ev_pct": f"+{parlay_ev * 100:.2f}%",
        "kelly": kelly_value,
        "timestamp": datetime.now().isoformat()
    }


def save_daily_picks(picks: list):
    """Guarda de forma segura los picks del día en el directorio configurado."""
    if not PICKS_DIR:
        print("      [ADVERTENCIA] No se detectó PICKS_DIR configurado. Omitiendo guardado.")
        return

    try:
        os.makedirs(PICKS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = os.path.join(PICKS_DIR, f"picks_{timestamp}.json")

        # Guardar en formato JSON de forma segura con UTF-8
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(picks, f, indent=2, ensure_ascii=False)

        print(f"      Guardado: {filename}")
    except OSError as e:
        print(f"      [ERROR] Error de I/O de sistema al guardar los picks: {e}")
    except Exception as e:
        print(f"      [ERROR] Error inesperado guardando picks: {e}")


if __name__ == "__main__":
    try:
        picks = run_prediction_window()
        if picks:
            print(f"\nResumen de picks procesados:")
            for p in picks:
                print(f"  {p.get('rating', '⭐')} {p.get('match')} | {p.get('market')} @ {p.get('odds')} | EV: {p.get('ev_pct')}")
    except KeyboardInterrupt:
        print("\n[PROCESO INTERRUMPIDO] Ejecución cancelada por el usuario.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR FATAL] Fallo crítico en el flujo principal: {e}")
        sys.exit(1)