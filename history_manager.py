"""
history_manager.py - Gestión de Memoria de Doble Capa
Corto plazo: picks_diarios/ (memoria de trabajo)
Largo plazo: archivo_historico/ + history_master.csv (cerebro)

Ejecutar al cierre de jornada (11 PM) para:
1. Verificar resultados de los picks del día
2. Calcular Brier Score
3. Actualizar history_master.csv
4. Mover archivos a archivo_historico/
5. Limpiar picks_diarios/
"""

import json
import os
import glob
import shutil
import pandas as pd
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    PICKS_DIR, ARCHIVE_DIR, HISTORY_FILE, API_FOOTBALL_KEY, API_FOOTBALL_BASE
)
from src.data_fetcher import get_fixtures_by_date
from src.model import EVCalculator


def get_match_result(fixture_id: int) -> dict:
    """Obtiene el resultado final de un partido por su fixture_id."""
    import requests
    url = f"{API_FOOTBALL_BASE}/fixtures"
    params = {"id": fixture_id}
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json().get("response", [])
        if data:
            fixture = data[0]
            goals = fixture.get("goals", {})
            return {
                "home_goals": goals.get("home", 0),
                "away_goals": goals.get("away", 0),
                "status": fixture.get("fixture", {}).get("status", {}).get("short", ""),
                "home_team": fixture["teams"]["home"]["name"],
                "away_team": fixture["teams"]["away"]["name"],
                "home_winner": fixture["teams"]["home"].get("winner"),
                "away_winner": fixture["teams"]["away"].get("winner"),
            }
    return {}


def evaluate_pick_result(pick: dict, result: dict) -> dict:
    """
    Evalúa si un pick fue acertado basándose en el resultado.
    
    Returns:
        Pick actualizado con campos de resultado.
    """
    if not result or result.get("status") != "FT":
        return {**pick, "outcome": "pending"}

    market = pick.get("market", "").lower()
    home_goals = result["home_goals"]
    away_goals = result["away_goals"]
    total_goals = home_goals + away_goals

    won = False

    if "gana" in market or "win" in market:
        if result["home_team"].lower() in market.lower():
            won = home_goals > away_goals
        elif result["away_team"].lower() in market.lower():
            won = away_goals > home_goals
    elif "over 2.5" in market:
        won = total_goals > 2.5
    elif "under 2.5" in market:
        won = total_goals < 2.5
    elif "over 1.5" in market:
        won = total_goals > 1.5
    elif "under 1.5" in market:
        won = total_goals < 1.5

    profit = (pick["odds"] - 1) if won else -1

    return {
        **pick,
        "outcome": "win" if won else "loss",
        "home_goals": home_goals,
        "away_goals": away_goals,
        "profit": profit,
        "result_verified_at": datetime.now().isoformat()
    }


