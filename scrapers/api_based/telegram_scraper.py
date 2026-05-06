"""
Telegram scraper - canales públicos argentinos.

Por qué Telegram es la fuente más subestimada:
- API oficial gratuita y permisiva (Telethon)
- Canales argentinos masivos (cientos de miles de subs)
- Conversaciones reales sin algoritmo
- Mensajes cortos = intención clara
- En grupos públicos: gente preguntando lo que no entiende

Setup:
1. https://my.telegram.org -> Login con tu número
2. API development tools -> crear app
3. Copiar api_id y api_hash al .env
4. Primera corrida: pide código SMS (one-time, después usa session file)

Uso async con Telethon (es la lib estándar y más estable).
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import Channel, MessageEntityHashtag

from scrapers.base import BaseScraper
from config.settings import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    TELEGRAM_CHANNELS_AR, DATA_DIR,
)
from database.repository import save_question


class TelegramScraper(BaseScraper):
    """
    Scraper de canales públicos argentinos.

    Recolecta:
    - Mensajes recientes con texto + métricas (vistas, forwards, reactions)
    - Preguntas detectadas (van también a tabla Question)
    - Hashtags trending por canal
    """
    name = "telegram"
    tier = 1   # API oficial = riesgo bajo

    SESSION_FILE = DATA_DIR / "telegram_session"

    def __init__(self,
                 channels: List[str] = None,
                 messages_per_channel: int = 200,
                 lookback_hours: int = 48):
        super().__init__()
        self.channels = channels or TELEGRAM_CHANNELS_AR
        self.messages_per_channel = messages_per_channel
        self.since = datetime.utcnow() - timedelta(hours=lookback_hours)

        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            self.log.warning(
                "Faltan TELEGRAM_API_ID / TELEGRAM_API_HASH. "
                "Obtenelos en https://my.telegram.org"
            )
            self.client = None
        else:
            self.client = TelegramClient(
                str(self.SESSION_FILE),
                int(TELEGRAM_API_ID),
                TELEGRAM_API_HASH,
            )

    def fetch(self) -> List[Dict]:
        """Wrap async en sync para que encaje con BaseScraper."""
        if not self.client:
            return []
        return asyncio.run(self._fetch_async())

    async def _fetch_async(self) -> List[Dict]:
        signals = []
        await self.client.start(phone=TELEGRAM_PHONE or None)
        self.log.info("Cliente Telegram conectado")

        for channel_username in self.channels:
            self.log.info(f"=== {channel_username} ===")
            try:
                signals.extend(await self._scrape_channel(channel_username))
            except Exception as e:
                self.log.error(f"Error {channel_username}: {e}")

        await self.client.disconnect()
        self.log.info(f"Total Telegram: {len(signals)}")
        return signals

    async def _scrape_channel(self, username: str) -> List[Dict]:
        """Scrapea un canal: mensajes + estadísticas."""
        try:
            entity = await self.client.get_entity(username)
        except Exception as e:
            self.log.warning(f"No se pudo resolver {username}: {e}")
            return []

        if not isinstance(entity, Channel):
            self.log.warning(f"{username} no es un canal")
            return []

        signals = []
        category = self._infer_channel_category(username)
        hashtag_counter = {}

        async for msg in self.client.iter_messages(
            entity, limit=self.messages_per_channel
        ):
            if not msg.message:
                continue
            if msg.date.replace(tzinfo=None) < self.since:
                break

            text = msg.message.strip()
            if len(text) < 10:
                continue

            views = msg.views or 0
            forwards = msg.forwards or 0

            # Reactions (suma total)
            reactions_count = 0
            if msg.reactions and msg.reactions.results:
                reactions_count = sum(r.count for r in msg.reactions.results)

            # Score: combina vistas + engagement
            engagement = forwards * 5 + reactions_count * 2
            views_score = min(views / 1000, 50) if views else 0
            score = min(views_score + engagement / 10, 100)

            # URL del mensaje
            msg_url = f"https://t.me/{username}/{msg.id}"

            # Hashtags
            hashtags = re.findall(r"#(\w+)", text)
            for h in hashtags:
                hashtag_counter[h.lower()] = hashtag_counter.get(h.lower(), 0) + 1

            # Detectar preguntas y guardar en tabla Question
            questions_in_msg = self._extract_questions(text)
            for q_text in questions_in_msg:
                save_question(
                    question=q_text,
                    source="telegram",
                    source_url=msg_url,
                    category=category,
                    upvotes=reactions_count,
                    answers_count=forwards,
                    intent=self._classify_intent(q_text),
                    extra={
                        "channel": username,
                        "views": views,
                    },
                )

            # Señal del mensaje completo
            signals.append({
                "source": "telegram",
                "source_subtype": "channel_message",
                "term": text[:300],
                "category": category,
                "score": score,
                "volume": views,
                "url": msg_url,
                "extra": {
                    "channel": username,
                    "msg_id": msg.id,
                    "forwards": forwards,
                    "reactions": reactions_count,
                    "hashtags": hashtags,
                    "is_question": bool(questions_in_msg),
                    "date": msg.date.isoformat(),
                },
            })

        # Señal agregada por hashtag (top 10 del canal en este período)
        for h, count in sorted(hashtag_counter.items(),
                               key=lambda x: -x[1])[:10]:
            signals.append({
                "source": "telegram",
                "source_subtype": "hashtag",
                "term": f"#{h}",
                "category": category,
                "score": min(count * 5, 100),
                "volume": count,
                "extra": {"channel": username, "occurrences": count},
            })

        self.log.info(f"  {username}: {len(signals)} señales")
        return signals

    @staticmethod
    def _extract_questions(text: str) -> List[str]:
        """
        Extrae preguntas de un texto.
        Detecta tanto '?' explícitos como frases tipo
        'alguien sabe', 'cómo hago', etc.
        """
        questions = []

        # Por signos de pregunta - corta en oraciones
        # Reconoce ¿...? y ...?
        pattern = re.compile(r"(¿[^?]+\?|[A-ZÁÉÍÓÚÑ][^.!?\n]{10,200}\?)")
        for m in pattern.findall(text):
            q = m.strip()
            if 15 <= len(q) <= 300:
                questions.append(q)

        # Por palabras gatillo
        triggers = [
            r"alguien sabe[^.\n]+",
            r"alguno sabe[^.\n]+",
            r"como (?:hago|puedo|cobro|pago|hacer)[^.\n]+",
            r"(?:me )?conviene[^.\n]+",
            r"vale la pena[^.\n]+",
        ]
        for trig in triggers:
            for m in re.findall(trig, text, re.IGNORECASE):
                q = m.strip()
                if 15 <= len(q) <= 300 and q not in questions:
                    questions.append(q)

        return questions[:5]

    @staticmethod
    def _classify_intent(text: str) -> str:
        t = text.lower()
        if "como" in t or "cómo" in t:
            return "how_to"
        if "que es" in t or "qué es" in t:
            return "what_is"
        if "cuanto" in t or "cuánto" in t or "precio" in t:
            return "price"
        if "donde" in t or "dónde" in t:
            return "where"
        if "conviene" in t or "vale la pena" in t or "mejor" in t:
            return "comparison"
        if "no funciona" in t or "no anda" in t or "error" in t:
            return "problem"
        return "other"

    @staticmethod
    def _infer_channel_category(username: str) -> str:
        u = username.lower().replace("@", "")
        if any(k in u for k in ("dolar", "cripto", "plazofijo", "merval",
                                 "finanzas", "inversion", "ahorro")):
            return "finanzas"
        if any(k in u for k in ("trabajo", "empleo", "remote", "freelance",
                                 "developer", "it_arg")):
            return "trabajo"
        if any(k in u for k in ("oferta", "descuento", "supermercado",
                                 "promo", "cupon")):
            return "compras"
        if any(k in u for k in ("anses", "afip", "tramite", "gobierno",
                                 "argentina_oficial")):
            return "tramites"
        if any(k in u for k in ("salud", "medic", "obrasocial", "pami")):
            return "salud"
        if any(k in u for k in ("noticia", "news", "diario", "info")):
            return "noticias"
        return "general"


if __name__ == "__main__":
    TelegramScraper(messages_per_channel=50).run()
