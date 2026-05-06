"""
Google Suggest scraper.

Endpoint público de autocompletado de Google.
Te devuelve las búsquedas más populares que empiezan con un texto,
segmentadas por país e idioma.

Esta es la mejor fuente de "qué pregunta la gente" porque:
- Los suggests salen de queries reales (no es algoritmo)
- Está segmentado por país (gl=ar)
- Es público, sin auth, sin TOS especial
- Tiene rate limit muy permisivo

Cómo lo usamos:
- Tomamos cada SEED_PREFIX de config (ej "como hago")
- Lo enviamos al endpoint y leemos los autocompletes
- Cada autocomplete es una "señal" de búsqueda real
- Iteramos también con prefijos + cada letra (a, b, c...) para ampliar
"""
import string
from typing import List, Dict
import httpx
from scrapers.base import BaseScraper
from config.settings import (
    GOOGLE_SUGGEST_URL, SEED_PREFIXES, COUNTRY_CODE, LANGUAGE
)


class GoogleSuggestScraper(BaseScraper):
    name = "google_suggest"
    tier = 2

    def __init__(self, deep_expand: bool = False):
        """
        deep_expand=True: para cada prefijo, expande con cada letra.
        Desactivado por defecto — en español k/j/x/w/z casi no tienen resultados útiles
        y multiplica el tiempo x27 innecesariamente.
        """
        super().__init__()
        self.deep_expand = deep_expand

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/130.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/",
    }

    def _query(self, term: str) -> List[str]:
        """Una llamada al endpoint de suggest."""
        params = {
            "client": "firefox",   # devuelve JSON limpio
            "q": term,
            "hl": "es",
            "gl": COUNTRY_CODE.lower(),
        }
        try:
            r = httpx.get(GOOGLE_SUGGEST_URL, params=params,
                          headers=self.HEADERS, timeout=15)
            if r.status_code != 200:
                self.log.warning(f"Suggest '{term}': HTTP {r.status_code}")
                return []
            data = r.json()
            return data[1] if len(data) > 1 else []
        except Exception as e:
            self.log.warning(f"Error suggest '{term}': {e}")
            return []

    def fetch(self) -> List[Dict]:
        signals: List[Dict] = []
        seen_terms = set()
        prefixes = list(SEED_PREFIXES)

        # Expandir cada prefijo con letras: "como" -> "como a", "como b", ...
        if self.deep_expand:
            expanded = []
            for p in prefixes:
                expanded.append(p)
                for letter in string.ascii_lowercase:
                    expanded.append(f"{p} {letter}")
            prefixes = expanded
            self.log.info(f"Expandido a {len(prefixes)} prefijos para query")

        for i, prefix in enumerate(prefixes):
            self.log.info(f"[{i+1}/{len(prefixes)}] Suggest '{prefix}'")
            suggestions = self.with_retries(self._query, prefix)

            for rank, sug in enumerate(suggestions):
                if sug in seen_terms:
                    continue
                seen_terms.add(sug)

                # Score basado en posición: posición 1 = score 100, posición 10 = score 10
                score = max(100 - (rank * 10), 10)
                category = self._infer_category(sug)

                signals.append({
                    "source": "google_suggest",
                    "source_subtype": "autocomplete",
                    "term": sug,
                    "category": category,
                    "score": score,
                    "extra": {
                        "seed_prefix": prefix,
                        "rank": rank,
                    },
                })

            self.random_delay()

        self.log.info(f"Total únicos capturados: {len(signals)}")
        return signals

    @staticmethod
    def _infer_category(term: str) -> str:
        """Infiere categoría por palabras clave en el término."""
        t = term.lower()
        rules = [
            (("dolar", "blue", "mep", "ccl", "plazo fijo", "ahorro", "inversion",
              "merval", "cripto", "bitcoin", "tasa", "inflacion"), "finanzas"),
            (("anses", "afip", "monotributo", "tramite", "renaper", "dni",
              "pasaporte", "cuit", "cuil", "turno", "mi argentina"), "tramites"),
            (("turno medico", "obra social", "pami", "vacuna", "remedio",
              "sintoma", "doctor", "clinica", "hospital"), "salud"),
            (("sueldo", "trabajo", "empleo", "freelance", "curriculum",
              "cv", "linkedin", "ganar dinero"), "trabajo"),
            (("nafta", "combustible", "ypf", "shell", "gas", "luz", "edesur",
              "edenor", "agua", "internet", "telefono"), "servicios"),
            (("colectivo", "subte", "tren", "sube", "cargar sube", "auto",
              "vtv", "patente", "licencia"), "transporte"),
            (("mercadolibre", "mercadopago", "comprar", "precio", "oferta",
              "descuento", "supermercado"), "compras"),
            (("receta", "comida", "milanesa", "asado", "empanada"), "comida"),
            (("netflix", "spotify", "futbol", "river", "boca",
              "telegram", "whatsapp"), "ocio"),
        ]
        for keywords, cat in rules:
            if any(k in t for k in keywords):
                return cat
        return "general"


if __name__ == "__main__":
    # Para correr suelto: python -m scrapers.suggest_based.google_suggest
    s = GoogleSuggestScraper(deep_expand=False)  # rápido para probar
    s.run()
