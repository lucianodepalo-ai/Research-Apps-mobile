"""
X (Twitter) scraper - búsquedas trending AR (Tier 4 - RIESGO ALTO).

⚠️ ADVERTENCIA:
- Scraping de X viola TOS desde 2023
- Las cuentas no verificadas se banean rápido por uso intensivo
- X bloquea búsqueda sin login desde 2023

Estrategia:
- Login con cuenta dedicada
- Visitar trending topics de Argentina
- Buscar queries específicas

Por defecto deshabilitado.
"""
import time
from typing import List, Dict
from urllib.parse import quote
from scrapers.base import BaseScraper
from scrapers.playwright_based.browser_manager import BrowserManager
from config.settings import (
    ENABLE_TWITTER, TWITTER_USERNAME, TWITTER_PASSWORD, DATA_DIR
)


class TwitterScraper(BaseScraper):
    name = "twitter"
    tier = 4

    SESSION_FILE = DATA_DIR / "x_session.json"

    SEARCH_QUERIES_AR = [
        "alguien sabe argentina",
        "como hago para argentina",
        "no entiendo como",
        "ayuda con tramite",
    ]

    def __init__(self, search_queries: List[str] = None):
        super().__init__()
        self.queries = search_queries or self.SEARCH_QUERIES_AR

    def fetch(self) -> List[Dict]:
        if not ENABLE_TWITTER:
            self.log.info("Twitter deshabilitado en .env")
            return []
        if not (TWITTER_USERNAME and TWITTER_PASSWORD):
            self.log.error("Faltan credenciales Twitter")
            return []

        signals = []
        with BrowserManager() as bm:
            self._ensure_session(bm)

            with bm.new_page(storage_state=str(self.SESSION_FILE)) as page:
                # Trending Argentina
                signals.extend(self._scrape_trending_ar(page))

                for q in self.queries:
                    self.log.info(f"X search: {q}")
                    try:
                        signals.extend(self._scrape_search(page, q))
                    except Exception as e:
                        self.log.error(f"Error '{q}': {e}")
                    self.random_delay()

        self.log.info(f"Total X: {len(signals)}")
        return signals

    def _ensure_session(self, bm: BrowserManager):
        if self.SESSION_FILE.exists():
            return
        self.log.info("Login X")
        with bm.new_context() as ctx:
            page = ctx.new_page()
            page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
            time.sleep(4)
            try:
                page.fill("input[autocomplete='username']", TWITTER_USERNAME)
                page.click("button:has-text('Siguiente'), button:has-text('Next')")
                time.sleep(3)
                page.fill("input[type='password']", TWITTER_PASSWORD)
                page.click("button:has-text('Iniciar'), button:has-text('Log in')")
                time.sleep(8)
                ctx.storage_state(path=str(self.SESSION_FILE))
                self.log.info("Sesión X guardada")
            except Exception as e:
                self.log.error(f"Login X falló: {e}")

    def _scrape_trending_ar(self, page) -> List[Dict]:
        """Trending topics de AR."""
        page.goto("https://x.com/explore/tabs/trending",
                  wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        items = page.query_selector_all('[data-testid="trend"]')[:30]
        signals = []
        for rank, it in enumerate(items):
            try:
                text = it.inner_text().split("\n")
                term = text[1] if len(text) > 1 else text[0]
                signals.append({
                    "source": "twitter",
                    "source_subtype": "trending_ar",
                    "term": term,
                    "category": "social_media",
                    "score": max(100 - rank * 3, 10),
                    "extra": {"rank": rank, "raw": text},
                })
            except Exception:
                pass
        return signals

    def _scrape_search(self, page, query: str) -> List[Dict]:
        url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=top"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        for _ in range(2):
            page.mouse.wheel(0, 2000)
            time.sleep(2)

        tweets = page.query_selector_all('article[data-testid="tweet"]')[:20]
        signals = []
        for rank, t in enumerate(tweets):
            try:
                text_el = t.query_selector('[data-testid="tweetText"]')
                text = text_el.inner_text() if text_el else ""
                if not text:
                    continue
                signals.append({
                    "source": "twitter",
                    "source_subtype": "search_tweet",
                    "term": text[:280],
                    "category": "social_media",
                    "score": max(100 - rank * 3, 10),
                    "extra": {"search_query": query, "rank": rank},
                })
            except Exception:
                pass
        return signals


if __name__ == "__main__":
    TwitterScraper().run()
