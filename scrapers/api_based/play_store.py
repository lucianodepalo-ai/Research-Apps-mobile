"""
Play Store scraper - el más valioso para detectar nichos de apps.

Estrategia:
1. Para cada query semilla, buscamos las top 30 apps que rankean en AR
2. Para cada app, traemos metadata + reviews
3. Las reviews 1-2 estrellas = problemas reales de los usuarios
4. Apps con muchos installs + rating bajo = oportunidad clara

Usamos google-play-scraper que es la librería estándar.
No requiere API key.
"""
from typing import List, Dict
from datetime import datetime
from google_play_scraper import search, app, reviews, Sort

from scrapers.base import BaseScraper
from config.settings import (
    PLAY_STORE_LANG, PLAY_STORE_COUNTRY,
    PLAY_STORE_SEED_QUERIES,
)
from database.repository import upsert_app, save_reviews_bulk, save_signals_bulk


class PlayStoreScraper(BaseScraper):
    name = "play_store"
    tier = 2

    def __init__(self, queries: List[str] = None,
                 apps_per_query: int = 20,
                 reviews_per_app: int = 50):
        super().__init__()
        self.queries = queries or PLAY_STORE_SEED_QUERIES
        self.apps_per_query = apps_per_query
        self.reviews_per_app = reviews_per_app

    def fetch(self) -> List[Dict]:
        """
        Override: usamos lógica propia porque guardamos en tablas
        especializadas (AppCompetitor, AppReview) además de SearchSignal.
        """
        signals = []
        total_apps = 0
        total_reviews = 0

        for query in self.queries:
            self.log.info(f"=== Buscando apps para query: '{query}' ===")
            try:
                results = self.with_retries(
                    search,
                    query,
                    lang=PLAY_STORE_LANG,
                    country=PLAY_STORE_COUNTRY,
                    n_hits=self.apps_per_query,
                )
            except Exception as e:
                self.log.error(f"Error buscando '{query}': {e}")
                continue

            self.log.info(f"  → {len(results)} apps encontradas")

            for rank, app_summary in enumerate(results):
                app_id = app_summary.get("appId")
                if not app_id:
                    continue

                # Detalle completo de la app
                try:
                    details = self.with_retries(
                        app, app_id,
                        lang=PLAY_STORE_LANG,
                        country=PLAY_STORE_COUNTRY,
                    )
                except Exception as e:
                    self.log.warning(f"  No pude traer detalle de {app_id}: {e}")
                    continue

                app_data = {
                    "app_id": app_id,
                    "title": details.get("title", ""),
                    "developer": details.get("developer"),
                    "category": details.get("genre"),
                    "score": details.get("score"),
                    "ratings_count": details.get("ratings"),
                    "reviews_count": details.get("reviews"),
                    "installs": details.get("installs"),
                    "free": details.get("free", True),
                    "price": details.get("price", 0),
                    "description": details.get("description"),
                    "summary": details.get("summary"),
                    "extra": {
                        "icon": details.get("icon"),
                        "url": details.get("url"),
                        "released": details.get("released"),
                        "updated": details.get("updated"),
                        "version": details.get("version"),
                    },
                }

                saved_app = upsert_app(app_data, query=query, rank=rank)
                total_apps += 1

                # Señal: la app aparece para esta query
                signals.append({
                    "source": "play_store",
                    "source_subtype": "search_result",
                    "term": query,
                    "category": details.get("genre"),
                    "score": max(100 - rank * 5, 10),
                    "volume": app_data.get("ratings_count") or 0,
                    "url": f"https://play.google.com/store/apps/details?id={app_id}",
                    "extra": {
                        "app_id": app_id,
                        "app_title": details.get("title"),
                        "rank": rank,
                        "rating": details.get("score"),
                        "installs": details.get("installs"),
                    },
                })

                # Reviews
                reviews_saved = self._fetch_reviews(saved_app.id, app_id)
                total_reviews += reviews_saved

                self.random_delay()

        self.log.info(
            f"=== Play Store: {total_apps} apps, {total_reviews} reviews, "
            f"{len(signals)} señales ==="
        )
        return signals

    def _fetch_reviews(self, app_pk: int, app_id: str) -> int:
        """Trae las reviews más recientes y más relevantes (mix)."""
        all_reviews = []
        try:
            # Mix: las más nuevas + las más relevantes (suele agarrar quejas con likes)
            for sort_method in [Sort.NEWEST, Sort.MOST_RELEVANT]:
                result, _ = self.with_retries(
                    reviews,
                    app_id,
                    lang=PLAY_STORE_LANG,
                    country=PLAY_STORE_COUNTRY,
                    sort=sort_method,
                    count=self.reviews_per_app // 2,
                )
                for r in result:
                    all_reviews.append({
                        "review_id": r.get("reviewId"),
                        "user_name": r.get("userName"),
                        "score": r.get("score"),
                        "content": r.get("content"),
                        "thumbs_up": r.get("thumbsUpCount", 0),
                        "review_date": r.get("at"),
                    })
        except Exception as e:
            self.log.warning(f"Error reviews {app_id}: {e}")

        if all_reviews:
            saved = save_reviews_bulk(app_pk, all_reviews)
            return saved
        return 0


if __name__ == "__main__":
    # Test rápido
    s = PlayStoreScraper(
        queries=["calculadora dolar", "feriados argentina"],
        apps_per_query=5,
        reviews_per_app=20,
    )
    s.run()
