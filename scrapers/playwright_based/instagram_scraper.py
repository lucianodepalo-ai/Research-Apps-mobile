"""
Instagram scraper - HASHTAGS AR (Tier 4 - RIESGO ALTO).

⚠️ ADVERTENCIA LEGAL:
- Scraping de Instagram viola los TOS de Meta
- Meta ha demandado scrapers (Bright Data, Octopus Data)
- Las cuentas usadas se banean en días/semanas
- Necesitás cuenta DEDICADA + proxy residencial

Por defecto está deshabilitado en .env. Activar consciente del riesgo.

Estrategia con login (la única que funciona estable):
- Login una vez, guardar storage_state.json
- Reutilizar storage para sesiones siguientes
- Visitar /explore/tags/<tag>/ y leer top posts
"""
import time
import json
from pathlib import Path
from typing import List, Dict
from scrapers.base import BaseScraper
from scrapers.playwright_based.browser_manager import BrowserManager
from config.settings import (
    SOCIAL_HASHTAGS_AR, ENABLE_INSTAGRAM,
    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, DATA_DIR,
)


class InstagramScraper(BaseScraper):
    name = "instagram"
    tier = 4

    SESSION_FILE = DATA_DIR / "ig_session.json"

    def __init__(self, hashtags: List[str] = None, posts_per_tag: int = 30):
        super().__init__()
        self.hashtags = hashtags or SOCIAL_HASHTAGS_AR
        self.posts_per_tag = posts_per_tag

    def fetch(self) -> List[Dict]:
        if not ENABLE_INSTAGRAM:
            self.log.info(
                "Instagram deshabilitado en .env. "
                "Activar con ENABLE_INSTAGRAM_SCRAPING=true (riesgo alto)"
            )
            return []

        if not (INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD):
            self.log.error("Faltan INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD")
            return []

        signals = []
        with BrowserManager() as bm:
            # Asegurar sesión
            self._ensure_session(bm)

            with bm.new_page(storage_state=str(self.SESSION_FILE)) as page:
                for tag in self.hashtags:
                    self.log.info(f"IG #{tag}")
                    try:
                        sigs = self._scrape_hashtag(page, tag)
                        signals.extend(sigs)
                    except Exception as e:
                        self.log.error(f"Error #{tag}: {e}")
                    self.random_delay()
        self.log.info(f"Total IG: {len(signals)}")
        return signals

    def _ensure_session(self, bm: BrowserManager):
        """Si no hay sesión guardada o expiró, hacer login."""
        if self.SESSION_FILE.exists():
            self.log.info("Sesión IG existente encontrada, intentando reutilizar")
            return

        self.log.info("Login IG (sesión nueva)")
        with bm.new_context() as ctx:
            page = ctx.new_page()
            page.goto("https://www.instagram.com/accounts/login/",
                      wait_until="domcontentloaded")
            time.sleep(3)
            try:
                # Aceptar cookies si aparece
                cookie_btn = page.query_selector("button:has-text('Permitir todas')")
                if cookie_btn:
                    cookie_btn.click()
                    time.sleep(1)
            except Exception:
                pass

            page.fill("input[name='username']", INSTAGRAM_USERNAME)
            page.fill("input[name='password']", INSTAGRAM_PASSWORD)
            page.click("button[type='submit']")
            time.sleep(8)  # esperar redirect / 2FA

            # Guardar storage
            ctx.storage_state(path=str(self.SESSION_FILE))
            self.log.info(f"Sesión guardada en {self.SESSION_FILE}")

    def _scrape_hashtag(self, page, hashtag: str) -> List[Dict]:
        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        # Scroll
        for _ in range(3):
            page.mouse.wheel(0, 2000)
            time.sleep(2)

        # IG cambia el DOM seguido. Estos selectores son del 2024-2025;
        # si rompen, abrir devtools y ajustar.
        articles = page.query_selector_all("article a[href*='/p/']")[:self.posts_per_tag]

        signals = []
        for rank, art in enumerate(articles):
            try:
                href = art.get_attribute("href")
                img = art.query_selector("img")
                alt = img.get_attribute("alt") if img else ""

                signals.append({
                    "source": "instagram",
                    "source_subtype": "hashtag_post",
                    "term": (alt or f"#{hashtag}")[:200],
                    "category": "social_media",
                    "score": max(100 - rank * 3, 10),
                    "url": f"https://www.instagram.com{href}" if href else None,
                    "extra": {
                        "hashtag": hashtag,
                        "rank": rank,
                        "alt_text": alt,
                    },
                })
            except Exception as e:
                self.log.debug(f"IG parse error: {e}")
        return signals


if __name__ == "__main__":
    InstagramScraper(posts_per_tag=10).run()
