"""
TikTok scraper - hashtags argentinos.

TikTok permite ver contenido de hashtags públicos sin login.
Esto es lo más seguro de los scrapers Tier 4.

Estrategia:
- Para cada hashtag AR, abrimos /tag/<hashtag>
- Capturamos los videos top con sus métricas
- Los videos virales en AR muestran qué consume la audiencia

Limitación: TikTok cambia el DOM seguido. Si rompe, ajustar selectores.
"""
import time
from typing import List, Dict
from urllib.parse import quote
from scrapers.base import BaseScraper
from scrapers.playwright_based.browser_manager import BrowserManager
from config.settings import SOCIAL_HASHTAGS_AR, ENABLE_TIKTOK


class TikTokScraper(BaseScraper):
    name = "tiktok"
    tier = 4

    def __init__(self, hashtags: List[str] = None, videos_per_tag: int = 20):
        super().__init__()
        self.hashtags = hashtags or SOCIAL_HASHTAGS_AR
        self.videos_per_tag = videos_per_tag

    def fetch(self) -> List[Dict]:
        if not ENABLE_TIKTOK:
            self.log.info("TikTok deshabilitado en .env (ENABLE_TIKTOK_SCRAPING=false)")
            return []

        signals = []
        with BrowserManager() as bm:
            with bm.new_page() as page:
                for tag in self.hashtags:
                    self.log.info(f"#{tag}")
                    try:
                        videos = self._scrape_hashtag(page, tag)
                        signals.extend(videos)
                    except Exception as e:
                        self.log.error(f"Error #{tag}: {e}")
                    self.random_delay()
        self.log.info(f"Total TikTok: {len(signals)}")
        return signals

    def _scrape_hashtag(self, page, hashtag: str) -> List[Dict]:
        url = f"https://www.tiktok.com/tag/{quote(hashtag)}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Scroll para cargar videos
        for _ in range(3):
            page.mouse.wheel(0, 1500)
            time.sleep(2)

        # Selectores - válidos al momento de escribir, pueden cambiar
        items = page.query_selector_all('[data-e2e="challenge-item"]')[:self.videos_per_tag]

        signals = []
        for rank, item in enumerate(items):
            try:
                desc_el = item.query_selector('[data-e2e="challenge-item-desc"]')
                desc = desc_el.inner_text() if desc_el else ""

                views_el = item.query_selector('[data-e2e="challenge-item-views"]')
                views_text = views_el.inner_text() if views_el else "0"
                views = self._parse_count(views_text)

                link_el = item.query_selector("a")
                href = link_el.get_attribute("href") if link_el else None

                signals.append({
                    "source": "tiktok",
                    "source_subtype": "hashtag_video",
                    "term": desc[:200] or f"#{hashtag}",
                    "category": "social_media",
                    "score": min(100 - rank * 5, 100),
                    "volume": views,
                    "url": href,
                    "extra": {
                        "hashtag": hashtag,
                        "rank": rank,
                        "views_raw": views_text,
                    },
                })
            except Exception as e:
                self.log.debug(f"Item parse error: {e}")
        return signals

    @staticmethod
    def _parse_count(s: str) -> int:
        """'1.2M' -> 1200000, '500K' -> 500000"""
        if not s:
            return 0
        s = s.strip().upper().replace(",", "")
        try:
            if s.endswith("K"):
                return int(float(s[:-1]) * 1000)
            if s.endswith("M"):
                return int(float(s[:-1]) * 1_000_000)
            if s.endswith("B"):
                return int(float(s[:-1]) * 1_000_000_000)
            return int(float(s))
        except ValueError:
            return 0


if __name__ == "__main__":
    TikTokScraper(videos_per_tag=10).run()
