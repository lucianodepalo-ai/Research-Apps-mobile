"""
Niche Analyzer.

Cruza señales de búsqueda (demanda) con apps competidoras (oferta)
para detectar nichos desatendidos.

Heurística simple v1:
    opportunity_score = demand_score - competition_score

Donde:
- demand_score: cuántas señales tiene el término / categoría, en cuántas fuentes
- competition_score: cuántas apps existen en Play Store para esa categoría,
  ponderado por su rating promedio (más rating = competencia más fuerte)

Un nicho ideal: alta demanda, pocas apps o apps con rating bajo.
"""
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from sqlalchemy import func, desc

from database.models import (
    SearchSignal, AppCompetitor, AppReview, Question,
    NicheOpportunity, get_session
)
from loguru import logger


class NicheAnalyzer:

    def __init__(self, lookback_days: int = 14):
        self.lookback_days = lookback_days
        self.since = datetime.utcnow() - timedelta(days=lookback_days)

    def run(self):
        logger.info("=== Niche Analyzer ===")
        # 1. Detectar términos con muchas señales
        hot_terms = self._hot_terms()
        # 2. Calcular competencia por categoría
        competition = self._competition_by_category()
        # 3. Generar oportunidades
        opportunities = self._build_opportunities(hot_terms, competition)
        # 4. Persistir
        self._persist(opportunities)

    def _hot_terms(self):
        """Términos con más señales únicas en el lookback period."""
        session = get_session()
        try:
            rows = (
                session.query(
                    SearchSignal.term,
                    SearchSignal.category,
                    func.count(SearchSignal.id).label("signals"),
                    func.count(func.distinct(SearchSignal.source)).label("sources"),
                    func.avg(SearchSignal.score).label("avg_score"),
                    func.sum(SearchSignal.volume).label("total_volume"),
                )
                .filter(SearchSignal.captured_at >= self.since)
                .group_by(SearchSignal.term, SearchSignal.category)
                .having(func.count(SearchSignal.id) >= 2)  # mínimo 2 observaciones
                .order_by(desc("signals"))
                .limit(500)
                .all()
            )
            return [
                {
                    "term": r.term,
                    "category": r.category or "general",
                    "signals": r.signals,
                    "sources": r.sources,
                    "avg_score": float(r.avg_score or 0),
                    "total_volume": int(r.total_volume or 0),
                }
                for r in rows
            ]
        finally:
            session.close()

    def _competition_by_category(self):
        """
        Para cada categoría calculamos:
        - cantidad de apps
        - rating promedio
        - installs totales
        - apps con rating < 4 (oportunidad: usuarios insatisfechos)
        """
        session = get_session()
        try:
            rows = (
                session.query(
                    AppCompetitor.category,
                    func.count(AppCompetitor.id).label("apps"),
                    func.avg(AppCompetitor.score).label("avg_rating"),
                    func.sum(AppCompetitor.installs_num).label("total_installs"),
                )
                .group_by(AppCompetitor.category)
                .all()
            )

            # Apps "débiles" = rating < 4 con installs significativos
            weak_apps = (
                session.query(
                    AppCompetitor.category,
                    func.count(AppCompetitor.id).label("weak_count"),
                )
                .filter(AppCompetitor.score < 4.0)
                .filter(AppCompetitor.installs_num > 10000)
                .group_by(AppCompetitor.category)
                .all()
            )
            weak_map = {r.category: r.weak_count for r in weak_apps}

            return {
                r.category: {
                    "apps": r.apps,
                    "avg_rating": float(r.avg_rating or 0),
                    "total_installs": int(r.total_installs or 0),
                    "weak_apps": weak_map.get(r.category, 0),
                }
                for r in rows if r.category
            }
        finally:
            session.close()

    def _build_opportunities(self, hot_terms, competition):
        """
        Construye oportunidades por categoría.
        Una oportunidad agrupa términos relacionados.
        """
        by_cat = defaultdict(lambda: {
            "terms": [],
            "total_signals": 0,
            "total_volume": 0,
        })

        for ht in hot_terms:
            cat = ht["category"]
            by_cat[cat]["terms"].append(ht)
            by_cat[cat]["total_signals"] += ht["signals"]
            by_cat[cat]["total_volume"] += ht["total_volume"]

        opportunities = []
        for cat, data in by_cat.items():
            if not data["terms"]:
                continue

            # Demand score: log-scale del total de señales (0-100)
            import math
            demand = min(math.log10(max(data["total_signals"], 1)) * 25, 100)

            # Competition score
            comp_data = competition.get(cat, {
                "apps": 0, "avg_rating": 0, "weak_apps": 0
            })
            apps_count = comp_data["apps"]
            avg_rating = comp_data["avg_rating"]
            weak_apps = comp_data["weak_apps"]

            # Penalizamos pocas apps (= mercado validado pero abierto)
            # Penalizamos apps con buen rating (= competencia fuerte)
            # Premiamos apps débiles (= usuarios insatisfechos)
            competition_score = min(apps_count * 3, 100)
            if avg_rating > 0:
                competition_score *= (avg_rating / 5)
            competition_score -= weak_apps * 5
            competition_score = max(min(competition_score, 100), 0)

            opportunity = demand - competition_score

            top_terms = sorted(data["terms"], key=lambda x: -x["signals"])[:10]

            opportunities.append({
                "name": f"Nicho: {cat}",
                "category": cat,
                "demand_score": round(demand, 2),
                "competition_score": round(competition_score, 2),
                "opportunity_score": round(opportunity, 2),
                "signals_count": data["total_signals"],
                "competitors_count": apps_count,
                "avg_competitor_rating": round(avg_rating, 2),
                "weak_apps_count": weak_apps,
                "top_terms": [t["term"] for t in top_terms],
            })

        opportunities.sort(key=lambda x: -x["opportunity_score"])
        return opportunities

    def _persist(self, opportunities):
        session = get_session()
        try:
            for opp in opportunities:
                existing = session.query(NicheOpportunity).filter_by(
                    name=opp["name"]
                ).first()
                if existing:
                    existing.last_updated_at = datetime.utcnow()
                    existing.demand_score = opp["demand_score"]
                    existing.competition_score = opp["competition_score"]
                    existing.opportunity_score = opp["opportunity_score"]
                    existing.signals_count = opp["signals_count"]
                    existing.competitors_count = opp["competitors_count"]
                    existing.avg_competitor_rating = opp["avg_competitor_rating"]
                    existing.top_terms = opp["top_terms"]
                else:
                    session.add(NicheOpportunity(
                        name=opp["name"],
                        category=opp["category"],
                        demand_score=opp["demand_score"],
                        competition_score=opp["competition_score"],
                        opportunity_score=opp["opportunity_score"],
                        signals_count=opp["signals_count"],
                        competitors_count=opp["competitors_count"],
                        avg_competitor_rating=opp["avg_competitor_rating"],
                        top_terms=opp["top_terms"],
                        status="detected",
                    ))
            session.commit()
            logger.info(f"✅ {len(opportunities)} oportunidades guardadas")
        finally:
            session.close()


if __name__ == "__main__":
    NicheAnalyzer().run()
