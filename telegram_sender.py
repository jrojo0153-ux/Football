import sys
import os
import html
import requests
from typing import Any, Dict, Optional

# Añadir directorio raíz a sys.path para asegurar importaciones
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Reutilización de conexiones TCP mediante un objeto Session de requests para mayor rendimiento
_session = requests.Session()


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convierte de forma segura cualquier valor a float evitando excepciones."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _esc(val: Any) -> str:
    """Escapa de forma segura caracteres HTML especiales para evitar que la API de Telegram falle."""
    return html.escape(str(val)) if val is not None else ""


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Envía un mensaje a Telegram de manera robusta usando un pool de conexiones."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("      ⚠️  Telegram no configurado (falta BOT_TOKEN o CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        response = _session.post(url, json=payload, timeout=12)
        if response.status_code == 200:
            return True
        print(f"      ❌ Error de API de Telegram ({response.status_code}): {response.text}")
        return False
    except requests.RequestException as e:
        print(f"      ❌ Error de red de Telegram: {e}")
        return False


def send_pick(pick: dict) -> bool:
    """Formatea y envía un pick individual de manera segura contra inyecciones HTML y nulos."""
    if not isinstance(pick, dict):
        print("      ❌ Error: El pick suministrado no es un diccionario válido.")
        return False

    reemission = "🔄 ACTUALIZACIÓN" if pick.get("_reemission") else "🎯 NUEVO PICK"
    rating = _esc(pick.get("rating", ""))
    match = _esc(pick.get("match", "Partido Desconocido"))
    
    league_raw = pick.get("league", "Liga Desconocida")
    league = _esc(str(league_raw).replace('_', ' ').title())
    
    market = _esc(pick.get("market", "N/A"))
    odds = _safe_float(pick.get("odds", 1.00))
    ev_pct = _esc(pick.get("ev_pct", "0.00%"))
    model_prob = _safe_float(pick.get("model_prob", 0.0))
    kelly_pct = _esc(pick.get("kelly_pct", "0.00%"))
    
    lambda_home = _safe_float(pick.get("lambda_home", 0.0))
    lambda_away = _safe_float(pick.get("lambda_away", 0.0))

    message = (
        f"{reemission} {rating}\n\n"
        f"⚽ <b>{match}</b>\n"
        f"🏆 {league}\n\n"
        f"📊 Pick: <b>{market}</b>\n"
        f"💰 Cuota: <b>{odds:.2f}</b>\n"
        f"📈 EV: <b>{ev_pct}</b>\n"
        f"🎲 Prob. Modelo: {model_prob:.1%}\n"
        f"💵 Kelly: {kelly_pct} del bankroll\n\n"
        f"📐 Poisson: λ Local={lambda_home:.2f} | λ Visita={lambda_away:.2f}"
    )

    if pick.get("_reemission"):
        prev_ev = _safe_float(pick.get("_previous_ev", 0.0))
        message += f"\n\n⬆️ EV anterior: {prev_ev*100:.2f}% → Ahora: {ev_pct}"

    return send_message(message.strip())


def send_parlay(parlay: dict) -> bool:
    """Formatea y envía un parlay mitigando fallos por tipos inesperados o inyección de HTML."""
    if not isinstance(parlay, dict):
        print("      ❌ Error: El parlay suministrado no es un diccionario válido.")
        return False

    legs_text = ""
    for i, leg in enumerate(parlay.get("legs", []), 1):
        l_match = _esc(leg.get("match", "Partido Desconocido"))
        l_market = _esc(leg.get("market", "N/A"))
        l_odds = _safe_float(leg.get("odds", 1.00))
        l_ev_pct = _esc(leg.get("ev_pct", "0.00%"))
        legs_text += f"\n  {i}. {l_match}\n     → {l_market} @ {l_odds:.2f} (EV: {l_ev_pct})"

    combined_odds = _safe_float(parlay.get("combined_odds", 1.00))
    ev_pct = _esc(parlay.get("ev_pct", "0.00%"))
    combined_prob = _safe_float(parlay.get("combined_prob", 0.0))
    kelly = _safe_float(parlay.get("kelly", 0.0))

    message = (
        f"🎰 <b>PARLAY DEL DÍA</b> 🎰\n\n"
        f"📋 Piernas:{legs_text}\n\n"
        f"💰 Cuota combinada: <b>{combined_odds:.2f}</b>\n"
        f"📈 EV del parlay: <b>{ev_pct}</b>\n"
        f"🎲 Prob. combinada: {combined_prob:.2%}\n"
        f"💵 Kelly: {kelly*100:.2f}% del bankroll\n\n"
        f"⚠️ Recuerda: máximo 3-5% del bankroll en parlays."
    )
    return send_message(message.strip())


def send_daily_summary(summary: dict) -> bool:
    """Envía un resumen de rendimiento diario al cierre con formateo robusto."""
    if not isinstance(summary, dict):
        print("      ❌ Error: El resumen suministrado no es un diccionario válido.")
        return False

    total_picks = int(_safe_float(summary.get('total_picks', 0)))
    matches_covered = int(_safe_float(summary.get('matches_covered', 0)))
    wins = int(_safe_float(summary.get('wins', 0)))
    losses = int(_safe_float(summary.get('losses', 0)))
    hit_rate = _safe_float(summary.get('hit_rate', 0.0))
    roi = _safe_float(summary.get('roi', 0.0))
    brier_score = _safe_float(summary.get('brier_score', 0.25))

    status_icon = "🟢 Día positivo!" if roi > 0 else "🔴 Día negativo. El modelo aprenderá."

    message = (
        f"📊 <b>RESUMEN DEL DÍA</b> 📊\n\n"
        f"🎯 Picks emitidos: {total_picks}\n"
        f"⚽ Partidos cubiertos: {matches_covered}\n"
        f"✅ Aciertos: {wins}\n"
        f"❌ Fallos: {losses}\n"
        f"📈 Hit Rate: {hit_rate:.1%}\n"
        f"💰 ROI del día: {roi:+.2f}%\n"
        f"📐 Brier Score: {brier_score:.4f}\n\n"
        f"{status_icon}"
    )
    return send_message(message.strip())


def send_system_alert(alert_type: str, details: str) -> bool:
    """Envía alertas del sistema sanitizando caracteres especiales."""
    message = f"⚙️ <b>SISTEMA</b>: {_esc(alert_type)}\n\n{_esc(details)}"
    return send_message(message)


if __name__ == "__main__":
    # Test de funcionalidad
    test_pick = {
        "match": "Cruz Azul vs Chivas",
        "league": "liga_mx",
        "market": "Cruz Azul gana",
        "odds": 2.10,
        "model_prob": 0.55,
        "ev": 0.155,
        "ev_pct": "+15.50%",
        "kelly": 0.037,
        "kelly_pct": "3.70%",
        "rating": "⭐⭐⭐",
        "lambda_home": 1.85,
        "lambda_away": 0.92,
    }
    print("Enviando pick de prueba...")
    result = send_pick(test_pick)
    print(f"Resultado: {'✅' if result else '❌'}")