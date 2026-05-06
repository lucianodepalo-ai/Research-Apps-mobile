"""
Scheduler completo: orquesta scrapers + analyzer + NLP + alertas + notificaciones.

Pipeline diario:
1. Scrapers de suggest cada 6h (rápidos)
2. Reddit + Telegram cada 12h
3. Play Store cada 24h (pesado)
4. Analyzer 4x por día
5. NLP de pain points: cada 12h sobre reviews nuevas
6. Detector de alertas + envío a Telegram cada 2h
7. Snapshot diario de NicheOpportunity para histórico real
"""
import signal
import sys
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from database.models import init_db
from database.analyzer import NicheAnalyzer

from scrapers.api_based.reddit_scraper import RedditScraper
from scrapers.api_based.play_store import PlayStoreScraper
from scrapers.api_based.telegram_scraper import TelegramScraper
from scrapers.suggest_based.google_suggest import GoogleSuggestScraper
from scrapers.suggest_based.youtube_suggest import YouTubeSuggestScraper

from insights.nlp.pain_extractor import PainExtractor
from insights.trend_analysis import take_niche_snapshot

from alerts.migrations import migrate as migrate_alerts
from alerts.detector import AlertDetector
from alerts.telegram_notifier import TelegramNotifier


# ============================================================
# Jobs
# ============================================================

def run_suggest():
    logger.info("=== JOB: SUGGEST ===")
    for ScraperCls in (GoogleSuggestScraper, YouTubeSuggestScraper):
        try:
            ScraperCls().run()
        except Exception as e:
            logger.exception(f"{ScraperCls.__name__}: {e}")


def run_social():
    logger.info("=== JOB: SOCIAL ===")
    try:
        RedditScraper(posts_per_sub=100).run()
    except Exception as e:
        logger.exception(f"Reddit: {e}")
    try:
        TelegramScraper(messages_per_channel=200, lookback_hours=14).run()
    except Exception as e:
        logger.exception(f"Telegram: {e}")


def run_play_store():
    logger.info("=== JOB: PLAY STORE ===")
    try:
        PlayStoreScraper(apps_per_query=20, reviews_per_app=50).run()
    except Exception as e:
        logger.exception(f"Play Store: {e}")



def run_analyzer():
    logger.info("=== JOB: ANALYZER ===")
    try:
        NicheAnalyzer(lookback_days=30).run()
    except Exception as e:
        logger.exception(f"Analyzer: {e}")


def run_nlp():
    """Procesa reviews 1-2★ que aún no tienen pain points."""
    logger.info("=== JOB: NLP PAIN POINTS ===")
    try:
        PainExtractor().process_pending(limit=300, force=False)
    except Exception as e:
        logger.exception(f"NLP: {e}")


def run_alerts():
    logger.info("=== JOB: ALERTS ===")
    try:
        new = AlertDetector().run()
        logger.info(f"Detector: {len(new)} alertas nuevas")
        # Mandar pendientes a Telegram (alertas individuales)
        TelegramNotifier().send_pending_alerts(batch_size=10)
    except Exception as e:
        logger.exception(f"Alerts: {e}")


def run_daily_digest():
    """Resumen 1x por día como alternativa/complemento a alertas individuales."""
    logger.info("=== JOB: DAILY DIGEST ===")
    try:
        TelegramNotifier().send_daily_digest()
    except Exception as e:
        logger.exception(f"Digest: {e}")


def run_snapshot():
    """Snapshot diario para histórico real de niches."""
    logger.info("=== JOB: NICHE SNAPSHOT ===")
    try:
        n = take_niche_snapshot()
        logger.info(f"Snapshot: {n} niches guardados")
    except Exception as e:
        logger.exception(f"Snapshot: {e}")


# ============================================================
# Setup
# ============================================================

def shutdown_handler(signum, frame):
    logger.info("Shutdown signal recibido, saliendo...")
    sys.exit(0)


def main():
    init_db()
    migrate_alerts()
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    scheduler = BlockingScheduler(timezone="America/Argentina/Buenos_Aires")

    # ----- Scrapers -----
    # Suggest cada 6h (00, 06, 12, 18 hs AR)
    scheduler.add_job(run_suggest, CronTrigger(hour="0,6,12,18", minute=10),
                       id="suggest", max_instances=1, coalesce=True)

    # Social cada 12h
    scheduler.add_job(run_social, CronTrigger(hour="3,15", minute=20),
                       id="social", max_instances=1, coalesce=True)

    # Play Store 1x día
    scheduler.add_job(run_play_store, CronTrigger(hour=4, minute=0),
                       id="play_store", max_instances=1, coalesce=True)


    # ----- Procesamiento -----
    # Analyzer 4x día (después de cada batch de scrapers)
    scheduler.add_job(run_analyzer, CronTrigger(hour="1,7,13,19", minute=0),
                       id="analyzer", max_instances=1, coalesce=True)

    # NLP cada 12h
    scheduler.add_job(run_nlp, CronTrigger(hour="5,17", minute=30),
                       id="nlp", max_instances=1, coalesce=True)

    # Snapshot diario para histórico
    scheduler.add_job(run_snapshot, CronTrigger(hour=23, minute=55),
                       id="snapshot", max_instances=1, coalesce=True)

    # ----- Alertas -----
    # Detector + envío individual cada 2h
    scheduler.add_job(run_alerts, CronTrigger(minute=15, hour="*/2"),
                       id="alerts", max_instances=1, coalesce=True)

    # Digest diario a las 9 AM AR (después del primer batch)
    scheduler.add_job(run_daily_digest, CronTrigger(hour=9, minute=0),
                       id="digest", max_instances=1, coalesce=True)

    logger.info("Scheduler iniciado. Jobs registrados:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.id}")

    # Primera corrida: todos los scrapers activos + analyzer
    logger.info("\n=== Bootstrap inicial ===")
    run_suggest()
    run_play_store()
    run_social()
    run_analyzer()

    scheduler.start()


if __name__ == "__main__":
    main()
