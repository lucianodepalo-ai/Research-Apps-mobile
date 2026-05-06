"""
Trend Analysis - comparativas temporales.

Permite responder preguntas como:
- ¿Qué creció esta semana vs la anterior?
- ¿Qué categoría perdió interés en los últimos 30 días?
- ¿Cómo evolucionó este término en el tiempo?

Diseñado para alimentar las vistas del dashboard con histórico real.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from sqlalchemy import func, desc, and_, distinct

from database.models import (
    SearchSignal, Question, AppCompetitor, AppReview,
    NicheOpportunity, get_session
)


class TrendAnalyzer:

    def __init__(self):
        self.now = datetime.utcnow()

    # ==========================================================
    # Comparativas A vs B
    # ==========================================================

    def compare_periods(self,
                          period_days: int = 7,
                          dimension: str = "term",
                          top_n: int = 50,
                          category: str = None) -> Dict:
        """
        Compara últimos `period_days` vs los `period_days` previos.

        dimension: "term" | "category" | "source"

        Devuelve:
            {
                "current_period": (start, end),
                "previous_period": (start, end),
                "rising": [{name, current, previous, delta_pct}, ...],
                "falling": [...],
                "new": [...],   # solo aparecen en current
                "lost": [...],  # solo aparecen en previous
            }
        """
        cur_start = self.now - timedelta(days=period_days)
        prev_start = cur_start - timedelta(days=period_days)

        cur_data = self._aggregate(cur_start, self.now, dimension, category)
        prev_data = self._aggregate(prev_start, cur_start, dimension, category)

        all_keys = set(cur_data.keys()) | set(prev_data.keys())

        rising, falling, new_items, lost = [], [], [], []
        for key in all_keys:
            current = cur_data.get(key, 0)
            previous = prev_data.get(key, 0)
            if previous == 0 and current > 0:
                new_items.append({
                    "name": key, "current": current, "previous": 0,
                    "delta_pct": float("inf"),
                })
            elif current == 0 and previous > 0:
                lost.append({
                    "name": key, "current": 0, "previous": previous,
                    "delta_pct": -100,
                })
            else:
                delta_pct = ((current - previous) / previous) * 100 if previous else 0
                item = {
                    "name": key, "current": current, "previous": previous,
                    "delta_pct": delta_pct,
                }
                if delta_pct > 0:
                    rising.append(item)
                elif delta_pct < 0:
                    falling.append(item)

        rising.sort(key=lambda x: -x["delta_pct"])
        falling.sort(key=lambda x: x["delta_pct"])
        new_items.sort(key=lambda x: -x["current"])
        lost.sort(key=lambda x: -x["previous"])

        return {
            "current_period": (cur_start, self.now),
            "previous_period": (prev_start, cur_start),
            "rising": rising[:top_n],
            "falling": falling[:top_n],
            "new": new_items[:top_n],
            "lost": lost[:top_n],
        }

    def _aggregate(self, start: datetime, end: datetime,
                    dimension: str, category: str = None) -> Dict[str, int]:
        session = get_session()
        try:
            field_map = {
                "term": SearchSignal.term,
                "category": SearchSignal.category,
                "source": SearchSignal.source,
            }
            field = field_map.get(dimension, SearchSignal.term)

            q = (
                session.query(field, func.count(SearchSignal.id))
                .filter(SearchSignal.captured_at >= start)
                .filter(SearchSignal.captured_at < end)
                .filter(field.isnot(None))
            )
            if category and dimension != "category":
                q = q.filter(SearchSignal.category == category)
            q = q.group_by(field)

            return {row[0]: row[1] for row in q.all()}
        finally:
            session.close()

    # ==========================================================
    # Series temporales
    # ==========================================================

    def daily_series(self, days: int = 90,
                       group_by: str = "source",
                       category: str = None) -> List[Dict]:
        """
        Devuelve serie diaria de cantidad de señales.
        group_by: "source" | "category" | None
        """
        session = get_session()
        try:
            since = self.now - timedelta(days=days)
            # SQLite: usar date() para extraer día
            day_expr = func.date(SearchSignal.captured_at).label("day")

            select_fields = [day_expr, func.count(SearchSignal.id).label("count")]
            group_fields = [day_expr]

            if group_by == "source":
                select_fields.append(SearchSignal.source)
                group_fields.append(SearchSignal.source)
            elif group_by == "category":
                select_fields.append(SearchSignal.category)
                group_fields.append(SearchSignal.category)

            q = session.query(*select_fields).filter(
                SearchSignal.captured_at >= since
            )
            if category:
                q = q.filter(SearchSignal.category == category)
            q = q.group_by(*group_fields).order_by(day_expr)

            rows = q.all()
            result = []
            for row in rows:
                item = {"day": str(row[0]), "count": row[1]}
                if group_by:
                    item[group_by] = row[2] if len(row) > 2 else None
                result.append(item)
            return result
        finally:
            session.close()

    def term_history(self, term: str, days: int = 90) -> List[Dict]:
        """Histórico día a día de un término puntual."""
        session = get_session()
        try:
            since = self.now - timedelta(days=days)
            rows = (
                session.query(
                    func.date(SearchSignal.captured_at).label("day"),
                    SearchSignal.source,
                    func.count(SearchSignal.id).label("count"),
                    func.avg(SearchSignal.score).label("avg_score"),
                    func.sum(SearchSignal.volume).label("volume"),
                )
                .filter(SearchSignal.term == term)
                .filter(SearchSignal.captured_at >= since)
                .group_by(func.date(SearchSignal.captured_at), SearchSignal.source)
                .order_by("day")
                .all()
            )
            return [{
                "day": str(r.day),
                "source": r.source,
                "count": r.count,
                "avg_score": float(r.avg_score or 0),
                "volume": int(r.volume or 0),
            } for r in rows]
        finally:
            session.close()

    def category_evolution(self, days: int = 90) -> List[Dict]:
        """Evolución de cada categoría a lo largo del tiempo."""
        session = get_session()
        try:
            since = self.now - timedelta(days=days)
            rows = (
                session.query(
                    func.date(SearchSignal.captured_at).label("day"),
                    SearchSignal.category,
                    func.count(SearchSignal.id).label("signals"),
                    func.count(distinct(SearchSignal.term)).label("unique_terms"),
                )
                .filter(SearchSignal.captured_at >= since)
                .filter(SearchSignal.category.isnot(None))
                .group_by(func.date(SearchSignal.captured_at), SearchSignal.category)
                .order_by("day")
                .all()
            )
            return [{
                "day": str(r.day),
                "category": r.category,
                "signals": r.signals,
                "unique_terms": r.unique_terms,
            } for r in rows]
        finally:
            session.close()

    # ==========================================================
    # Niche opportunities en el tiempo
    # ==========================================================

    def niche_score_history(self) -> List[Dict]:
        """
        Para gráfico: cómo evolucionó cada nicho.
        Limitación: como NicheOpportunity se actualiza in-place, esto
        muestra el estado actual. Para histórico completo hay que
        agregar tabla de snapshots (siguiente paso).
        """
        session = get_session()
        try:
            rows = session.query(NicheOpportunity).all()
            return [{
                "category": r.category,
                "name": r.name,
                "opportunity_score": r.opportunity_score,
                "demand_score": r.demand_score,
                "competition_score": r.competition_score,
                "detected_at": r.detected_at,
                "last_updated_at": r.last_updated_at,
                "signals_count": r.signals_count,
            } for r in rows]
        finally:
            session.close()


# ==========================================================
# Snapshots para histórico real de niches (correr periódicamente)
# ==========================================================

def take_niche_snapshot():
    """
    Guarda snapshot del estado actual de NicheOpportunity en una
    tabla histórica. Llamar diariamente desde el scheduler para
    poder hacer comparativas temporales reales.
    """
    from sqlalchemy import Column, Integer, Float, String, DateTime
    from database.models import Base, engine

    class NicheSnapshot(Base):
        __tablename__ = "niche_snapshots"
        __table_args__ = {"extend_existing": True}
        id = Column(Integer, primary_key=True)
        snapshot_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
        niche_id = Column(Integer, index=True)
        category = Column(String(100), index=True)
        opportunity_score = Column(Float)
        demand_score = Column(Float)
        competition_score = Column(Float)
        signals_count = Column(Integer)
        competitors_count = Column(Integer)

    Base.metadata.create_all(engine, tables=[NicheSnapshot.__table__])

    session = get_session()
    try:
        niches = session.query(NicheOpportunity).all()
        now = datetime.utcnow()
        for n in niches:
            session.add(NicheSnapshot(
                snapshot_at=now,
                niche_id=n.id,
                category=n.category,
                opportunity_score=n.opportunity_score,
                demand_score=n.demand_score,
                competition_score=n.competition_score,
                signals_count=n.signals_count,
                competitors_count=n.competitors_count,
            ))
        session.commit()
        return len(niches)
    finally:
        session.close()


if __name__ == "__main__":
    a = TrendAnalyzer()
    cmp = a.compare_periods(period_days=7, dimension="term", top_n=10)
    print("\n=== Top rising terms last 7d vs prev 7d ===")
    for item in cmp["rising"][:10]:
        print(f"  {item['name']:40} {item['previous']:>4} → {item['current']:>4}  "
              f"({item['delta_pct']:+.0f}%)")
    print(f"\nNew terms: {len(cmp['new'])}")
    for item in cmp["new"][:5]:
        print(f"  {item['name']:40} (apareció con {item['current']})")
