# Deploy en Hetzner

Sistema completo: scraping + NLP local con Ollama + alertas a Telegram.

## Recursos recomendados

- **CX22** (~4€/mes, 2 vCPU, 4GB RAM, 40GB) — alcanza si NO usás Ollama
- **CPX21** (~8€/mes, 3 vCPU, 4GB RAM, 80GB) — recomendado con Ollama (modelo 3B)
- **CPX31** (~14€/mes, 4 vCPU, 8GB RAM, 160GB) — si querés modelo 7B

Ollama con `llama3.2:3b` corre razonablemente en CPU sin GPU.

## 1. Provisioning

```bash
ssh root@TU_IP_HETZNER

apt update && apt upgrade -y
apt install -y docker.io docker-compose-v2 git ufw

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

adduser builder
usermod -aG docker builder
su - builder
```

## 2. Clonar y configurar

```bash
git clone TU_REPO argentina_insights
cd argentina_insights
cp .env.example .env
nano .env
```

Variables clave a llenar:
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (https://reddit.com/prefs/apps)
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` (https://my.telegram.org)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_CHAT_ID` (tu bot existente)
- `OLLAMA_URL=http://ollama:11434` (si usás el container)
- `OLLAMA_MODEL=llama3.2:3b` (default)

## 3. Levantar todo

```bash
docker compose up -d --build

# La primera vez Ollama tarda en bajar la imagen.
# Después hay que descargar el modelo:
docker compose exec ollama ollama pull llama3.2:3b

# Verificar que el modelo esté:
docker compose exec ollama ollama list
```

## 4. Primera autenticación Telegram (scraper)

```bash
docker compose run --rm scheduler python -c "
from telethon import TelegramClient
import os
client = TelegramClient(
    'data/telegram_session',
    int(os.environ['TELEGRAM_API_ID']),
    os.environ['TELEGRAM_API_HASH'],
)
client.start(phone=os.environ['TELEGRAM_PHONE'])
print('OK')
client.disconnect()
"
```

Pide código que llega como mensaje en Telegram. Una sola vez.

## 5. Verificar que Telegram bot funciona

```bash
# Test rápido de envío
docker compose run --rm scheduler python -c "
from alerts.telegram_notifier import TelegramNotifier
n = TelegramNotifier()
print('Enviando test...')
ok = n.send('🧪 Test de Argentina Insights')
print('OK' if ok else 'FALLÓ — revisá TELEGRAM_BOT_TOKEN y CHAT_ID')
"
```

## 6. Acceder al dashboard

Por defecto en `http://TU_IP:8501` (sin auth — peligroso).

### Opción recomendada: SSH tunnel

```bash
# Desde tu máquina local
ssh -L 8501:localhost:8501 builder@TU_IP
# Abrí http://localhost:8501
```

### Opción producción: Caddy con HTTPS

```bash
# Generar password hash
docker run --rm caddy:2-alpine caddy hash-password --plaintext "TU_PASS"

# Editar Caddyfile.example -> Caddyfile, poner dominio + hash
cp Caddyfile.example Caddyfile
nano Caddyfile

# Agregar caddy al docker-compose y levantar
docker compose up -d
```

## 7. Logs y monitoreo

```bash
# Logs del scheduler en vivo
docker compose logs -f scheduler

# Logs del dashboard
docker compose logs -f dashboard

# Logs de Ollama (para debug de NLP)
docker compose logs -f ollama

# Ver alertas pendientes
docker compose exec scheduler python -c "
from database.models import get_session
from alerts.migrations import Alert
s = get_session()
print(s.query(Alert).count(), 'alertas en total')
s.close()
"
```

## 8. Backup automático

```bash
crontab -e
```

Agregar:
```
0 5 * * * cd /home/builder/argentina_insights && \
    cp data/insights.db data/backups/insights_$(date +\%Y\%m\%d).db && \
    find data/backups -mtime +14 -delete
```

## 9. Sin Ollama (alternativa minimalista)

Si tu server es chico o no querés Ollama:

1. Comentá el servicio `ollama` en `docker-compose.yml`
2. En `.env`: `OLLAMA_ENABLED=false`
3. El sistema usa heurísticas en lugar de LLM

Funciona igual, solo que pain points son menos precisos.

## 10. Si ya tenés Ollama corriendo en el host

Comentá el servicio `ollama` del compose y poné en `.env`:

```
OLLAMA_URL=http://host.docker.internal:11434
```

Y agregá en compose para scheduler/dashboard:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## 11. Troubleshooting

**El scheduler no detecta alertas:** verificar que pasaron al menos 7 días de datos (BURN_IN_DAYS). Para testear antes, editar `alerts/detector.py` y bajar `BURN_IN_DAYS = 1`.

**Ollama timeout:** modelo muy grande para tu CPU. Probar `llama3.2:1b` (más rápido, menos preciso).

**Telegram bot no envía:** chequear que iniciaste conversación con `/start` al bot. El bot no puede iniciar conversación, vos sí.

**Reviews sin pain points:** correr manual:
```bash
docker compose exec scheduler python -m insights.nlp.pain_extractor --limit 200
```

## 12. Recursos típicos

Stack completo con Ollama:
- Scheduler: 250 MB RAM
- Dashboard: 200 MB RAM
- Ollama (idle): 500 MB RAM
- Ollama (procesando): 3-4 GB RAM (modelo 3B)

DB SQLite crece ~30-80 MB por mes con todos los scrapers activos. Para >1 año conviene migrar a PostgreSQL (cambio de URL en `.env`).
