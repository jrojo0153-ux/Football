import os
from types import MappingProxyType
from typing import Dict, Any, Final

def _get_required_env(key: str, default: str = "") -> str:
    """
    Obtiene una variable de entorno de forma segura.
    Lanza un aviso preventivo si la clave crítica no está configurada.
    """
    value = os.environ.get(key, default).strip()
    if not value:
        import warnings
        warnings.warn(f"La variable de entorno '{key}' no está configurada o está vacía.", RuntimeWarning)
    return value

# === API KEYS (Validación robusta desde el entorno) ===
ODDS_API_KEY: Final[str] = _get_required_env("ODDS_API_KEY")
API_FOOTBALL_KEY: Final[str] = _get_required_env("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN: Final[str] = _get_required_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: Final[str] = _get_required_env("TELEGRAM_CHAT_ID")

# === API ENDPOINTS (Inmutables) ===
ODDS_API_BASE: Final[str] = "https://api.the-odds-api.com/v4"
API_FOOTBALL_BASE: Final[str] = "https://v3.football.api-sports.io"

# === MODELO MATEMÁTICO (Tipado estricto e inmutable) ===
KELLY_FRACTION: Final[float] = 0.25       # Kelly fraccional conservador para gestión de riesgo
MIN_EV_THRESHOLD: Final[float] = 0.05     # Mínimo +5% EV esperado para emitir pick
MIN_EV_REEMISSION: Final[float] = 0.15    # Mínimo +15% EV para actualizar/re-emitir pick
CONFIDENCE_THRESHOLD: Final[float] = 0.60  # Probabilidad de éxito mínima del modelo (60%)

# === LIGAS MONITOREADAS (Uso de MappingProxyType para evitar mutación en runtime) ===
_LEAGUES_DATA: Dict[str, Dict[str, Any]] = {
    "liga_mx": {"id": 262, "odds_key": "soccer_mexico_ligamx"},
    "premier_league": {"id": 39, "odds_key": "soccer_epl"},
    "la_liga": {"id": 140, "odds_key": "soccer_spain_la_liga"},
    "serie_a": {"id": 135, "odds_key": "soccer_italy_serie_a"},
    "bundesliga": {"id": 78, "odds_key": "soccer_germany_bundesliga"},
    "ligue_1": {"id": 61, "odds_key": "soccer_france_ligue_one"},
    "mls": {"id": 253, "odds_key": "soccer_usa_mls"},
    "champions_league": {"id": 2, "odds_key": "soccer_uefa_champs_league"},
    "world_cup": {"id": 1, "odds_key": "soccer_fifa_world_cup"},
}
LEAGUES: MappingProxyType[str, Dict[str, Any]] = MappingProxyType(_LEAGUES_DATA)

# === RUTAS ABSOLUTAS (Evita vulnerabilidades de Path Traversal y dependencias de ejecución) ===
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PICKS_DIR: Final[str] = os.path.join(_BASE_DIR, "picks_diarios")
ARCHIVE_DIR: Final[str] = os.path.join(_BASE_DIR, "archivo_historico")
HISTORY_FILE: Final[str] = os.path.join(_BASE_DIR, "history_master.csv")
MODEL_DIR: Final[str] = os.path.join(_BASE_DIR, "models")

# Asegurar la existencia física de los directorios de trabajo
for _dir in (PICKS_DIR, ARCHIVE_DIR, MODEL_DIR):
    os.makedirs(_dir, exist_ok=True)

# === FACTORES DE DISTRIBUCIÓN POISSON ===
POISSON_WEIGHT_HOME: Final[float] = 1.15  # Ajuste por ventaja de localía
POISSON_WEIGHT_AWAY: Final[float] = 0.85  # Ajuste por desventaja de visitante