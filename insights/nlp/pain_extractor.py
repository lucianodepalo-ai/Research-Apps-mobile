"""
Pain Point Extractor.

Para cada review 1-2 estrellas:
1. Si Ollama está corriendo: extrae pain_points y feature_requests estructurados
2. Si no: heurística por keywords (más limitado pero funciona)

Resultado: tabla AppReview se enriquece con pain_points (JSON) y feature_requests.
Estos pain points alimentan el dashboard de "qué mejorar para diferenciarse".

Ejecutar:
    python -m insights.nlp.pain_extractor
    python -m insights.nlp.pain_extractor --limit 100 --force
"""
import json
import re
import argparse
from datetime import datetime, timedelta
from collections import Counter
from typing import List, Dict, Optional

from sqlalchemy import desc, and_, or_
from loguru import logger

from database.models import AppReview, AppCompetitor, get_session
from insights.nlp.ollama_client import get_client


# Heurística de fallback: keywords con categorías
PAIN_PATTERNS = {
    "performance": [
        "lento", "lentísim", "tarda", "se cuelga", "se traba", "se cierra",
        "se congela", "demora", "se queda colgad",
    ],
    "bugs": [
        "no funciona", "no anda", "no me deja", "no carga", "no abre",
        "error", "bug", "crash", "se rompe", "falla", "fallo",
    ],
    "publicidad": [
        "publicidad", "ads", "anuncio", "demasiad", "intrusiv",
        "banner",
    ],
    "ux": [
        "complicad", "confus", "no se entiende", "no es intuitiv",
        "feo", "diseño",
    ],
    "registro_login": [
        "no me deja entrar", "no puedo iniciar", "login no", "registro no",
        "olvidé contraseña", "verificación",
    ],
    "monetizacion": [
        "cobran", "carísim", "estafa", "engaño", "premium", "pago",
        "te cobran",
    ],
    "datos_desactualizados": [
        "desactualiz", "viejo", "no actualiza", "obsolet",
    ],
    "permisos_privacidad": [
        "permisos", "privacidad", "datos personal", "spy",
    ],
    "feature_request": [
        "deberían", "deberia", "estaría bueno", "agreguen", "agregar",
        "falta", "faltan", "necesita", "ojalá",
    ],
}


PROMPT_TEMPLATE = """Sos un analista de reviews de apps argentinas. Extraé información estructurada.

Review (rating {rating}/5):
"{content}"

Devolvé SOLO JSON válido con esta estructura exacta:
{{
  "pain_points": ["lista corta de problemas concretos, máximo 3"],
  "feature_requests": ["lista de features que pide explícitamente, máximo 3"],
  "category": "una de: performance, bugs, publicidad, ux, registro_login, monetizacion, datos_desactualizados, otro",
  "severity": "alta, media o baja",
  "is_actionable": true o false
}}

Reglas:
- pain_points y feature_requests deben ser frases cortas en español, máximo 8 palabras cada una
- Si la review es solo "no me gusta" sin detalle: pain_points=[], is_actionable=false
- Sé específico: NO uses "la app no funciona", SI usá "no carga el saldo SUBE"
- Si menciona algo arreglable: is_actionable=true"""


