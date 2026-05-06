# Argentina Insights — Sistema de Inteligencia de Búsquedas

Sistema de scraping profesional para detectar nichos desatendidos en Argentina cruzando múltiples fuentes de intención de búsqueda.

## Arquitectura

```
argentina_insights/
├── config/             # Settings, secretos, listas de fuentes
├── scrapers/
│   ├── api_based/      # Fuentes con API oficial (sin riesgo)
│   ├── suggest_based/  # Autocompletes públicos (Google, YouTube, Play)
│   └── playwright_based/ # Fuentes que requieren browser (Meta, X, etc.)
├── database/           # Modelos SQLAlchemy y repositorios
├── dashboard/          # Streamlit dashboard para análisis
├── data/               # SQLite database (insights.db)
├── logs/               # Logs de cada scraper
└── tests/              # Tests unitarios
```

## Flujo de datos

```
Fuentes → Scrapers → Normalizador → DB (SearchSignal) → Analyzer → Dashboard
                                          ↓
                                    Question Extractor → DB (Question)
                                          ↓
                                    Niche Detector → DB (NicheOpportunity)
```

## Fuentes implementadas

### Tier 1 — APIs oficiales (sin riesgo)
- Google Trends (pytrends) — búsquedas trending AR
- Reddit (PRAW) — r/argentina y otros
- YouTube Data API — búsquedas y videos AR
- Wikipedia Pageviews API — qué leen los argentinos
- DolarAPI — cotizaciones (proxy de interés económico)

### Tier 2 — Suggest público (riesgo bajo, gris)
- Google Suggest AR — autocompletado de Google segmentado
- YouTube Suggest AR — autocompletado de YouTube
- Play Store search — ranking + reviews de apps competidoras

### Tier 3 — Scraping respetuoso (riesgo medio)
- Mercado Libre Preguntas — intención de compra real
- Wikipedia búsquedas fallidas — vacíos informativos
- Google News RSS — temperatura mediática

### Tier 4 — Playwright con login (riesgo alto, opcional)
- TikTok hashtags AR (sin login, riesgo bajo)
- Instagram hashtags (con login, riesgo alto — DESHABILITADO por defecto)
- X/Twitter búsqueda (con login, riesgo alto — DESHABILITADO por defecto)

## Uso rápido

```bash
# 1. Instalar
pip install -r requirements.txt
playwright install chromium

# 2. Configurar
cp .env.example .env
# Editar .env con tus credenciales

# 3. Inicializar DB
python -m database.init_db

# 4. Correr scraper individual
python -m scrapers.suggest_based.google_suggest

# 5. Correr todos los scrapers (Tier 1 y 2)
python run_all.py --tier 1,2

# 6. Levantar dashboard
streamlit run dashboard/app.py
```
