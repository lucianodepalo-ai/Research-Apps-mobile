"""
YouTube Suggest scraper.

Cuando la gente no entiende algo, busca tutorial en YouTube.
Los autocompletes de YouTube AR son oro para detectar intención
de aprender / resolver problemas concretos.

Endpoint: clientes6 (público, mismo formato que Google).
"""
from typing import List, Dict
import httpx
from scrapers.base import BaseScraper
from config.settings import YOUTUBE_SUGGEST_URL, COUNTRY_CODE


class YouTubeSuggestScraper(BaseScraper):
    name = "youtube_suggest"
    tier = 2

    SEED_PREFIXES = [
        # Tutorial intent — lo que busca gente que quiere aprender
        "como hacer", "como usar", "tutorial", "paso a paso",
        "como configurar", "como instalar", "como solucionar",
        "guia para", "aprende a",

        # Reviews y comparativas — para decidir qué app/servicio usar
        "review", "que es mejor", "comparacion", "vale la pena",
        "diferencia entre", "cual es mejor app",

        # Finanzas AR — alto volumen de búsqueda tutorial
        "como invertir en argentina", "como comprar dolar",
        "como cobrar dolares siendo freelance",
        "como funciona mercadopago", "como hacer plazo fijo",
        "como declarar impuestos argentina",

        # Trámites AR — gente que necesita que alguien le explique
        "como tramitar dni argentina", "como sacar cuit",
        "como usar mi argentina", "como cobrar anses",
        "como pagar afip online",

        # Apps móviles AR — intención directa
        "app para ganar dinero argentina", "mejor app de finanzas argentina",
        "app para aprender ingles gratis", "app para hacer factura",
        "como usar billetera virtual",

        # Trabajo y emprendimiento
        "como emprender en argentina", "como trabajar desde casa",
        "como conseguir clientes freelance",
    ]

    def _query(self, term: str) -> List[str]:
        params = {
            "client": "youtube",
            "ds": "yt",
            "q": term,
            "hl": "es",
            "gl": COUNTRY_CODE.lower(),
        }
        try:
            r = httpx.get(YOUTUBE_SUGGEST_URL, params=params, timeout=15)
            r.raise_for_status()
            # YouTube devuelve JSONP-like; limpiamos prefijo
            text = r.text
            if text.startswith("window.google.ac.h("):
                text = text[len("window.google.ac.h("):-1]
            elif text.startswith(")]}'"):
                text = text[4:]
            import json
            data = json.loads(text)
            # data[1] es la lista; cada item es [text, ...]
            return [item[0] for item in data[1] if isinstance(item, list)]
        except Exception as e:
            self.log.warning(f"Error YT suggest '{term}': {e}")
            return []

    def fetch(self) -> List[Dict]:
        signals = []
        for prefix in self.SEED_PREFIXES:
            self.log.info(f"YT Suggest: '{prefix}'")
            suggestions = self.with_retries(self._query, prefix)
            for rank, sug in enumerate(suggestions):
                signals.append({
                    "source": "youtube_suggest",
                    "source_subtype": "autocomplete",
                    "term": sug,
                    "score": max(100 - rank * 10, 10),
                    "extra": {"seed_prefix": prefix, "rank": rank},
                })
            self.random_delay()
        self.log.info(f"Total: {len(signals)} suggests")
        return signals


if __name__ == "__main__":
    YouTubeSuggestScraper().run()
