"""
Orquestador: corre los scrapers según tier seleccionado.

Uso:
    python run_all.py --tier 1,2          # APIs + suggest (recomendado para empezar)
    python run_all.py --tier 1,2,4        # incluye Playwright (riesgo)
    python run_all.py --analyze           # solo correr el analyzer
    python run_all.py --tier 2 --analyze  # tier 2 + analyzer al final
"""
import argparse
import sys
from loguru import logger

from database.models import init_db
from database.analyzer import NicheAnalyzer

# Tier 1 - APIs oficiales
from scrapers.api_based.reddit_scraper import RedditScraper
from scrapers.api_based.play_store import PlayStoreScraper
from scrapers.api_based.telegram_scraper import TelegramScraper

# Tier 2 - Suggest
from scrapers.suggest_based.google_suggest import GoogleSuggestScraper
from scrapers.suggest_based.youtube_suggest import YouTubeSuggestScraper

# Tier 4 - Playwright
from scrapers.playwright_based.tiktok_scraper import TikTokScraper
from scrapers.playwright_based.instagram_scraper import InstagramScraper
from scrapers.playwright_based.twitter_scraper import TwitterScraper


SCRAPERS_BY_TIER = {
    1: [
        RedditScraper,
        PlayStoreScraper,
        TelegramScraper,
    ],
    2: [
        GoogleSuggestScraper,
        YouTubeSuggestScraper,
    ],
    4: [
        TikTokScraper,        # sin login (más seguro)
        InstagramScraper,     # con login (riesgo)
        TwitterScraper,       # con login (riesgo)
    ],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tier", type=str, default="1,2",
        help="Tiers a correr separados por coma (ej: 1,2,4)"
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="Correr el niche analyzer al final"
    )
    parser.add_argument(
        "--init", action="store_true",
        help="Inicializar DB primero"
    )
    args = parser.parse_args()

    if args.init:
        init_db()

    tiers = [int(t.strip()) for t in args.tier.split(",")]
    logger.info(f"Tiers seleccionados: {tiers}")

    total = 0
    for tier in tiers:
        scrapers = SCRAPERS_BY_TIER.get(tier, [])
        if not scrapers:
            logger.warning(f"Tier {tier} no tiene scrapers")
            continue
        logger.info(f"\n{'='*60}\nTIER {tier}\n{'='*60}")
        for ScraperClass in scrapers:
            try:
                instance = ScraperClass()
                items = instance.run()
                total += items
            except Exception as e:
                logger.exception(f"Falló {ScraperClass.__name__}: {e}")

    logger.info(f"\n=== TOTAL CAPTURADO: {total} señales ===")

    if args.analyze:
        logger.info("\n=== Corriendo analyzer ===")
        NicheAnalyzer().run()


if __name__ == "__main__":
    main()
