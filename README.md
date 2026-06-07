# Football ML Betting System

Sistema de Machine Learning para predicción de partidos de fútbol con valor esperado positivo (+EV).

## Arquitectura

```
football-ml-system/
├── .github/
│   └── workflows/
│       ├── daily_picks.yml          # Cron: 8AM, 12PM, 4PM (UTC-6)
│       └── nightly_update.yml       # Cron: 11PM - migración y aprendizaje
├── src/
│   ├── data_fetcher.py             # API-Football: datos históricos
│   ├── odds_fetcher.py             # The Odds API: cuotas en vivo
│   ├── model.py                    # Modelo ML (Poisson + Kelly + EV)
│   ├── predictor.py                # Motor de predicción principal
│   ├── deduplication.py            # Anti-spam y deduplicación
│   ├── telegram_sender.py          # Envío de picks a Telegram
│   └── history_manager.py          # Gestión de memoria (corto/largo plazo)
├── picks_diarios/                  # Memoria de trabajo (picks del día)
├── archivo_historico/              # Memoria a largo plazo
├── models/                         # Modelos entrenados
├── config.py                       # Configuración general
├── requirements.txt
└── README.md
```

## APIs Requeridas

- **API-Football** (RapidAPI): Datos históricos, estadísticas, H2H
- **The Odds API**: Cuotas en tiempo real de múltiples casas de apuestas
- **Telegram Bot API**: Envío de picks

## Secrets de GitHub

```
ODDS_API_KEY=tu_key_de_the_odds_api
API_FOOTBALL_KEY=tu_key_de_api_football
TELEGRAM_BOT_TOKEN=tu_token_de_bot
TELEGRAM_CHAT_ID=tu_chat_id
```

## Instalación

```bash
pip install -r requirements.txt
```

## Uso Manual

```bash
python src/predictor.py
```
