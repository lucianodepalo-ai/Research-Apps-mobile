# CLAUDE.md

> Contexto operativo para Claude Code. Leer completo antes de modificar el repo.

## Qué es este proyecto

**Argentina Insights** es un sistema de inteligencia de mercado que detecta nichos desatendidos en Argentina cruzando datos de búsqueda, redes y apps competidoras. El output final son **oportunidades accionables** para construir aplicaciones móviles monetizables.

El usuario es un creador de apps. El proyecto sirve dos roles:

1. **Investigador automático**: corre 24/7, recolecta señales de demanda y oferta del mercado argentino.
2. **Asistente de decisiones**: presenta oportunidades con tesis, MVP sugerido y modelo de monetización para que el usuario decida qué construir.

El sistema NO es una app comercial. Es la herramienta interna que el usuario usa para descubrir qué app construir después.

## Arquitectura mental

```
┌─────────────────────────────────────────────────────────────┐
│  RECOLECCIÓN (scrapers/)                                     │
│  Tier 1 APIs oficiales · Tier 2 Suggest · Tier 4 Playwright │
└──────────────────────────┬──────────────────────────────────┘
                           │ SearchSignal, Question, AppCompetitor, AppReview
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  PROCESAMIENTO                                               │
│  database/analyzer.py  → NicheOpportunity                    │
│  insights/nlp/         → pain_points, feature_requests       │
│  insights/trend_analysis.py → comparativas temporales        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  ALERTAS (alerts/)                                           │
│  detector.py → Alert  →  telegram_notifier.py → bot          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  PRESENTACIÓN                                                │
│  dashboard/ Streamlit (10 vistas)                            │
│  insights/opportunity_generator.py → tarjetas de negocio     │
└─────────────────────────────────────────────────────────────┘
```

Todos los componentes leen y escriben en SQLite (`data/insights.db`). No hay APIs internas — el "bus" es la base de datos.

## Estructura de directorios

```
argentina_insights/
├── config/
│   └── settings.py              # TODO va por env vars + .env
├── database/
│   ├── models.py                # SQLAlchemy: 6 tablas
│   ├── repository.py            # CRUD + queries de análisis
│   └── analyzer.py              # NicheAnalyzer (calcula NicheOpportunity)
├── scrapers/
│   ├── base.py                  # BaseScraper abstracta (TODOS heredan de acá)
│   ├── api_based/               # Tier 1 - sin riesgo legal
│   │   ├── reddit_scraper.py    # PRAW
│   │   ├── play_store.py        # google-play-scraper
│   │   └── telegram_scraper.py  # Telethon, canales públicos
│   ├── suggest_based/           # Tier 2 - autocompletes públicos
│   │   ├── google_suggest.py
│   │   └── youtube_suggest.py
│   └── playwright_based/        # Tier 4 - RIESGO ALTO, deshabilitado por default
│       ├── browser_manager.py   # Anti-detección, sesiones reusables
│       ├── tiktok_scraper.py    # sin login (lo más seguro de Tier 4)
│       ├── instagram_scraper.py # con login (riesgo de ban)
│       └── twitter_scraper.py   # con login (riesgo de ban)
├── insights/
│   ├── opportunity_generator.py # Cerebro: convierte data en oportunidades
│   ├── trend_analysis.py        # Comparativas temporales y series
│   └── nlp/
│       ├── ollama_client.py     # Cliente HTTP con cache + fallback
│       └── pain_extractor.py    # Extrae pain_points de reviews 1-2★
├── alerts/
│   ├── migrations.py            # Tabla Alert
│   ├── detector.py              # 5 tipos de alerta con anti-ruido
│   └── telegram_notifier.py     # Bot de Telegram (alertas + digest)
├── dashboard/
│   ├── app.py                   # Router principal Streamlit
│   └── views/                   # Una vista = un archivo
│       ├── opportunities.py     # ⭐ vista estrella
│       ├── alerts_view.py
│       ├── trends_compare.py
│       ├── overview.py
│       ├── niches.py
│       ├── questions.py
│       ├── competitors.py
│       ├── pain_points.py
│       ├── terms_explorer.py
│       └── monitoring.py
├── data/                        # SQLite + sesiones (volumen Docker)
├── logs/
├── scheduler.py                 # APScheduler: todo el pipeline
├── run_all.py                   # CLI manual para correr scrapers
├── docker-compose.yml           # scheduler + dashboard + ollama
├── Dockerfile
├── .env.example
└── DEPLOY.md                    # Hetzner step-by-step
```

