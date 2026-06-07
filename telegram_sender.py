"""
telegram_sender.py - Envío de picks y parlays a Telegram.
Usa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
"""

import requests
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Envía un mensaje a Telegram."""
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
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException as e:
        print(f"      ❌ Error enviando a Telegram: {e}")
        return False


def send_pick(pick: dict) -> bool:
    """Formatea y envía un pick individual."""
    reemission = "🔄 ACTUALIZACIÓN" if pick.get("_reemission") else "🎯 NUEVO PICK"

    message = f"""
{reemission} {pick['rating']}

⚽ <b>{pick['match']}</b>
🏆 {pick['league'].replace('_', ' ').title()}

📊 Pick: <b>{pick['market']}</b>
💰 Cuota: <b>{pick['odds']}</b>
📈 EV: <b>{pick['ev_pct']}</b>
🎲 Prob. Modelo: {pick['model_prob']:.1%}
💵 Kelly: {pick['kelly_pct']} del bankroll

📐 Poisson: λ Local={pick['lambda_home']:.2f} | λ Visita={pick['lambda_away']:.2f}
"""

    if pick.get("_reemission"):
        prev_ev = pick.get("_previous_ev", 0)
        message += f"\n⬆️ EV anterior: {prev_ev*100:.2f}% → Ahora: {pick['ev_pct']}"

    return send_message(message.strip())


def send_parlay(parlay: dict) -> bool:
    """Formatea y envía un parlay."""
    legs_text = ""
    for i, leg in enumerate(parlay["legs"], 1):
        legs_text += f"\n  {i}. {leg['match']}\n     → {leg['market']} @ {leg['odds']} (EV: {leg['ev_pct']})"

    message = f"""
🎰 <b>PARLAY DEL DÍA</b> 🎰

📋 Piernas:{legs_text}

💰 Cuota combinada: <b>{parlay['combined_odds']:.2f}</b>
📈 EV del parlay: <b>{parlay['ev_pct']}</b>
🎲 Prob. combinada: {parlay['combined_prob']:.2%}
💵 Kelly: {parlay['kelly']*100:.2f}% del bankroll

⚠️ Recuerda: máximo 3-5% del bankroll en parlays.
"""
    return send_message(message.strip())


def send_daily_summary(summary: dict) -> bool:
    """Envía resumen diario al cierre."""
    message = f"""
📊 <b>RESUMEN DEL DÍA</b> 📊

🎯 Picks emitidos: {summary.get('total_picks', 0)}
⚽ Partidos cubiertos: {summary.get('matches_covered', 0)}
✅ Aciertos: {summary.get('wins', 0)}
❌ Fallos: {summary.get('losses', 0)}
📈 Hit Rate: {summary.get('hit_rate', 0):.1%}
💰 ROI del día: {summary.get('roi', 0):+.2f}%
📐 Brier Score: {summary.get('brier_score', 0.25):.4f}

{'🟢 Día positivo!' if summary.get('roi', 0) > 0 else '🔴 Día negativo. El modelo aprenderá.'}
"""
    return send_message(message.strip())


def send_system_alert(alert_type: str, details: str) -> bool:
    """Envía alertas del sistema."""
    message = f"⚙️ <b>SISTEMA</b>: {alert_type}\n\n{details}"
    return send_message(message)


if __name__ == "__main__":
    # Test
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
