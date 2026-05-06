"""
Business Opportunity Generator.

Convierte datos crudos en hipótesis accionables de productos.
Cada oportunidad tiene:
- Tesis (qué problema resuelve)
- Evidencia (datos que la respaldan)
- Score de viabilidad (demanda/competencia/complejidad)
- Sugerencia de monetización
- Roadmap de MVP

El objetivo: que vos como builder veas en 30 segundos
"qué construir hoy" con justificación de datos.
"""
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import List, Dict
from sqlalchemy import func, desc, and_, or_

from database.models import (
    SearchSignal, Question, AppCompetitor, AppReview,
    NicheOpportunity, get_session
)


class OpportunityGenerator:
    """Genera ideas de apps/productos a partir de los datos recolectados."""

    # Templates de monetización por categoría
    MONETIZATION_BY_CATEGORY = {
        "finanzas": [
            "Suscripción mensual ($1-3 USD) por alertas/datos premium",
            "Comisión por referidos a brokers/exchanges",
            "Versión gratis con ads + Pro sin ads",
        ],
        "tramites": [
            "Freemium: trámites gratis, recordatorios y autocompletado pagos",
            "Comisión por gestión de turnos",
            "Sponsorship de servicios profesionales (gestores, abogados)",
        ],
        "trabajo": [
            "Premium para destacar perfil",
            "Comisión por matching con empresas",
            "Curso/contenido pago integrado",
        ],
        "compras": [
            "Comisión de afiliados (Amazon, ML, MercadoPago)",
            "Cashback con fee del comercio",
            "Premium sin ads + alertas anticipadas de ofertas",
        ],
        "salud": [
            "Suscripción para reservas/recordatorios premium",
            "Sponsorship de obras sociales/farmacias",
            "Marketplace de profesionales con comisión",
        ],
        "transporte": [
            "Premium con rutas personalizadas + sin ads",
            "Comisión por integraciones de pago (SUBE, Modo)",
        ],
        "general": [
            "Freemium con features avanzados pagos",
            "Ads no intrusivos",
            "Donation-ware con bonus",
        ],
    }

    # Estimación de complejidad técnica por tipo de feature
    COMPLEXITY_HINTS = {
        "calculadora": 1,        # baja
        "conversor": 1,
        "alerta": 2,
        "recordatorio": 2,
        "tracker": 3,
        "marketplace": 5,
        "social": 5,
        "chat": 4,
        "ai": 4,
    }

    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
        self.since = datetime.utcnow() - timedelta(days=lookback_days)

    # ==========================================================
    # API pública
    # ==========================================================

    def top_opportunities(self, limit: int = 20) -> List[Dict]:
        """
        Devuelve oportunidades ordenadas por score, enriquecidas con:
        - tesis, monetización, complejidad estimada, evidencia
        """
        opps = self._gather_opportunities()
        enriched = [self._enrich_opportunity(o) for o in opps]
        enriched.sort(key=lambda x: -x["final_score"])
        return enriched[:limit]

    def underserved_apps(self, min_installs: int = 50_000,
                          max_rating: float = 3.8) -> List[Dict]:
        """
        Apps con muchas instalaciones pero rating bajo.
        Significa: hay demanda, pero la oferta es mala.
        Es la oportunidad más clara para reemplazo.
        """
        session = get_session()
        try:
            rows = (
                session.query(AppCompetitor)
                .filter(AppCompetitor.installs_num >= min_installs)
                .filter(AppCompetitor.score <= max_rating)
                .filter(AppCompetitor.score.isnot(None))
                .order_by(desc(AppCompetitor.installs_num))
                .all()
            )
            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "developer": r.developer,
                    "category": r.category,
                    "rating": r.score,
                    "installs": r.installs,
                    "installs_num": r.installs_num,
                    "ratings_count": r.ratings_count,
                    "discovered_via": r.discovered_via_query,
                    "app_id": r.app_id,
                    # opportunity = installs / rating (más bajo rating, más oportunidad)
                    "replacement_score": (r.installs_num or 0) / max(r.score or 1, 0.5),
                }
                for r in rows
            ]
        finally:
            session.close()

    def trending_questions_unaddressed(self, limit: int = 30) -> List[Dict]:
        """
        Preguntas que aparecen mucho y NO tienen una app dedicada que las resuelva.
        Heurística: pregunta con alto times_seen + no encontramos app cuya
        descripción/título matchee con palabras clave de la pregunta.
        """
        session = get_session()
        try:
            top_q = (
                session.query(Question)
                .filter(Question.last_seen_at >= self.since)
                .order_by(desc(Question.times_seen))
                .limit(200)
                .all()
            )

            # Cargar todas las apps para matchear
            apps = session.query(AppCompetitor).all()
            apps_text = " ".join(
                f"{a.title or ''} {a.description or ''}".lower()
                for a in apps
            )

            unaddressed = []
            for q in top_q:
                kws = self._extract_keywords(q.question)
                if not kws:
                    continue
                # Si menos de la mitad de las keywords aparecen en alguna app -> unaddressed
                hits = sum(1 for k in kws if k in apps_text)
                coverage = hits / len(kws) if kws else 0
                if coverage < 0.5:
                    unaddressed.append({
                        "question": q.question,
                        "category": q.category,
                        "intent": q.intent,
                        "times_seen": q.times_seen,
                        "upvotes": q.upvotes,
                        "url": q.source_url,
                        "coverage": round(coverage, 2),
                        "keywords": kws,
                    })
            unaddressed.sort(key=lambda x: -x["times_seen"])
            return unaddressed[:limit]
        finally:
            session.close()

    def category_quadrants(self) -> List[Dict]:
        """
        Para cada categoría: demanda total vs competencia agregada.
        Útil para el scatter plot de oportunidad.
        """
        session = get_session()
        try:
            # Demanda
            demand_rows = (
                session.query(
                    SearchSignal.category,
                    func.count(SearchSignal.id).label("signals"),
                    func.count(func.distinct(SearchSignal.term)).label("unique_terms"),
                )
                .filter(SearchSignal.captured_at >= self.since)
                .filter(SearchSignal.category.isnot(None))
                .group_by(SearchSignal.category)
                .all()
            )
            demand_map = {
                r.category: {"signals": r.signals, "unique_terms": r.unique_terms}
                for r in demand_rows
            }

            # Competencia
            comp_rows = (
                session.query(
                    AppCompetitor.category,
                    func.count(AppCompetitor.id).label("apps"),
                    func.avg(AppCompetitor.score).label("avg_rating"),
                    func.sum(AppCompetitor.installs_num).label("total_installs"),
                )
                .filter(AppCompetitor.category.isnot(None))
                .group_by(AppCompetitor.category)
                .all()
            )
            comp_map = {
                r.category: {
                    "apps": r.apps,
                    "avg_rating": float(r.avg_rating or 0),
                    "total_installs": int(r.total_installs or 0),
                }
                for r in comp_rows
            }

            # Cruzar
            all_cats = set(demand_map.keys()) | set(comp_map.keys())
            result = []
            for cat in all_cats:
                d = demand_map.get(cat, {"signals": 0, "unique_terms": 0})
                c = comp_map.get(cat, {"apps": 0, "avg_rating": 0, "total_installs": 0})
                result.append({
                    "category": cat,
                    "demand_signals": d["signals"],
                    "demand_unique_terms": d["unique_terms"],
                    "competition_apps": c["apps"],
                    "competition_avg_rating": c["avg_rating"],
                    "competition_total_installs": c["total_installs"],
                })
            return result
        finally:
            session.close()

    def pain_points_for_category(self, category: str,
                                   limit: int = 50) -> List[Dict]:
        """
        Reviews negativas de apps en esta categoría.
        Tu hoja de ruta de producto: lo que YA molesta a los usuarios.
        """
        session = get_session()
        try:
            rows = (
                session.query(AppReview, AppCompetitor.title, AppCompetitor.app_id)
                .join(AppCompetitor, AppReview.app_id_fk == AppCompetitor.id)
                .filter(AppCompetitor.category == category)
                .filter(AppReview.score <= 2)
                .order_by(desc(AppReview.thumbs_up))
                .limit(limit)
                .all()
            )
            return [
                {
                    "app": title,
                    "app_id": app_id,
                    "score": r.score,
                    "content": r.content,
                    "thumbs_up": r.thumbs_up,
                    "review_date": r.review_date,
                }
                for r, title, app_id in rows
            ]
        finally:
            session.close()

    # ==========================================================
    # Internos
    # ==========================================================

    def _gather_opportunities(self) -> List[Dict]:
        """Carga las NicheOpportunity ya calculadas por NicheAnalyzer."""
        session = get_session()
        try:
            rows = session.query(NicheOpportunity).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "category": r.category,
                    "demand_score": r.demand_score or 0,
                    "competition_score": r.competition_score or 0,
                    "opportunity_score": r.opportunity_score or 0,
                    "signals_count": r.signals_count or 0,
                    "competitors_count": r.competitors_count or 0,
                    "avg_competitor_rating": r.avg_competitor_rating or 0,
                    "top_terms": r.top_terms or [],
                    "status": r.status,
                }
                for r in rows
            ]
        finally:
            session.close()

    def _enrich_opportunity(self, opp: Dict) -> Dict:
        """Agrega tesis, monetización, complejidad."""
        cat = opp["category"]
        terms = opp["top_terms"][:5]

        # Tesis: armada con los términos top
        if terms:
            tesis = (
                f"Los argentinos buscan activamente {', '.join(terms[:3])} "
                f"({opp['signals_count']} señales en {self.lookback_days} días)."
            )
            if opp["competitors_count"] < 5:
                tesis += f" Solo {opp['competitors_count']} apps existentes en Play Store."
            elif opp["avg_competitor_rating"] < 3.8:
                tesis += (
                    f" {opp['competitors_count']} apps existentes pero con rating "
                    f"promedio bajo ({opp['avg_competitor_rating']:.1f}/5) → "
                    "los usuarios están insatisfechos."
                )
            else:
                tesis += (
                    f" Hay {opp['competitors_count']} competidores con rating "
                    f"{opp['avg_competitor_rating']:.1f}/5 → mercado validado pero competido."
                )
        else:
            tesis = "Datos insuficientes para tesis."

        # Monetización
        monetization = self.MONETIZATION_BY_CATEGORY.get(
            cat, self.MONETIZATION_BY_CATEGORY["general"]
        )

        # Complejidad estimada (heurística simple)
        complexity = self._estimate_complexity(terms)

        # Final score: opportunity_score con ajuste por complejidad
        # Apps simples valen más para ti porque las podés sacar rápido
        final_score = opp["opportunity_score"] - (complexity - 1) * 5

        return {
            **opp,
            "tesis": tesis,
            "monetization": monetization,
            "complexity": complexity,
            "complexity_label": ["", "Muy simple", "Simple", "Media",
                                  "Compleja", "Muy compleja"][complexity],
            "final_score": round(final_score, 2),
            "mvp_features": self._suggest_mvp_features(cat, terms),
        }

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """Extrae palabras significativas (>3 letras) ignorando stopwords."""
        from unidecode import unidecode
        stopwords = {
            "que", "como", "para", "por", "con", "una", "uno", "del", "los",
            "las", "esto", "esta", "este", "pero", "donde", "cuando",
            "alguien", "sabe", "puedo", "hago", "tengo", "quiero",
            "the", "and", "for"
        }
        text = unidecode(text.lower())
        words = [w for w in text.split() if len(w) > 3 and w.isalpha()
                 and w not in stopwords]
        return words

    def _estimate_complexity(self, terms: List[str]) -> int:
        """1=muy simple, 5=muy compleja."""
        max_c = 1
        joined = " ".join(terms).lower()
        for keyword, c in self.COMPLEXITY_HINTS.items():
            if keyword in joined:
                max_c = max(max_c, c)
        return max_c

    def _suggest_mvp_features(self, category: str,
                                terms: List[str]) -> List[str]:
        """Features sugeridos según categoría."""
        base = {
            "finanzas": [
                "Cotización en tiempo real con caché",
                "Alertas push por umbrales (ej: dólar > X)",
                "Calculadora de conversión rápida",
                "Histórico con gráfico simple",
                "Widget de Android",
            ],
            "tramites": [
                "Catálogo de trámites con guías paso a paso",
                "Recordatorios de vencimientos",
                "Lista de documentos requeridos",
                "Links directos a sitios oficiales",
                "Modo offline para guías",
            ],
            "trabajo": [
                "Listado de oportunidades con filtros AR",
                "Notificaciones de nuevos posts",
                "Generador de CV simple",
                "Calculadora de sueldo neto / freelance",
                "Comparador de monedas para freelance",
            ],
            "compras": [
                "Comparador de precios en supermercados/ML",
                "Alertas de baja de precio",
                "Lista de compras compartida",
                "Calculadora de cuotas con interés real",
                "Historial de precios para detectar 'descuentos truchos'",
            ],
            "salud": [
                "Buscador de turnos por especialidad",
                "Recordatorios de medicación",
                "Vademécum de remedios con precios",
                "Cuadro de vacunas por edad",
            ],
            "transporte": [
                "Saldo SUBE en tiempo real",
                "Cómo llegar simplificado (sin ads)",
                "Recordatorio de vencimientos VTV/patente",
                "Alertas de paros/cortes",
            ],
        }
        return base.get(category, [
            "Funcionalidad core simple",
            "Notificaciones útiles",
            "Modo offline básico",
            "Onboarding de 3 pasos",
        ])
