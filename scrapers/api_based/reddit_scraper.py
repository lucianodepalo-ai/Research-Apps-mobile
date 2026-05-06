"""
Reddit scraper para subreddits argentinos.

Por qué Reddit:
- API oficial gratis y permisiva
- r/argentina, r/AskArgentina y otros tienen miles de preguntas reales
- Los upvotes son señal directa de relevancia
- Los comments suelen tener problemas concretos sin filtro
"""
from typing import List, Dict
from datetime import datetime
import praw

from scrapers.base import BaseScraper
from config.settings import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT,
    SUBREDDITS_AR,
)
from database.repository import save_question


class RedditScraper(BaseScraper):
    name = "reddit"
    tier = 1

    def __init__(self, posts_per_sub: int = 100, fetch_top_comments: bool = True):
        super().__init__()
        self.posts_per_sub = posts_per_sub
        self.fetch_top_comments = fetch_top_comments
        if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
            self.log.warning("Reddit sin credenciales. Agregalas al .env")
            self.client = None
        else:
            self.client = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                user_agent=REDDIT_USER_AGENT,
            )
            self.client.read_only = True

    def fetch(self) -> List[Dict]:
        if not self.client:
            return []

        signals = []
        for sub_name in SUBREDDITS_AR:
            self.log.info(f"=== r/{sub_name} ===")
            try:
                sub = self.client.subreddit(sub_name)
                # Top de la semana captura lo relevante
                posts = list(sub.top(time_filter="week", limit=self.posts_per_sub))
            except Exception as e:
                self.log.error(f"Error r/{sub_name}: {e}")
                continue

            for post in posts:
                title = post.title
                is_question = self._looks_like_question(title)
                category = self._infer_category(title)

                signals.append({
                    "source": "reddit",
                    "source_subtype": "post",
                    "term": title,
                    "category": category,
                    "score": min(post.score, 1000) / 10,  # 0-100
                    "volume": post.num_comments,
                    "url": f"https://reddit.com{post.permalink}",
                    "extra": {
                        "subreddit": sub_name,
                        "post_id": post.id,
                        "upvote_ratio": post.upvote_ratio,
                        "is_self": post.is_self,
                        "selftext_preview": (post.selftext or "")[:500],
                    },
                })

                if is_question:
                    save_question(
                        question=title,
                        source="reddit",
                        source_url=f"https://reddit.com{post.permalink}",
                        category=category,
                        upvotes=post.score,
                        answers_count=post.num_comments,
                        intent=self._classify_intent(title),
                        extra={"subreddit": sub_name},
                    )

            self.random_delay()

        self.log.info(f"Total Reddit: {len(signals)}")
        return signals

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        t = text.lower()
        question_words = (
            "?", "¿", "como ", "cómo ", "que ", "qué ", "cuando", "cuándo",
            "donde", "dónde", "alguien sabe", "alguno sabe", "me conviene",
            "vale la pena", "recomienda", "ayuda", "duda",
        )
        return any(w in t for w in question_words)

    @staticmethod
    def _classify_intent(text: str) -> str:
        t = text.lower()
        if "como" in t or "cómo" in t:
            return "how_to"
        if "que es" in t or "qué es" in t:
            return "what_is"
        if "cuando" in t or "cuándo" in t:
            return "when"
        if "donde" in t or "dónde" in t:
            return "where"
        if " vs " in t or "diferencia" in t or "mejor" in t:
            return "comparison"
        if "precio" in t or "cuanto cuesta" in t or "cuánto" in t:
            return "price"
        if "no me anda" in t or "no funciona" in t or "error" in t:
            return "problem"
        return "other"

    @staticmethod
    def _infer_category(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("dolar", "blue", "ahorro", "plazo fijo", "merval")):
            return "finanzas"
        if any(k in t for k in ("anses", "afip", "monotributo", "tramite")):
            return "tramites"
        if any(k in t for k in ("trabajo", "sueldo", "empleo", "freelance")):
            return "trabajo"
        if any(k in t for k in ("salud", "medico", "obra social", "pami")):
            return "salud"
        return "general"


if __name__ == "__main__":
    RedditScraper(posts_per_sub=20).run()