## Modelo de datos

Las 7 tablas. Antes de hacer queries nuevas, revisar `database/models.py`.

| Tabla | Qué guarda | Granularidad |
|---|---|---|
| `search_signals` | Cualquier observación de interés sobre un término | 1 fila por (fuente, término, captura) |
| `questions` | Preguntas concretas detectadas, deduplicadas por hash | 1 fila por pregunta única, contador `times_seen` |
| `app_competitors` | Apps del Play Store argentino | 1 fila por `app_id`, se hace upsert |
| `app_reviews` | Reviews de Play Store | 1 fila por `review_id` |
| `niche_opportunities` | Output del NicheAnalyzer | 1 fila por categoría |
| `niche_snapshots` | Histórico diario de niche_opportunities | 1 fila por (niche, día) |
| `alerts` | Eventos detectados por detector.py | 1 fila por evento, con dedup por fingerprint |
| `scrape_runs` | Auditoría de cada corrida de scraper | 1 fila por ejecución |

**Convención clave**: `term` siempre se guarda normalizado (lowercase, sin acentos, vía `unidecode`). El campo `raw_term` guarda el original. Si comparás strings, usá `term`.

## Convenciones de código

### Nuevos scrapers

Heredan de `BaseScraper`. La clase base maneja:
- Logging (loguru, archivo por scraper)
- Retries con backoff exponencial (`self.with_retries(fn, *args)`)
- Delay aleatorio entre requests (`self.random_delay()`)
- Auditoría en `scrape_runs`
- Inserción bulk en `search_signals`

Tu único trabajo: implementar `fetch() -> List[Dict]` donde cada dict tiene al menos `source` y `term`. Los demás campos son opcionales (`category`, `score`, `volume`, `url`, `extra`, etc.).

```python
from scrapers.base import BaseScraper

class MyNewScraper(BaseScraper):
    name = "my_source"     # único, usado en logs y filtros
    tier = 1               # 1=API, 2=suggest, 3=respetuoso, 4=playwright

    def fetch(self) -> list:
        signals = []
        for item in self.with_retries(self._call_api):
            signals.append({
                "source": "my_source",
                "term": item["text"],
                "category": "trabajo",   # opcional
                "score": item["score"],
                "url": item["url"],
                "extra": {"raw": item},
            })
            self.random_delay()
        return signals
```

Después agregarlo a `run_all.py` (`SCRAPERS_BY_TIER`) y `scheduler.py` (job correspondiente).

### Nuevas vistas del dashboard

Una vista = un archivo en `dashboard/views/` con función `render()` exportada. El router en `app.py` la importa y la llama. Convención:

```python
"""Vista: descripción corta."""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd

from database.models import get_session  # SIEMPRE pasar por session

@st.cache_data(ttl=60)
def _load(...):
    session = get_session()
    try:
        # query
        return df
    finally:
        session.close()      # SIEMPRE cerrar

def render():
    st.title("...")
    days = st.session_state.get("lookback_days", 30)  # del slider global
    # ...
```

Reglas:
- Siempre `try/finally` en sesiones de DB
- `@st.cache_data(ttl=60)` en funciones de carga (60s alcanza)
- Usar `st.session_state["lookback_days"]` para coherencia entre vistas
- Si exportás CSV: `st.download_button` con bytes UTF-8
- Para dataframes con muchas filas usar `height=500` y `hide_index=True`

### Nuevas alertas

En `alerts/detector.py`. Cada nuevo detector es un método de `AlertDetector` que devuelve `List[Alert]`. Mantener filosofía anti-ruido:

1. **Umbral absoluto**: la métrica debe superar un mínimo concreto (ej: ≥ 10 menciones). Sin esto, cosas chiquitas con mucho % crecimiento generan ruido.
2. **Fingerprint estable**: `self._fingerprint("kind", id_estable)` para que dedup funcione.
3. **Severity con criterio**: `critical` se reserva para "esto es urgente, mirá ya". `high` = mirar hoy. `medium` = mirar esta semana. `info` = registro.
4. **Mensaje estructurado**: Markdown legible, con título corto y body con métricas. Lo manda Telegram tal cual.

### Convenciones de configuración

- TODO secreto va en `.env` (gitignored). El `.env.example` se mantiene actualizado.
- Listas semilla (subreddits, canales, queries) van en `config/settings.py` como constantes editables.
- Umbrales de detección de alertas van como constantes al tope de `alerts/detector.py`. Cambian seguido al ajustar el sistema.

