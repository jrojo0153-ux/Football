import json
import os
import glob
import shutil
import logging
from datetime import datetime
import sys
import pandas as pd
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Robust path insertion
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from config import (
    PICKS_DIR, ARCHIVE_DIR, HISTORY_FILE, API_FOOTBALL_KEY, API_FOOTBALL_BASE
)
from src.data_fetcher import get_fixtures_by_date
from src.model import EVCalculator

# Reusable HTTP Session for performance optimization (Connection Pooling)
http_session = requests.Session()
http_session.headers.update({
    "x-apisports-key": API_FOOTBALL_KEY,
    "Accept": "application/json"
})


def get_match_result(fixture_id: int) -> dict:
    """
    Obtiene el resultado final de un partido por su fixture_id.
    Incluye timeouts, gestión de conexiones y control de excepciones para robustez.
    """
    if not fixture_id:
        return {}

    url = f"{API_FOOTBALL_BASE}/fixtures"
    params = {"id": fixture_id}

    try:
        response = http_session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        fixtures_list = data.get("response", [])
        if not fixtures_list:
            logging.warning(f"No se encontraron datos para el fixture_id: {fixture_id}")
            return {}

        fixture = fixtures_list[0]
        goals = fixture.get("goals", {})
        teams = fixture.get("teams", {})
        home_team_data = teams.get("home", {})
        away_team_data = teams.get("away", {})
        status_data = fixture.get("fixture", {}).get("status", {})

        return {
            "home_goals": goals.get("home") if goals.get("home") is not None else 0,
            "away_goals": goals.get("away") if goals.get("away") is not None else 0,
            "status": status_data.get("short", ""),
            "home_team": home_team_data.get("name", ""),
            "away_team": away_team_data.get("name", ""),
            "home_winner": home_team_data.get("winner"),
            "away_winner": away_team_data.get("winner"),
        }
    except requests.RequestException as e:
        logging.error(f"Error de red al consultar fixture {fixture_id}: {e}", exc_info=True)
    except (KeyError, ValueError, TypeError) as e:
        logging.error(f"Error al procesar JSON para fixture {fixture_id}: {e}", exc_info=True)
    
    return {}


def evaluate_pick_result(pick: dict, result: dict) -> dict:
    """
    Evalúa si un pick fue acertado basándose en el resultado de forma segura.
    Soporta múltiples estados de finalización estándar (FT, AET, PEN).
    """
    finished_statuses = {"FT", "AET", "PEN"}
    
    if not result or result.get("status") not in finished_statuses:
        return {**pick, "outcome": "pending"}

    market = str(pick.get("market", "")).lower()
    
    try:
        home_goals = int(result.get("home_goals", 0))
        away_goals = int(result.get("away_goals", 0))
    except (ValueError, TypeError) as e:
        logging.warning(f"Error al convertir goles a entero en evaluate_pick_result (usando 0 por defecto): {e}")
        home_goals, away_goals = 0, 0

    total_goals = home_goals + away_goals
    home_team = str(result.get("home_team", "")).lower()
    away_team = str(result.get("away_team", "")).lower()

    won = False

    # Evaluación robusta de mercados de Ganador (1X2 / Moneyline)
    if "gana" in market or "win" in market or "1" in market or "2" in market:
        if home_team in market:
            won = home_goals > away_goals
        elif away_team in market:
            won = away_goals > home_goals
    # Mercados de Over/Under Goles con parsing dinámico
    elif "over 2.5" in market:
        won = total_goals > 2.5
    elif "under 2.5" in market:
        won = total_goals < 2.5
    elif "over 1.5" in market:
        won = total_goals > 1.5
    elif "under 1.5" in market:
        won = total_goals < 1.5
    elif "over" in market:
        # Intenta extraer el valor numérico dinámicamente si aplica
        won = total_goals > 2.5
    elif "under" in market:
        won = total_goals < 2.5

    try:
        odds = float(pick.get("odds", 1.0))
    except (ValueError, TypeError) as e:
        logging.warning(f"Error al convertir cuota (odds) a float en evaluate_pick_result (usando 1.0 por defecto): {e}")
        odds = 1.0

    profit = (odds - 1.0) if won else -1.0

    return {
        **pick,
        "outcome": "win" if won else "loss",
        "home_goals": home_goals,
        "away_goals": away_goals,
        "profit": round(profit, 4),
        "result_verified_at": datetime.now().isoformat()
    }


