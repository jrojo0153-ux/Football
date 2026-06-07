import os

# === API KEYS (desde GitHub Secrets / Variables de entorno) ===
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# === API ENDPOINTS ===
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# === MODELO ===
KELLY_FRACTION = 0.25  # Kelly fraccional conservador
MIN_EV_THRESHOLD = 0.05  # Mínimo +5% EV para emitir pick
MIN_EV_REEMISSION = 0.15  # Mínimo +15% EV para re-emitir pick existente
CONFIDENCE_THRESHOLD = 0.60  # Probabilidad mínima del modelo

# === LIGAS MONITOREADAS ===
LEAGUES = {
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

# === RUTAS ===
PICKS_DIR = "picks_diarios"
ARCHIVE_DIR = "archivo_historico"
HISTORY_FILE = "history_master.csv"
MODEL_DIR = "models"

# === POISSON ===
POISSON_WEIGHT_HOME = 1.15  # Factor de ventaja local
POISSON_WEIGHT_AWAY = 0.85
