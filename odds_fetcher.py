import os
import sys
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Configuración del logger para manejo de errores robusto
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuración dinámica del path del sistema
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import ODDS_API_KEY, ODDS_API_BASE, LEAGUES
except ImportError:
    logger.error("No se pudo importar 'config'. Asegúrese de que el archivo exista y esté configurado correctamente.")
    ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
    ODDS_API_BASE = os.environ.get("ODDS_API_BASE", "https://api.the-odds-api.com/v4")
    LEAGUES = {}

# Optimización de red: Reutilización de conexiones (pooling) y reintentos automáticos (backoff)
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# Vulnerabilidad corregida: Evitar esperas infinitas definiendo tiempos límite (timeouts) de conexión y lectura
HTTP_TIMEOUT = (3.05, 10.0)


def get_odds(sport_key: str, regions: str = "us,eu", markets: str = "h2h,totals") -> list:
    """
    Obtiene cuotas para un deporte/liga específica de manera segura y eficiente.
    """
    if not ODDS_API_KEY:
        logger.error("La clave de API (ODDS_API_KEY) no está configurada.")
        return []

    url = f"{ODDS_API_BASE.rstrip('/')}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }
    try:
        response = session.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error de red obteniendo cuotas para {sport_key}: {e}")
        return []
    except ValueError:
        logger.error(f"Error parseando JSON de respuesta para {sport_key}")
        return []


def get_live_odds(sport_key: str) -> list:
    """Obtiene cuotas de partidos en vivo."""
    if not ODDS_API_KEY:
        logger.error("La clave de API (ODDS_API_KEY) no está configurada.")
        return []

    url = f"{ODDS_API_BASE.rstrip('/')}/sports/{sport_key}/odds-live"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    try:
        response = session.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error de red obteniendo cuotas en vivo para {sport_key}: {e}")
        return []
    except ValueError:
        logger.error(f"Error parseando JSON de respuesta en vivo para {sport_key}")
        return []


def get_available_sports() -> list:
    """Lista todos los deportes/ligas disponibles."""
    if not ODDS_API_KEY:
        logger.error("La clave de API (ODDS_API_KEY) no está configurada.")
        return []

    url = f"{ODDS_API_BASE.rstrip('/')}/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        response = session.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error de red obteniendo deportes disponibles: {e}")
        return []
    except ValueError:
        logger.error("Error parseando JSON de deportes disponibles")
        return []


def extract_best_odds(event: dict, market: str = "h2h") -> dict:
    """
    Extrae las mejores cuotas de un evento para cada outcome de manera segura.
    Normaliza strings para evitar fallos de coincidencia exactas por espacios o capitalización.
    """
    best = {
        "home": {"odds": 0.0, "bookmaker": ""}, 
        "away": {"odds": 0.0, "bookmaker": ""},
        "draw": {"odds": 0.0, "bookmaker": ""}
    }
    
    home_team = str(event.get("home_team", "")).strip().lower()
    away_team = str(event.get("away_team", "")).strip().lower()
    
    for bookmaker in event.get("bookmakers", []):
        bookmaker_title = bookmaker.get("title", "Unknown")
        for mkt in bookmaker.get("markets", []):
            if mkt.get("key") != market:
                continue
            for outcome in mkt.get("outcomes", []):
                name = str(outcome.get("name", "")).strip().lower()
                try:
                    price = float(outcome.get("price", 0.0))
                except (ValueError, TypeError):
                    continue
                
                if name == home_team:
                    if price > best["home"]["odds"]:
                        best["home"] = {"odds": price, "bookmaker": bookmaker_title}
                elif name == away_team:
                    if price > best["away"]["odds"]:
                        best["away"] = {"odds": price, "bookmaker": bookmaker_title}
                elif name in ("draw", "tie", "x"):
                    if price > best["draw"]["odds"]:
                        best["draw"] = {"odds": price, "bookmaker": bookmaker_title}
    
    return best


def extract_totals(event: dict) -> dict:
    """
    Extrae de forma segura las mejores cuotas de Over/Under para una línea de totales dada.
    """
    best = {}
    
    for bookmaker in event.get("bookmakers", []):
        bookmaker_title = bookmaker.get("title", "Unknown")
        for mkt in bookmaker.get("markets", []):
            if mkt.get("key") != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                name = outcome.get("name", "")
                if not name:
                    continue
                try:
                    point = float(outcome.get("point", 2.5))
                    price = float(outcome.get("price", 0.0))
                except (ValueError, TypeError):
                    continue
                
                key = f"{name.lower()}_{point}"
                
                if key not in best or price > best[key]["odds"]:
                    best[key] = {"odds": price, "bookmaker": bookmaker_title, "line": point}
    
    return best


def get_all_odds_today() -> dict:
    """
    Obtiene de forma eficiente todas las cuotas del día reutilizando la sesión HTTP.
    """
    all_odds = {}
    for league_name, league_info in LEAGUES.items():
        sport_key = league_info.get("odds_key")
        if not sport_key:
            logger.warning(f"La liga '{league_name}' no posee una clave de cuotas 'odds_key' válida.")
            continue
        events = get_odds(sport_key)
        if events:
            all_odds[league_name] = events
            print(f"  {league_name}: {len(events)} eventos con cuotas")
    return all_odds


def calculate_implied_probability(decimal_odds: float) -> float:
    """
    Convierte cuota decimal a probabilidad implícita.
    Corrección de bug: Evita divisiones entre cero y maneja valores menores o iguales a uno.
    """
    if decimal_odds <= 1.0:
        return 0.0
    return 1.0 / decimal_odds


def calculate_no_vig_probability(odds_list: list) -> list:
    """
    Elimina el vig/juice de las cuotas para obtener probabilidades reales.
    Maneja con seguridad valores erróneos o divisores nulos.
    """
    implied = [1.0 / o for o in odds_list if o > 1.0]
    total = sum(implied)
    if total <= 0:
        return [0.0] * len(odds_list)
    return [p / total for p in implied]


if __name__ == "__main__":
    print("Deportes disponibles:")
    sports = get_available_sports()
    for s in sports:
        sport_key = s.get("key", "")
        if "soccer" in sport_key:
            print(f"  {sport_key}: {s.get('title', '')}")
    
    print("\nObteniendo cuotas del día...")
    all_odds = get_all_odds_today()
    for league, events in all_odds.items():
        print(f"\n{league}:")
        for event in events[:3]:
            home = event.get('home_team', 'Unknown Home')
            away = event.get('away_team', 'Unknown Away')
            print(f"  {home} vs {away}")
            best = extract_best_odds(event)
            print(f"    Home: {best['home']['odds']} | Draw: {best['draw']['odds']} | Away: {best['away']['odds']}")