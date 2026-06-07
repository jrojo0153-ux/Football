"""
predictor.py - Motor de Predicción Principal
Orquesta: data_fetcher + odds_fetcher + model + deduplication + telegram
"""

import json
import os
import sys
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


def run_prediction_window():
    """
    Ejecuta una ventana de predicción completa.
    Flujo: Obtener datos → Calcular probabilidades → Filtrar valor → Deduplicar → Enviar
    """
    print(f"\n{'='*60}")
    print(f"  VENTANA DE PREDICCIÓN - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Inicializar componentes
    poisson_model = PoissonGoalModel()
    poisson_model.load_league_averages()
    form_adjuster = FormAdjuster()
    dedup = DeduplicationManager()

    # 1. Obtener partidos del día
    print("[1/5] Obteniendo partidos del día...")
    fixtures = get_all_today_fixtures()
    print(f"      Encontrados: {len(fixtures)} partidos\n")

    if not fixtures:
        print("      No hay partidos hoy. Saliendo.")
        return []

    # 2. Obtener cuotas
    print("[2/5] Obteniendo cuotas en vivo...")
    all_odds = {}
    for league_name, league_info in LEAGUES.items():
        odds_data = get_odds(league_info["odds_key"])
        for event in odds_data:
            key = f"{event['home_team']}_{event['away_team']}".lower().replace(" ", "")
            all_odds[key] = event
    print(f"      Cuotas obtenidas para {len(all_odds)} eventos\n")

    # 3. Analizar cada partido
    print("[3/5] Analizando partidos con modelo Poisson + ML...")
    value_picks = []

    for fixture in fixtures:
        home_team = fixture["teams"]["home"]
        away_team = fixture["teams"]["away"]
        league_name = fixture.get("_league_name", "unknown")
        league_id = LEAGUES.get(league_name, {}).get("id", 0)

        # Extraer features
        home_features = extract_team_features(home_team["id"], league_id, is_home=True)
        away_features = extract_team_features(away_team["id"], league_id, is_home=False)

        if not home_features or not away_features:
            continue

        # H2H
        h2h = get_h2h(home_team["id"], away_team["id"])

        # Modelo Poisson
        league_avg = poisson_model.league_averages.get(league_name, {}).get("avg_total_goals", 2.65)
        poisson_result = poisson_model.predict_goals(
            home_attack=home_features["avg_goals_for"],
            home_defense=home_features["avg_goals_against"],
            away_attack=away_features["avg_goals_for"],
            away_defense=away_features["avg_goals_against"],
            league_avg_goals=league_avg
        )
        probs = poisson_model.get_match_probabilities(poisson_result["prob_matrix"])

        # Ajustar con forma y H2H
        probs["home_win"] = form_adjuster.adjust_probability(
            probs["home_win"], home_features, h2h)
        probs["away_win"] = form_adjuster.adjust_probability(
            probs["away_win"], away_features, h2h)
        # Renormalizar
        total = probs["home_win"] + probs["draw"] + probs["away_win"]
        probs["home_win"] /= total
        probs["draw"] /= total
        probs["away_win"] /= total

        # Buscar cuotas del partido
        match_key = f"{home_team['name']}_{away_team['name']}".lower().replace(" ", "")
        odds_event = all_odds.get(match_key)

        if not odds_event:
            continue

        best_odds = extract_best_odds(odds_event)
        totals = extract_totals(odds_event)

        # Evaluar todos los mercados
        markets_to_check = [
            ("home_win", best_odds["home"]["odds"], f"{home_team['name']} gana"),
            ("away_win", best_odds["away"]["odds"], f"{away_team['name']} gana"),
            ("over_2.5", totals.get("over_2.5", {}).get("odds", 0), "Over 2.5 goles"),
            ("under_2.5", totals.get("under_2.5", {}).get("odds", 0), "Under 2.5 goles"),
        ]

        for market_key, odds, description in markets_to_check:
            if odds <= 1.0:
                continue

            model_prob = probs.get(market_key, 0)
            evaluation = evaluate_pick(model_prob, odds)

            if evaluation["is_value_bet"]:
                pick = {
                    "match": f"{home_team['name']} vs {away_team['name']}",
                    "league": league_name,
                    "market": description,
                    "odds": odds,
                    "model_prob": model_prob,
                    "ev": evaluation["ev"],
                    "ev_pct": evaluation["ev_pct"],
                    "kelly": evaluation["kelly"],
                    "kelly_pct": evaluation["kelly_pct"],
                    "rating": evaluation["rating"],
                    "lambda_home": poisson_result["lambda_home"],
                    "lambda_away": poisson_result["lambda_away"],
                    "timestamp": datetime.now().isoformat(),
                    "fixture_id": fixture.get("fixture", {}).get("id", 0)
                }
                value_picks.append(pick)

    print(f"      Picks con valor encontrados: {len(value_picks)}\n")

    # 4. Deduplicar
    print("[4/5] Verificando deduplicación...")
    new_picks = []
    for pick in value_picks:
        status = dedup.check_pick(pick)
        if status == "new":
            new_picks.append(pick)
            dedup.register_pick(pick)
        elif status == "improved" and pick["ev"] >= MIN_EV_REEMISSION:
            pick["_reemission"] = True
            new_picks.append(pick)
            dedup.update_pick(pick)
        # else: skip (already sent)

    print(f"      Picks nuevos para enviar: {len(new_picks)}\n")

    # 5. Enviar a Telegram
    print("[5/5] Enviando picks a Telegram...")
    for pick in sorted(new_picks, key=lambda x: x["ev"], reverse=True)[:5]:
        send_pick(pick)
        print(f"      ✅ Enviado: {pick['match']} - {pick['market']} @ {pick['odds']}")

    # Generar parlay si hay suficientes picks
    if len(new_picks) >= 3:
        parlay = generate_best_parlay(new_picks)
        if parlay:
            send_parlay(parlay)
            print(f"      ✅ Parlay enviado: {len(parlay['legs'])} piernas @ {parlay['combined_odds']:.2f}")

    # Guardar picks del día
    save_daily_picks(new_picks)

    print(f"\n{'='*60}")
    print(f"  VENTANA COMPLETADA - {len(new_picks)} picks emitidos")
    print(f"{'='*60}\n")

    return new_picks


def generate_best_parlay(picks: list, target_odds: float = 5.0, legs: int = 3) -> dict:
    """
    Genera el mejor parlay de N piernas apuntando a una cuota objetivo.
    Selecciona los picks con mayor EV y confianza.
    """
    # Ordenar por EV descendente
    sorted_picks = sorted(picks, key=lambda x: x["ev"], reverse=True)

    # Seleccionar las mejores piernas (evitar mismo partido)
    selected = []
    used_matches = set()

    for pick in sorted_picks:
        if pick["match"] not in used_matches and len(selected) < legs:
            selected.append(pick)
            used_matches.add(pick["match"])

    if len(selected) < 3:
        return None

    # Calcular cuota combinada
    combined_odds = 1.0
    for pick in selected:
        combined_odds *= pick["odds"]

    # Calcular EV del parlay
    combined_prob = 1.0
    for pick in selected:
        combined_prob *= pick["model_prob"]
    parlay_ev = EVCalculator.calculate_ev(combined_prob, combined_odds)

    return {
        "legs": selected,
        "combined_odds": combined_odds,
        "combined_prob": combined_prob,
        "ev": parlay_ev,
        "ev_pct": f"+{parlay_ev*100:.2f}%",
        "kelly": EVCalculator.calculate_kelly(combined_prob, combined_odds),
        "timestamp": datetime.now().isoformat()
    }


def save_daily_picks(picks: list):
    """Guarda los picks del día en la carpeta picks_diarios."""
    os.makedirs(PICKS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = os.path.join(PICKS_DIR, f"picks_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(picks, f, indent=2, ensure_ascii=False)

    print(f"      Guardado: {filename}")


if __name__ == "__main__":
    picks = run_prediction_window()
    if picks:
        print(f"\nResumen de picks:")
        for p in picks:
            print(f"  {p['rating']} {p['match']} | {p['market']} @ {p['odds']} | EV: {p['ev_pct']}")