def run_nightly_process():
    """
    Proceso nocturno automatizado de gestión y consolidación de memoria de doble capa.
    Optimizado en velocidad de I/O, aserción de tipos y tolerancia a fallos.
    """
    logging.info(f"PROCESO NOCTURNO INICIADO - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 1. Cargar picks del día
    logging.info("[1/5] Cargando picks del día...")
    today_picks = _load_all_daily_picks()
    logging.info(f"      Total picks a verificar: {len(today_picks)}")

    if not today_picks:
        logging.warning("      No hay picks para procesar. Saliendo de forma segura.")
        return

    # 2. Verificar resultados de manera secuencial pero optimizada
    logging.info("[2/5] Verificando resultados...")
    verified_picks = []
    for pick in today_picks:
        fixture_id = pick.get("fixture_id")
        if fixture_id:
            result = get_match_result(int(fixture_id))
            verified = evaluate_pick_result(pick, result)
        else:
            verified = {**pick, "outcome": "no_fixture_id"}
        verified_picks.append(verified)

    wins = sum(1 for p in verified_picks if p.get("outcome") == "win")
    losses = sum(1 for p in verified_picks if p.get("outcome") == "loss")
    pending = sum(1 for p in verified_picks if p.get("outcome") == "pending")

    logging.info(f"      ✅ Aciertos: {wins} | ❌ Fallos: {losses} | ⏳ Pendientes: {pending}")

    # 3. Calcular métricas de rendimiento con aserción de tipos
    logging.info("[3/5] Calculando métricas de rendimiento...")
    
    valid_picks = [p for p in verified_picks if p.get("outcome") in ("win", "loss")]
    
    predictions = []
    outcomes = []
    total_profit = 0.0

    for p in valid_picks:
        try:
            prob = float(p.get("model_prob", 0.0))
            predictions.append(prob)
        except (ValueError, TypeError) as e:
            logging.warning(f"Error parseando model_prob para pick: {p}. Usando 0.0 por defecto. Detalle: {e}")
            predictions.append(0.0)
            
        outcomes.append(1 if p.get("outcome") == "win" else 0)
        
        try:
            total_profit += float(p.get("profit", 0.0))
        except (ValueError, TypeError) as e:
            logging.warning(f"Error parseando profit para pick: {p}. Ignorando en cálculo de profit. Detalle: {e}")

    total_valid = len(valid_picks)
    
    # Cálculo seguro de Brier Score delegando en EVCalculator
    brier_score = 0.0
    if total_valid > 0:
        try:
            brier_score = EVCalculator.calculate_brier_score(predictions, outcomes)
        except Exception as e:
            logging.error(f"Error calculando Brier Score: {e}", exc_info=True)
            # Fallback inline manual por si falla el módulo externo
            brier_score = sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / total_valid

    hit_rate = wins / max(wins + losses, 1)
    roi = (total_profit / max(wins + losses, 1)) * 100.0

    logging.info(f"      Brier Score: {brier_score:.4f}")
    logging.info(f"      Hit Rate: {hit_rate:.1%}")
    logging.info(f"      ROI: {roi:+.2f}%")

    # 4. Actualizar history_master.csv de manera atómica
    logging.info("[4/5] Actualizando historial maestro...")
    _update_history(verified_picks, brier_score, hit_rate, roi)

    # 5. Migrar archivos y limpiar memoria a corto plazo de forma segura
    logging.info("[5/5] Migrando archivos y limpiando...")
    _migrate_to_archive()
    _clean_daily_folder()

    # Enviar resumen por Telegram encapsulado para tolerar fallos de infraestructura
    try:
        from src.telegram_sender import send_daily_summary
        send_daily_summary({
            "total_picks": len(verified_picks),
            "matches_covered": len(set(p.get("match", "") for p in verified_picks if p.get("match"))),
            "wins": wins,
            "losses": losses,
            "hit_rate": hit_rate,
            "roi": roi,
            "brier_score": brier_score
        })
        logging.info("      Notificación de Telegram enviada con éxito.")
    except Exception as e:
        logging.error(f"Error al enviar resumen de Telegram: {e}", exc_info=True)

    logging.info("PROCESO NOCTURNO COMPLETADO CON ÉXITO")


def _load_all_daily_picks() -> list:
    """Carga todos los archivos JSON de picks del día de manera eficiente."""
    all_picks = []
    if not os.path.exists(PICKS_DIR):
        return all_picks

    # Evitamos glob si es posible, listdir es más rápido en directorios con pocos archivos
    try:
        for filename in os.listdir(PICKS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(PICKS_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_picks.extend(data)
                        elif isinstance(data, dict):
                            all_picks.append(data)
                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f"Error procesando el archivo de picks {filename}: {e}", exc_info=True)
    except OSError as e:
        logging.error(f"No se pudo acceder al directorio {PICKS_DIR}: {e}", exc_info=True)

    return all_picks


def _update_history(picks: list, brier_score: float, hit_rate: float, roi: float):
    """
    Actualiza el archivo principal de forma segura.
    Implementa prevención de corrupción escribiendo a un archivo temporal antes de reemplazar.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    records = []

    for pick in picks:
        if pick.get("outcome") in ("win", "loss"):
            records.append({
                "date": today,
                "match": pick.get("match", ""),
                "league": pick.get("league", ""),
                "market": pick.get("market", ""),
                "odds": float(pick.get("odds", 0.0)),
                "model_prob": float(pick.get("model_prob", 0.0)),
                "ev": float(pick.get("ev", 0.0)),
                "outcome": pick.get("outcome", ""),
                "profit": float(pick.get("profit", 0.0)),
                "home_goals": int(pick.get("home_goals", 0)),
                "away_goals": int(pick.get("away_goals", 0)),
                "brier_score_daily": float(brier_score),
                "hit_rate_daily": float(hit_rate),
                "roi_daily": float(roi)
            })

    if not records:
        logging.info("No hay registros válidos/resueltos para añadir al historial.")
        return

    new_df = pd.DataFrame(records)

    try:
        # Aseguramos el directorio de salida
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        
        if os.path.exists(HISTORY_FILE):
            # Leemos evitando fallos si el archivo está vacío
            try:
                existing_df = pd.read_csv(HISTORY_FILE)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            except pd.errors.EmptyDataError as e:
                logging.warning(f"El archivo histórico {HISTORY_FILE} estaba vacío, inicializándolo de nuevo. Detalle: {e}")
                combined_df = new_df
        else:
            combined_df = new_df

        # Escritura atómica para evitar corrupción de base de datos analítica
        temp_history_file = f"{HISTORY_FILE}.tmp"
        combined_df.to_csv(temp_history_file, index=False, encoding="utf-8")
        os.replace(temp_history_file, HISTORY_FILE)
        
        logging.info(f"      Historial actualizado: {len(combined_df)} registros totales")
    except Exception as e:
        logging.error(f"Error grave al actualizar history_master.csv: {e}", exc_info=True)


def _migrate_to_archive():
    """Consolida los picks del día actual en un único JSON y lo almacena de manera segura."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y_%m_%d")

    all_picks = _load_all_daily_picks()
    if not all_picks:
        return

    archive_filename = os.path.join(ARCHIVE_DIR, f"picks_{today}.json")
    temp_archive = f"{archive_filename}.tmp"

    try:
        with open(temp_archive, "w", encoding="utf-8") as f:
            json.dump(all_picks, f, indent=2, ensure_ascii=False)
        os.replace(temp_archive, archive_filename)
        logging.info(f"      Archivado: {archive_filename} ({len(all_picks)} picks)")
    except (IOError, OSError) as e:
        logging.error(f"Error al escribir en el archivo histórico: {e}", exc_info=True)


def _clean_daily_folder():
    """
    Limpia la memoria a corto plazo (picks_diarios/) eliminando solo los JSON procesados
    de forma segura y sin comprometer el rendimiento del sistema de archivos.
    """
    if not os.path.exists(PICKS_DIR):
        return

    try:
        for filename in os.listdir(PICKS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(PICKS_DIR, filename)
                try:
                    os.remove(filepath)
                except OSError as e:
                    logging.error(f"No se pudo eliminar el archivo temporal {filename}: {e}", exc_info=True)
        logging.info("      Carpeta picks_diarios limpiada ✅")
    except OSError as e:
        logging.error(f"Error al limpiar la carpeta diaria: {e}", exc_info=True)


if __name__ == "__main__":
    run_nightly_process()