## Pipeline operativo (cómo corre todo)

`scheduler.py` orquesta todo con APScheduler en zona horaria Argentina. Los jobs:

```
SCRAPERS:
  suggest      cada 6h    (00:10, 06:10, 12:10, 18:10)
  social       cada 12h   (03:20, 15:20)         Reddit + Telegram
  play_store   cada 24h   (04:00)                Pesado, una vez

PROCESAMIENTO:
  analyzer     4x día     (01, 07, 13, 19:00)    Recalcula NicheOpportunity
  nlp          cada 12h   (05:30, 17:30)         Ollama sobre reviews 1-2★
  snapshot     1x día     (23:55)                Histórico de niches

ALERTAS:
  detect+push  cada 2h    (:15)                  Detector + alertas individuales
  digest       1x día     (09:00)                Resumen consolidado
```

**Burn-in**: el detector NO emite alertas hasta tener 7 días de datos en DB (`BURN_IN_DAYS` en `detector.py`). Para testing, bajar a 1.

## Tiers de scraping y riesgo legal

Esto es importante: el sistema separa fuentes por riesgo. **Antes de agregar fuentes nuevas, ubicarlas en el tier correcto**.

- **Tier 1**: APIs oficiales con permiso explícito. Riesgo cero. Incluye Reddit, Telegram (Telethon canales públicos), Play Store (google-play-scraper es lib estándar).
- **Tier 2**: Endpoints públicos sin TOS especial. Riesgo bajo. Suggests de Google y YouTube.
- **Tier 3**: Scraping de sitios públicos sin login, respetando robots.txt. Riesgo bajo-medio. (Reservado para futuro: Mercado Libre Preguntas, Wikipedia pageviews).
- **Tier 4**: Scraping con browser (Playwright), posiblemente con login. Riesgo legal alto, riesgo de ban alto. Por defecto **deshabilitado en `.env`**. Incluye Instagram, X, TikTok logueado.

**Regla**: nunca activar Tier 4 con cuenta personal del usuario. Siempre cuentas dedicadas. Si Claude Code agrega un nuevo scraper Tier 4, debe (a) usar variable `ENABLE_X_SCRAPING` para activación opcional, (b) loguear advertencia clara, (c) usar el `BrowserManager` que ya tiene anti-detección.

## Filosofía de detección de oportunidades

El sistema busca **demanda alta + oferta baja o mala**. Tres heurísticas principales:

1. **NicheAnalyzer (categoría agregada)**: cruza señales por categoría con apps existentes. `opportunity_score = demand_score - competition_score`. Apps con muchos installs y rating bajo *bajan* el competition_score (= oportunidad de reemplazo).

2. **OpportunityGenerator (tarjetas accionables)**: enriquece NicheOpportunity con tesis en lenguaje natural, complejidad estimada (1-5 según keywords técnicos), templates de monetización por categoría, y MVP features sugeridos. El score final ajusta por complejidad: apps simples valen más porque salen rápido.

3. **Underserved apps (apps individuales)**: no por categoría sino por app específica. `replacement_score = installs / rating`. Sirve para identificar reemplazos directos.

Si Claude Code va a refinar la detección: el lugar es `insights/opportunity_generator.py`. Los templates de monetización y MVP están como dicts editables — agregarles más categorías es fácil.

## Integración con Ollama

`OllamaClient` es un wrapper HTTP con tres comportamientos clave:

1. **Health check perezoso**: chequea disponibilidad la primera vez y cachea resultado en memoria. Si Ollama está caído, todas las llamadas devuelven `None` rápido sin fallar.
2. **Cache SQLite**: prompts idénticos no se reprocesan. Cache en `data/ollama_cache.db`.
3. **Fallback elegante**: cuando devuelve `None`, el `PainExtractor` usa heurísticas por keywords. El sistema nunca se rompe por LLM ausente.

**Modelos recomendados**:
- `llama3.2:3b` (default, 2GB RAM): velocidad/calidad balanceada en CPU
- `llama3.2:1b` (700MB RAM): si server muy chico
- `qwen2.5:7b`: si hay 8GB+ disponibles, mejor en español

Si agregás features que usen LLM: pasar siempre por `get_client()` (singleton), usar `generate_json()` con prompts que pidan estructura explícita, validar campos en el resultado, manejar `None` con un fallback.

## Cosas que NO hacer