class PainExtractor:

    def __init__(self):
        self.client = get_client()
        self.using_llm = self.client.health_check()
        if self.using_llm:
            logger.info(f"✅ Ollama disponible ({self.client.model}) - usando LLM")
        else:
            logger.warning("⚠️ Ollama no disponible - fallback a heurísticas")

    def process_pending(self, limit: int = 500, force: bool = False) -> int:
        """
        Procesa reviews que aún no tienen pain_points extraídos.
        force=True reprocesa todas.
        """
        session = get_session()
        try:
            q = session.query(AppReview).filter(AppReview.score <= 2)
            if not force:
                q = q.filter(or_(
                    AppReview.pain_points.is_(None),
                    AppReview.pain_points == [],
                ))
            # Priorizar las más útiles: con likes y contenido sustancial
            q = q.order_by(desc(AppReview.thumbs_up)).limit(limit)
            reviews = q.all()

            if not reviews:
                logger.info("No hay reviews pendientes")
                return 0

            logger.info(f"Procesando {len(reviews)} reviews...")
            processed = 0
            for r in reviews:
                if not r.content or len(r.content) < 15:
                    continue
                try:
                    result = self.extract(r.content, r.score or 1)
                    r.pain_points = result.get("pain_points") or []
                    r.feature_requests = result.get("feature_requests") or []
                    r.sentiment = self._derive_sentiment(r.score)
                    processed += 1
                    if processed % 25 == 0:
                        session.commit()
                        logger.info(f"  Avance: {processed}/{len(reviews)}")
                except Exception as e:
                    logger.warning(f"Review {r.id}: {e}")
            session.commit()
            logger.info(f"✅ {processed} reviews procesadas")
            return processed
        finally:
            session.close()

    def extract(self, content: str, rating: int) -> Dict:
        """Extrae pain points: prueba LLM primero, fallback heurístico."""
        if self.using_llm:
            result = self._extract_with_llm(content, rating)
            if result:
                return result
            # Si Ollama falla en este request específico, fallback
            self.using_llm = self.client.health_check(force=True)

        return self._extract_with_heuristics(content)

    def _extract_with_llm(self, content: str, rating: int) -> Optional[Dict]:
        # Truncamos para no usar mucho contexto
        content_clean = content[:600].replace("\n", " ").replace('"', "'")
        prompt = PROMPT_TEMPLATE.format(content=content_clean, rating=rating)
        result = self.client.generate_json(prompt)
        if not result:
            return None
        # Validar campos esperados
        return {
            "pain_points": result.get("pain_points") or [],
            "feature_requests": result.get("feature_requests") or [],
            "category": result.get("category", "otro"),
            "severity": result.get("severity", "media"),
            "is_actionable": result.get("is_actionable", False),
        }

    def _extract_with_heuristics(self, content: str) -> Dict:
        """Fallback simple por matching de patrones."""
        content_lower = content.lower()
        pain_points = []
        feature_requests = []

        for cat, keywords in PAIN_PATTERNS.items():
            for kw in keywords:
                if kw in content_lower:
                    # Extraer la oración que contiene el keyword
                    sentence = self._extract_sentence(content, kw)
                    if not sentence:
                        continue
                    if cat == "feature_request":
                        feature_requests.append(sentence[:80])
                    else:
                        pain_points.append(sentence[:80])
                    break  # un keyword por categoría

        return {
            "pain_points": pain_points[:3],
            "feature_requests": feature_requests[:3],
            "category": "otro",
            "severity": "media",
            "is_actionable": bool(pain_points or feature_requests),
        }

    @staticmethod
    def _extract_sentence(text: str, keyword: str) -> str:
        """Extrae la oración del texto que contiene el keyword."""
        sentences = re.split(r"[.!?\n]", text)
        for s in sentences:
            if keyword in s.lower():
                return s.strip()
        return ""

    @staticmethod
    def _derive_sentiment(score: int) -> str:
        if not score:
            return "neutral"
        if score <= 2:
            return "negative"
        if score == 3:
            return "neutral"
        return "positive"


def aggregate_pain_points_by_category(category: str = None,
                                        days: int = 30,
                                        top_n: int = 20) -> List[Dict]:
    """
    Agrega pain_points y feature_requests a nivel categoría.
    Para el dashboard: 'qué le falta a las apps de finanzas'.
    """
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        q = (
            session.query(AppReview, AppCompetitor.category, AppCompetitor.title)
            .join(AppCompetitor, AppReview.app_id_fk == AppCompetitor.id)
            .filter(AppReview.captured_at >= since)
            .filter(AppReview.score <= 2)
            .filter(AppReview.pain_points.isnot(None))
        )
        if category:
            q = q.filter(AppCompetitor.category == category)

        rows = q.all()
        pain_counter = Counter()
        feature_counter = Counter()
        pain_apps = {}    # pain -> set de apps que lo mencionan
        feature_apps = {}

        for review, cat, app_title in rows:
            for p in (review.pain_points or []):
                if not p or len(p) < 5:
                    continue
                key = p.lower().strip()
                pain_counter[key] += 1
                pain_apps.setdefault(key, set()).add(app_title)
            for f in (review.feature_requests or []):
                if not f or len(f) < 5:
                    continue
                key = f.lower().strip()
                feature_counter[key] += 1
                feature_apps.setdefault(key, set()).add(app_title)

        return {
            "pain_points": [
                {
                    "text": p,
                    "mentions": count,
                    "apps_affected": len(pain_apps.get(p, set())),
                    "example_apps": list(pain_apps.get(p, set()))[:3],
                }
                for p, count in pain_counter.most_common(top_n)
            ],
            "feature_requests": [
                {
                    "text": f,
                    "mentions": count,
                    "apps_affected": len(feature_apps.get(f, set())),
                    "example_apps": list(feature_apps.get(f, set()))[:3],
                }
                for f, count in feature_counter.most_common(top_n)
            ],
        }
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    PainExtractor().process_pending(limit=args.limit, force=args.force)