def run_nightly_process():
    """
    Proceso nocturno completo (11 PM):
    1. Verificar resultados
    2. Calcular métricas
    3. Actualizar historial
    4. Migrar archivos
    5. Limpiar carpeta diaria
    """
    print(f"\n{'='*60}")
    print(f"  PROCESO NOCTURNO - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Cargar picks del día
    print("[1/5] Cargando picks del día...")
    today_picks = _load_all_daily_picks()
    print(f"      Total picks a verificar: {len(today_picks)}")

    if not today_picks:
        print("      No hay picks para procesar. Saliendo.")
        return

    # 2. Verificar resultados
    print("[2/5] Verificando resultados...")
    verified_picks = []
    for pick in today_picks:
        fixture_id = pick.get("fixture_id", 0)
        if fixture_id:
            result = get_match_result(fixture_id)
            verified = evaluate_pick_result(pick, result)
        else:
            verified = {**pick, "outcome": "no_fixture_id"}
        verified_picks.append(verified)

    wins = sum(1 for p in verified_picks if p["outcome"] == "win")
    losses = sum(1 for p in verified_picks if p["outcome"] == "loss")
    pending = sum(1 for p in verified_picks if p["outcome"] == "pending")

    print(f"      ✅ Aciertos: {wins} | ❌ Fallos: {losses} | ⏳ Pendientes: {pending}")

    # 3. Calcular métricas
    print("[3/5] Calculando métricas de rendimiento...")
    predictions = [p["model_prob"] for p in verified_picks if p["outcome"] in ("win", "loss")]
    outcomes = [1 if p["outcome"] == "win" else 0 for p in verified_picks if p["outcome"] in ("win", "loss")]

    brier_score = EVCalculator.calculate_brier_score(predictions, outcomes)
    hit_rate = wins / max(wins + losses, 1)
    total_profit = sum(p.get("profit", 0) for p in verified_picks if p["outcome"] in ("win", "loss"))
    roi = total_profit / max(wins + losses, 1) * 100

    print(f"      Brier Score: {brier_score:.4f}")
    print(f"      Hit Rate: {hit_rate:.1%}")
    print(f"      ROI: {roi:+.2f}%")

    # 4. Actualizar history_master.csv
    print("[4/5] Actualizando historial maestro...")
    _update_history(verified_picks, brier_score, hit_rate, roi)

    # 5. Migrar y limpiar
    print("[5/5] Migrando archivos y limpiando...")
    _migrate_to_archive()
    _clean_daily_folder()

    # Enviar resumen por Telegram
    from src.telegram_sender import send_daily_summary
    send_daily_summary({
        "total_picks": len(verified_picks),
        "matches_covered": len(set(p.get("match", "") for p in verified_picks)),
        "wins": wins,
        "losses": losses,
        "hit_rate": hit_rate,
        "roi": roi,
        "brier_score": brier_score
    })

    print(f"\n{'='*60}")
    print(f"  PROCESO NOCTURNO COMPLETADO")
    print(f"{'='*60}\n")


def _load_all_daily_picks() -> list:
    """Carga todos los picks de la carpeta diaria."""
    all_picks = []
    if not os.path.exists(PICKS_DIR):
        return all_picks

    for filepath in glob.glob(os.path.join(PICKS_DIR, "*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                picks = json.load(f)
                all_picks.extend(picks)
        except (json.JSONDecodeError, IOError):
            continue

    return all_picks


def _update_history(picks: list, brier_score: float, hit_rate: float, roi: float):
    """Actualiza el archivo history_master.csv con los resultados del día."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Crear DataFrame de los picks verificados
    records = []
    for pick in picks:
        if pick["outcome"] in ("win", "loss"):
            records.append({
                "date": today,
                "match": pick.get("match", ""),
                "league": pick.get("league", ""),
                "market": pick.get("market", ""),
                "odds": pick.get("odds", 0),
                "model_prob": pick.get("model_prob", 0),
                "ev": pick.get("ev", 0),
                "outcome": pick.get("outcome", ""),
                "profit": pick.get("profit", 0),
                "home_goals": pick.get("home_goals", 0),
                "away_goals": pick.get("away_goals", 0),
                "brier_score_daily": brier_score,
                "hit_rate_daily": hit_rate,
                "roi_daily": roi
            })

    if not records:
        return

    new_df = pd.DataFrame(records)

    # Append al historial existente
    if os.path.exists(HISTORY_FILE):
        existing_df = pd.read_csv(HISTORY_FILE)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    combined_df.to_csv(HISTORY_FILE, index=False)
    print(f"      Historial actualizado: {len(combined_df)} registros totales")


def _migrate_to_archive():
    """Mueve los archivos del día a archivo_historico/ con nombre descriptivo."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y_%m_%d")

    if not os.path.exists(PICKS_DIR):
        return

    files = glob.glob(os.path.join(PICKS_DIR, "*.json"))
    if not files:
        return

    # Consolidar todos los picks del día en un solo archivo
    all_picks = []
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_picks.extend(json.load(f))
        except (json.JSONDecodeError, IOError):
            continue

    # Guardar en archivo_historico con nombre descriptivo
    archive_filename = os.path.join(ARCHIVE_DIR, f"picks_{today}.json")
    with open(archive_filename, "w", encoding="utf-8") as f:
        json.dump(all_picks, f, indent=2, ensure_ascii=False)

    print(f"      Archivado: {archive_filename} ({len(all_picks)} picks)")


def _clean_daily_folder():
    """Limpia la carpeta picks_diarios para el nuevo día."""
    if os.path.exists(PICKS_DIR):
        for f in glob.glob(os.path.join(PICKS_DIR, "*.json")):
            os.remove(f)
    print("      Carpeta picks_diarios limpiada ✅")


if __name__ == "__main__":
    run_nightly_process()
