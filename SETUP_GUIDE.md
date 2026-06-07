# Guía de Configuración - Football ML System

## Paso 1: Obtener API Keys

### The Odds API (cuotas en vivo)
1. Ir a https://the-odds-api.com/
2. Crear cuenta gratuita (500 requests/mes gratis)
3. Copiar tu API Key

### API-Football (datos históricos)
1. Ir a https://www.api-football.com/ o https://rapidapi.com/api-sports/api/api-football
2. Crear cuenta (plan gratuito: 100 requests/día)
3. Copiar tu API Key

### Telegram Bot
1. Abrir Telegram, buscar @BotFather
2. Enviar `/newbot` y seguir instrucciones
3. Copiar el token del bot
4. Para obtener tu Chat ID: enviar un mensaje al bot, luego visitar `https://api.telegram.org/bot<TOKEN>/getUpdates`

## Paso 2: Crear Repositorio en GitHub

```bash
cd football-ml-system
git init
git add .
git commit -m "Initial commit: Football ML System"
git remote add origin https://github.com/TU_USUARIO/football-ml-system.git
git push -u origin main
```

## Paso 3: Configurar Secrets en GitHub

Ir a tu repositorio → Settings → Secrets and variables → Actions → New repository secret

Agregar estos 4 secrets:

| Secret Name | Valor |
|---|---|
| `ODDS_API_KEY` | Tu key de The Odds API |
| `API_FOOTBALL_KEY` | Tu key de API-Football |
| `TELEGRAM_BOT_TOKEN` | Token de tu bot de Telegram |
| `TELEGRAM_CHAT_ID` | Tu Chat ID de Telegram |

## Paso 4: Activar GitHub Actions

1. Ir a tu repositorio → Actions
2. Verificar que los workflows aparezcan:
   - `Daily Picks - Predicción de Fútbol ML`
   - `Nightly Update - Cierre de Jornada y Aprendizaje`
3. Puedes ejecutar manualmente con "Run workflow" para probar

## Paso 5: Verificar Funcionamiento

El sistema se ejecutará automáticamente:
- **8:00 AM CST** → Primera ventana de picks
- **12:00 PM CST** → Segunda ventana (con deduplicación)
- **4:00 PM CST** → Tercera ventana (con deduplicación)
- **11:00 PM CST** → Cierre: verifica resultados, aprende, migra datos

## Horarios (Cron en UTC)

| Hora CST | Hora UTC | Cron |
|---|---|---|
| 8:00 AM | 14:00 | `0 14 * * *` |
| 12:00 PM | 18:00 | `0 18 * * *` |
| 4:00 PM | 22:00 | `0 22 * * *` |
| 11:00 PM | 05:00 (+1 día) | `0 5 * * *` |

## Notas Importantes

- **picks_diarios/**: Memoria de trabajo. El sistema la consulta antes de enviar para no repetir picks.
- **archivo_historico/**: Diario de operación. Archivos renombrados como `picks_2026_06_05.json`.
- **history_master.csv**: Cerebro del sistema. Aquí aprende de errores pasados y ajusta pesos.
- **models/**: Pesos aprendidos del modelo (se actualizan cada noche).

## Ejecución Manual (Testing)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Exportar variables de entorno
export ODDS_API_KEY="tu_key"
export API_FOOTBALL_KEY="tu_key"
export TELEGRAM_BOT_TOKEN="tu_token"
export TELEGRAM_CHAT_ID="tu_chat_id"

# Ejecutar predicción
python -m src.predictor

# Ejecutar cierre nocturno
python -m src.history_manager
```
