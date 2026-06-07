import os
import sys
from datetime import datetime
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Configurar el sistema de logging estructurado formal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("data_fetcher")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_FOOTBALL_KEY, API_FOOTBALL_BASE, LEAGUES

# Configurar sesión HTTP con reintentos y tolerancia a fallos (Connection Pooling y Backoff)
session = requests.Session()
session.headers.update({
    "x-apisports-key": API_FOOTBALL_KEY,
    "Accept": "application/json"
})
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    raise_on_status=False
)
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))


def _make_request(endpoint: str, params: dict) -> dict:
    """Método auxiliar seguro para realizar peticiones HTTP."""
    url = f"{API_FOOTBALL_BASE.rstrip('/')}/{endpoint.lstrip('/')}"
    logger.info(f"Iniciando petición GET a: {url} con parámetros: {params}")
    try:
        response = session.get(url, params=params, timeout=12)
        if response.status_code == 200:
            logger.info(f"Petición exitosa a {url}")
            return response.json()
        else:
            logger.warning(f"Error de API al solicitar {url}. Código de estado: {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Error de red/petición en {url}: {str(e)}", exc_info=True)
    return {}


def get_fixtures_today(league_id: int, season: int = 2026) -> list:
    """Obtiene los partidos de hoy para una liga específica."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_fixtures_by_date(league_id, today, season)


def get_fixtures_by_date(league_id: int, date: str, season: int = 2026) -> list:
    """Obtiene partidos para una fecha específica."""
    params = {
        "league": league_id,
        "season": season,
        "date": date
    }
    data = _make_request("fixtures", params)
    return data.get("response") or []


def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    """Obtiene historial de enfrentamientos directos (Head to Head)."""
    params = {
        "h2h": f"{team1_id}-{team2_id}",
        "last": last
    }
    data = _make_request("fixtures/headtohead", params)
    return data.get("response") or []


def get_team_stats(team_id: int, league_id: int, season: int = 2026) -> dict:
    """Obtiene estadísticas completas de un equipo en una liga/temporada."""
    params = {
        "team": team_id,
        "league": league_id,
        "season": season
    }
    data = _make_request("teams/statistics", params)
    return data.get("response") or {}


def get_last_matches(team_id: int, last: int = 10) -> list:
    """Obtiene los últimos N partidos de un equipo."""
    params = {
        "team": team_id,
        "last": last
    }
    data = _make_request("fixtures", params)
    return data.get("response") or []


def get_standings(league_id: int, season: int = 2026) -> list:
    """Obtiene la tabla de posiciones de una liga."""
    params = {
        "league": league_id,
        "season": season
    }
    data = _make_request("standings", params)
    response = data.get("response") or []
    if response:
        league_data = response[0].get("league", {})
        standings = league_data.get("standings", [])
        if standings and isinstance(standings[0], list):
            return standings[0]
    return []


def extract_team_features(team_id: int, league_id: int, is_home: bool) -> dict:
    """
    Extrae features de un equipo para el modelo ML de forma segura contra nulos y tipos incorrectos.
    """
    stats = get_team_stats(team_id, league_id)
    last_matches = get_last_matches(team_id, last=10)

    if not stats:
        logger.warning(f"No se pudieron obtener estadísticas para el equipo {team_id} en la liga {league_id}")
        return {}

    # Goles promedio
    goals_for = stats.get("goals", {}).get("for", {}).get("average", {})
    goals_against = stats.get("goals", {}).get("against", {}).get("average", {})

    # Forma reciente (últimos 5 partidos)
    raw_form = stats.get("form") or ""
    form = raw_form[-5:] if isinstance(raw_form, str) else ""
    wins_last5 = form.count("W")
    draws_last5 = form.count("D")
    losses_last5 = form.count("L")

    # Clean sheets
    clean_sheets = stats.get("clean_sheet", {})

    # Calcular goles recientes de manera robusta
    recent_goals_for = 0
    recent_goals_against = 0
    recent_count = 0
    
    for match in last_matches[-5:]:
        goals = match.get("goals") or {}
        teams = match.get("teams") or {}
        home_team = teams.get("home") or {}
        
        home_id = home_team.get("id")
        if home_id is None:
            continue

        if home_id == team_id:
            recent_goals_for += goals.get("home") or 0
            recent_goals_against += goals.get("away") or 0
        else:
            recent_goals_for += goals.get("away") or 0
            recent_goals_against += goals.get("home") or 0
        recent_count += 1

    avg_recent_gf = recent_goals_for / max(recent_count, 1)
    avg_recent_ga = recent_goals_against / max(recent_count, 1)

    venue = "home" if is_home else "away"

    # Extracción segura de tipos numéricos
    def safe_float(source, key):
        if isinstance(source, dict):
            val = source.get(key)
        else:
            val = source
        try:
            return float(val or 0)
        except (ValueError, TypeError) as e:
            logger.warning(f"Error al transformar a float la clave '{key}' del equipo {team_id}: {str(e)}")
            return 0.0

    def safe_int(source, key):
        if isinstance(source, dict):
            val = source.get(key)
        else:
            val = source
        try:
            return int(val or 0)
        except (ValueError, TypeError) as e:
            logger.warning(f"Error al transformar a entero la clave '{key}' del equipo {team_id}: {str(e)}")
            return 0

    return {
        "team_id": team_id,
        "avg_goals_for": safe_float(goals_for, venue),
        "avg_goals_against": safe_float(goals_against, venue),
        "avg_recent_gf": avg_recent_gf,
        "avg_recent_ga": avg_recent_ga,
        "wins_last5": wins_last5,
        "draws_last5": draws_last5,
        "losses_last5": losses_last5,
        "form_points": wins_last5 * 3 + draws_last5,
        "clean_sheets_total": safe_int(clean_sheets, "total"),
        "is_home": int(is_home),
    }


def get_all_today_fixtures() -> list:
    """Obtiene TODOS los partidos de hoy de todas las ligas monitoreadas de forma segura."""
    all_fixtures = []
    logger.info("Iniciando recopilación de partidos para el día de hoy.")
    for league_name, league_info in LEAGUES.items():
        league_id = league_info.get("id")
        if not league_id:
            logger.warning(f"No se encontró un ID de liga configurado para {league_name}")
            continue
        logger.info(f"Obteniendo partidos de hoy para: {league_name} (ID: {league_id})")
        fixtures = get_fixtures_today(league_id)
        for f in fixtures:
            f["_league_name"] = league_name
            f["_odds_key"] = league_info.get("odds_key")
        all_fixtures.extend(fixtures)
    logger.info(f"Búsqueda finalizada. Total de partidos encontrados hoy: {len(all_fixtures)}")
    return all_fixtures


if __name__ == "__main__":
    logger.info("Obteniendo partidos de hoy...")
    fixtures = get_all_today_fixtures()
    logger.info(f"Total partidos encontrados: {len(fixtures)}")
    for f in fixtures:
        teams = f.get("teams") or {}
        home = teams.get("home", {}).get("name", "Desconocido")
        away = teams.get("away", {}).get("name", "Desconocido")
        logger.info(f"  {home} vs {away} ({f.get('_league_name', 'Liga Desconocida')})")