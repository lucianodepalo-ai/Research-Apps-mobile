# Dockerfile multi-purpose: corre scheduler o dashboard según comando
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Argentina/Buenos_Aires

# Python deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# Playwright browsers (requerido para TikTok scraper)
RUN playwright install --with-deps chromium

# Código
COPY . .

# Volúmenes para persistir DB, sesiones y logs
VOLUME ["/app/data", "/app/logs"]

EXPOSE 8501

# Default: scheduler. Override con docker-compose para dashboard.
CMD ["python", "scheduler.py"]