- **No hacer commit de `.env`** ni de `data/*.db` ni de `data/*.session` (sesión Telegram). Ya están en `.gitignore`.
- **No usar `Session` directo de SQLAlchemy en vistas/scripts**. Siempre `get_session()` con try/finally.
- **No agregar dependencias pesadas** (transformers, torch) sin justificación. Para NLP usamos Ollama vía HTTP, no modelos en proceso.
- **No bypasear `BaseScraper`** creando scripts sueltos. La auditoría en `scrape_runs` y los retries dependen de eso.
- **No quitar el burn-in period** de alertas en producción. Los falsos positivos en los primeros días destruyen la confianza en el sistema.
- **No hardcodear credenciales** "para testear". Siempre `os.getenv()` con default vacío.
- **No quitar la deduplicación de alertas**. El `fingerprint` y `DEDUP_DAYS` son la diferencia entre un sistema útil y un canal de spam.
- **No alterar el modelo `term` normalizado**. Las queries de análisis dependen de que esté lowercase + sin acentos.

## Cosas que SÍ pedirle a Claude Code

Tareas típicas que se le pueden pedir con confianza:

- Agregar un nuevo scraper Tier 1/2 siguiendo el patrón
- Agregar una nueva vista al dashboard
- Crear un nuevo tipo de alerta en `detector.py`
- Refinar templates de monetización o MVP en `opportunity_generator.py`
- Mejorar el extractor de keywords / categorización en scrapers
- Agregar índices de base de datos si una query se vuelve lenta
- Migrar de SQLite a Postgres (cambio simple por SQLAlchemy)
- Agregar tests con pytest
- Mejorar prompts de Ollama en `pain_extractor.py`

Tareas que requieren confirmación del usuario antes:

- Modificar umbrales de detección en `detector.py` (afectan el ruido)
- Activar Tier 4 (Playwright con login)
- Cambiar el esquema de DB (requiere migración)
- Tocar el scheduler (afecta la frecuencia de uso de APIs externas)

## Estado actual del proyecto

- ✅ Recolección Tier 1 y 2 funcionando (Reddit, Play Store, Telegram, Google/YT Suggest)
- ✅ Tier 4 implementado pero deshabilitado por defecto (TikTok, IG, X)
- ✅ NLP con Ollama + fallback heurístico
- ✅ Sistema de alertas con anti-ruido y bot de Telegram
- ✅ Dashboard Streamlit con 10 vistas
- ✅ Comparativa temporal y snapshots
- ✅ Docker Compose listo para Hetzner
- ⏳ Pendiente: validación con datos reales (corre primera semana)
- ⏳ Pendiente: refinar templates de monetización con feedback del usuario

## Comandos frecuentes

```bash
# Local (desarrollo)
python run_all.py --init --tier 1,2 --analyze
streamlit run dashboard/app.py

# Scraper individual
python -m scrapers.suggest_based.google_suggest

# NLP manual
python -m insights.nlp.pain_extractor --limit 200

# Detector de alertas manual
python -m alerts.detector

# Test bot Telegram
python -c "from alerts.telegram_notifier import TelegramNotifier; \
TelegramNotifier().send('test')"

# Producción (Hetzner)
docker compose up -d --build
docker compose logs -f scheduler
docker compose exec ollama ollama pull llama3.2:3b
```

## Decisiones de diseño y por qué

- **SQLite y no Postgres desde el día 1**: alcanza hasta ~1M registros, simplifica deploy. La migración a Postgres es trivial con SQLAlchemy cuando haga falta.
- **Streamlit y no React**: el dashboard es para uso personal del builder, no producto. Streamlit permite iterar 10x más rápido sin frontend.
- **Ollama en Docker en lugar de OpenAI/Anthropic API**: privacidad de datos del scraping, costo cero, no rate limits. Calidad suficiente para clasificar quejas en español.
- **APScheduler en proceso, no Celery/Redis**: una máquina, un proceso. Sin overhead de broker.
- **Telethon en lugar de bot de Telegram para scraping**: los bots no leen canales públicos como cliente normal. Telethon usa la API de cliente, ve todo lo que ve un usuario. El bot se usa solo para *enviar* alertas (camino opuesto).
- **Burn-in period de 7 días**: con menos datos cualquier baseline es ruidoso y el sistema te avisaría todo. Mejor silencio inicial que falsa señal.
- **Cache de Ollama en SQLite separado**: si reseteás insights.db perdés DB pero no embeddings. Los prompts son determinísticos así que el cache vale meses.
