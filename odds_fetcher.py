"""
odds_fetcher.py - Obtiene cuotas en tiempo real de The Odds API.
Usa ODDS_API_KEY para autenticación.
"""

import requests
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ODDS_API_KEY, ODDS_API_BASE, LEAGUES


def get_odds(sport_key: str, regions: str = "us,eu", markets: str = "h2h,totals") -> list:
    """
    Obtiene cuotas para un deporte/liga específica.
    
    Args:
        sport_key: Clave del deporte en The Odds API (ej: soccer_mexico_ligamx)
        regions: Regiones de casas de apuestas (us, eu, uk, au)
        markets: Mercados (h2h = 1X2, totals = Over/Under, spreads)
    
    Returns:
        Lista de eventos con cuotas
    """
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error {response.status_code}: {response.text}")
        return []


def get_live_odds(sport_key: str) -> list:
    """Obtiene cuotas de partidos en vivo."""
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds-live"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return []


def get_available_sports() -> list:
    """Lista todos los deportes/ligas disponibles."""
    url = f"{ODDS_API_BASE}/sports"
    params = {"apiKey": ODDS_API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return []


def extract_best_odds(event: dict, market: str = "h2h") -> dict:
    """
    Extrae las mejores cuotas de un evento para cada outcome.
    
    Returns:
        {
            "home": {"odds": 1.85, "bookmaker": "DraftKings"},
            "away": {"odds": 2.10, "bookmaker": "FanDuel"},
            "draw": {"odds": 3.40, "bookmaker": "Bet365"}
        }
    """
    best = {"home": {"odds": 0, "bookmaker": ""}, 
            "away": {"odds": 0, "bookmaker": ""},
            "draw": {"odds": 0, "bookmaker": ""}}
    
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    
    for bookmaker in event.get("bookmakers", []):
        for mkt in bookmaker.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt.get("outcomes", []):
                name = outcome["name"]
                price = outcome["price"]
                
                if name == home_team and price > best["home"]["odds"]:
                    best["home"] = {"odds": price, "bookmaker": bookmaker["title"]}
                elif name == away_team and price > best["away"]["odds"]:
                    best["away"] = {"odds": price, "bookmaker": bookmaker["title"]}
                elif name == "Draw" and price > best["draw"]["odds"]:
                    best["draw"] = {"odds": price, "bookmaker": bookmaker["title"]}
    
    return best


def extract_totals(event: dict) -> dict:
    """
    Extrae las mejores cuotas de Over/Under.
    
    Returns:
        {
            "over_2.5": {"odds": 1.90, "bookmaker": "..."},
            "under_2.5": {"odds": 1.95, "bookmaker": "..."}
        }
    """
    best = {}
    
    for bookmaker in event.get("bookmakers", []):
        for mkt in bookmaker.get("markets", []):
            if mkt["key"] != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                name = outcome["name"]  # "Over" or "Under"
                point = outcome.get("point", 2.5)
                price = outcome["price"]
                key = f"{name.lower()}_{point}"
                
                if key not in best or price > best[key]["odds"]:
                    best[key] = {"odds": price, "bookmaker": bookmaker["title"], "line": point}
    
    return best


def get_all_odds_today() -> dict:
    """
    Obtiene todas las cuotas del día para las ligas monitoreadas.
    
    Returns:
        Dict con sport_key como clave y lista de eventos como valor.
    """
    all_odds = {}
    for league_name, league_info in LEAGUES.items():
        sport_key = league_info["odds_key"]
        events = get_odds(sport_key)
        if events:
            all_odds[league_name] = events
            print(f"  {league_name}: {len(events)} eventos con cuotas")
    return all_odds


def calculate_implied_probability(decimal_odds: float) -> float:
    """Convierte cuota decimal a probabilidad implícita."""
    if decimal_odds <= 0:
        return 0
    return 1 / decimal_odds


def calculate_no_vig_probability(odds_list: list) -> list:
    """
    Elimina el vig/juice de las cuotas para obtener probabilidades reales.
    
    Args:
        odds_list: Lista de cuotas decimales [home, draw, away]
    
    Returns:
        Lista de probabilidades sin vig [p_home, p_draw, p_away]
    """
    implied = [1 / o for o in odds_list if o > 0]
    total = sum(implied)
    if total == 0:
        return [0] * len(odds_list)
    return [p / total for p in implied]


if __name__ == "__main__":
    print("Deportes disponibles:")
    sports = get_available_sports()
    for s in sports:
        if "soccer" in s.get("key", ""):
            print(f"  {s['key']}: {s['title']}")
    
    print("\nObteniendo cuotas del día...")
    all_odds = get_all_odds_today()
    for league, events in all_odds.items():
        print(f"\n{league}:")
        for event in events[:3]:
            print(f"  {event['home_team']} vs {event['away_team']}")
            best = extract_best_odds(event)
            print(f"    Home: {best['home']['odds']} | Draw: {best['draw']['odds']} | Away: {best['away']['odds']}")
