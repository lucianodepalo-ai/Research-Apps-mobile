"""Configuración central del sistema."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# === Paths ===
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / "insights.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# === Comportamiento general ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
USER_AGENT = "ArgentinaInsightsBot/1.0 (research; contact@example.com)"

MIN_DELAY_SEC = int(os.getenv("MIN_DELAY_SEC", "3"))
MAX_DELAY_SEC = int(os.getenv("MAX_DELAY_SEC", "8"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# === Geo ===
COUNTRY_CODE = "AR"
LANGUAGE = "es-AR"
TIMEZONE_OFFSET = -180  # UTC-3

# === Reddit ===
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ArgentinaInsights/1.0")

SUBREDDITS_AR = [
    "argentina", "AskArgentina", "merval", "devsarg",
    "republicaargentina", "Argaming", "Cordoba",
    "rosario", "buenosaires", "ArgentinaBenderStyle",
    "RepublicaArgentina", "argentinaeconomia",
]

# === YouTube ===
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# === Play Store ===
PLAY_STORE_LANG = "es"
PLAY_STORE_COUNTRY = "ar"

# === Suggest endpoints ===
GOOGLE_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
YOUTUBE_SUGGEST_URL = "https://suggestqueries-clients6.youtube.com/complete/search"

# === Playwright Tier 4 ===
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "")

ENABLE_INSTAGRAM = os.getenv("ENABLE_INSTAGRAM_SCRAPING", "false").lower() == "true"
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")

ENABLE_TWITTER = os.getenv("ENABLE_TWITTER_SCRAPING", "false").lower() == "true"
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME", "")
TWITTER_PASSWORD = os.getenv("TWITTER_PASSWORD", "")

ENABLE_TIKTOK = os.getenv("ENABLE_TIKTOK_SCRAPING", "true").lower() == "true"

# === Semillas para descubrimiento amplio ===
# Prefijos para autocomplete (Google/YouTube Suggest)
SEED_PREFIXES = [
    # Preguntas directas - revelan dudas
    "como", "como hago", "como hacer", "como puedo", "como saber",
    "que es", "que significa", "que pasa si", "cuanto",
    "cuando", "donde", "por que", "para que",
    # Trámites
    "como tramitar", "requisitos para", "turno para",
    "como solicitar", "donde sacar",
    # Finanzas
    "precio", "cuanto cuesta", "como invertir", "como ahorrar",
    "como ganar", "como cobrar",
    # Problemas
    "no puedo", "no me anda", "porque no", "como solucionar",
    # Compras
    "mejor", "comparacion", "vs", "opiniones", "es bueno",
    # Salud
    "sintomas", "remedio", "como curar",
]

# Categorías de Play Store para barrer apps competidoras
PLAY_STORE_CATEGORIES = [
    "FINANCE", "BUSINESS", "PRODUCTIVITY", "TOOLS",
    "LIFESTYLE", "HEALTH_AND_FITNESS", "EDUCATION",
    "SHOPPING", "FOOD_AND_DRINK", "TRAVEL_AND_LOCAL",
    "MAPS_AND_NAVIGATION", "NEWS_AND_MAGAZINES",
]

# Keywords semilla para buscar apps en Play Store
PLAY_STORE_SEED_QUERIES = [
    "calculadora", "dolar", "sueldo", "tramites argentina",
    "anses", "afip", "transporte", "colectivo", "subte",
    "feriados", "recetas", "turnos medicos", "obra social",
    "factura", "monotributo", "freelance", "delivery",
    "supermercado", "ofertas", "descuentos",
]

# Hashtags semilla para Instagram/TikTok AR
SOCIAL_HASHTAGS_AR = [
    "argentina", "buenosaires", "argentinatips",
    "tramitesargentina", "dolarblue", "ahorroargentina",
    "emprenderar", "freelancear", "vidaenargentina",
]

# === Telegram (https://my.telegram.org) ===
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")  # +5491150000000

# Canales públicos argentinos. Edita según vayas validando cuáles aportan.
TELEGRAM_CHANNELS_AR = [
    # Finanzas / dólar
    "dolarhoyok",
    "CriptoYa_oficial",
    "argendolar",
    # Trámites e info gubernamental
    "argentinaentramites",
    "miargentinaapp",
    # Trabajo / IT
    "trabajosit_arg",
    "remotearg",
    # Ofertas y compras
    "ofertas_argentinaa",
    "descuentosenargentina",
    # Noticias
    "infobaeoficial",
    "TNcomar",
]
