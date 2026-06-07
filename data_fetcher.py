"""
data_fetcher.py - Obtiene datos históricos de API-Football (api-sports.io)
Usa API_FOOTBALL_KEY para autenticación.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_FOOTBALL_KEY, API_FOOTBALL_BASE, LEAGUES


HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY
}


def get_fixtures_today(league_id: int, season: int = 2026) -> list:
    """Obtiene los partidos de hoy para una liga específica."""
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"{API_FOOTBALL_BASE}/fixtures"
    params = {
        "league": league_id,
        "season": season,
        "date": today
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        return response.json().get("response", [])
    return []


def get_fixtures_by_date(league_id: int, date: str, season: int = 2026) -> list:
    """Obtiene partidos para una fecha específica."""
    url = f"{API_FOOTBALL_BASE}/fixtures"
    params = {
        "league": league_id,
        "season": season,
        "date": date
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        return response.json().get("response", [])
    return []


def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    """Obtiene historial de enfrentamientos directos (Head to Head)."""
    url = f"{API_FOOTBALL_BASE}/fixtures/headtohead"
    params = {
        "h2h": f"{team1_id}-{team2_id}",
        "last": last
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        return response.json().get("response", [])
    return []


def get_team_stats(team_id: int, league_id: int, season: int = 2026) -> dict:
    """Obtiene estadísticas completas de un equipo en una liga/temporada."""
    url = f"{API_FOOTBALL_BASE}/teams/statistics"
    params = {
        "team": team_id,
        "league": league_id,
        "season": season
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        return response.json().get("response", {})
    return {}


def get_last_matches(team_id: int, last: int = 10) -> list:
    """Obtiene los últimos N partidos de un equipo."""
    url = f"{API_FOOTBALL_BASE}/fixtures"
    params = {
        "team": team_id,
        "last": last
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        return response.json().get("response", [])
    return []


def get_standings(league_id: int, season: int = 2026) -> list:
    """Obtiene la tabla de posiciones de una liga."""
    url = f"{API_FOOTBALL_BASE}/standings"
    params = {
        "league": league_id,
        "season": season
    }
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code == 200:
        data = response.json().get("response", [])
        if data:
            return data[0].get("league", {}).get("standings", [[]])[0]
    return []


def extract_team_features(team_id: int, league_id: int, is_home: bool) -> dict:
    """
    Extrae features de un equipo para el modelo ML.
    Retorna un diccionario con métricas clave.
    """
    stats = get_team_stats(team_id, league_id)
    last_matches = get_last_matches(team_id, last=10)

    if not stats:
        return {}

    # Goles promedio
    goals_for = stats.get("goals", {}).get("for", {}).get("average", {})
    goals_against = stats.get("goals", {}).get("against", {}).get("average", {})

    # Forma reciente (últimos 5 partidos)
    form = stats.get("form", "")[-5:]
    wins_last5 = form.count("W")
    draws_last5 = form.count("D")
    losses_last5 = form.count("L")

    # Clean sheets
    clean_sheets = stats.get("clean_sheet", {})

    # Calcular goles recientes
    recent_goals_for = 0
    recent_goals_against = 0
    recent_count = 0
    for match in last_matches[-5:]:
        goals = match.get("goals", {})
        if match["teams"]["home"]["id"] == team_id:
            recent_goals_for += goals.get("home", 0) or 0
            recent_goals_against += goals.get("away", 0) or 0
        else:
            recent_goals_for += goals.get("away", 0) or 0
            recent_goals_against += goals.get("home", 0) or 0
        recent_count += 1

    avg_recent_gf = recent_goals_for / max(recent_count, 1)
    avg_recent_ga = recent_goals_against / max(recent_count, 1)

    venue = "home" if is_home else "away"

    return {
        "team_id": team_id,
        "avg_goals_for": float(goals_for.get(venue, 0) or 0),
        "avg_goals_against": float(goals_against.get(venue, 0) or 0),
        "avg_recent_gf": avg_recent_gf,
        "avg_recent_ga": avg_recent_ga,
        "wins_last5": wins_last5,
        "draws_last5": draws_last5,
        "losses_last5": losses_last5,
        "form_points": wins_last5 * 3 + draws_last5,
        "clean_sheets_total": clean_sheets.get("total", 0) or 0,
        "is_home": int(is_home),
    }


def get_all_today_fixtures() -> list:
    """Obtiene TODOS los partidos de hoy de todas las ligas monitoreadas."""
    all_fixtures = []
    for league_name, league_info in LEAGUES.items():
        fixtures = get_fixtures_today(league_info["id"])
        for f in fixtures:
            f["_league_name"] = league_name
            f["_odds_key"] = league_info["odds_key"]
        all_fixtures.extend(fixtures)
    return all_fixtures


if __name__ == "__main__":
    print("Obteniendo partidos de hoy...")
    fixtures = get_all_today_fixtures()
    print(f"Total partidos encontrados: {len(fixtures)}")
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        print(f"  {home} vs {away} ({f['_league_name']})")
