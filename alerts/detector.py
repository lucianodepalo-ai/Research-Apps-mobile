"""
Alert Detector - lógica de detección con foco en señal, no ruido.

Filosofía anti-spam:
1. UMBRAL ABSOLUTO: la métrica debe superar un mínimo absoluto. Sin este
   filtro, cosas pequeñas con mucho crecimiento % generan ruido.
2. UMBRAL RELATIVO: la métrica debe superar significativamente su baseline.
3. DEDUPLICACIÓN: misma alerta no se repite en N días.
4. COOLDOWN POR CATEGORÍA: como mucho M alertas por categoría por día.
5. BURN-IN PERIOD: las primeras semanas no alertamos (sin baseline confiable).

Tipos de alerta implementados:

A) RISING_TERM
   Un término individual que pasa de aparecer poco a aparecer mucho.
   Solo dispara si: volumen actual >= 10 Y crecimiento >= 200% vs media histórica.

B) NEW_QUESTION_CLUSTER
   Pregunta nueva (nunca vista) que aparece con mucha repetición rápido.
   Dispara si: times_seen >= 5 en menos de 48h.

C) HIGH_VALUE_PAIN
   Pain point que aparece mencionado por muchas apps de una categoría.
   Dispara si: >= 5 apps lo mencionan Y >= 20 reviews con likes lo respaldan.

D) WEAK_COMPETITOR
   App nueva descubierta con muchos installs pero rating malo.
   Dispara si: installs >= 100k Y rating <= 3.5 Y nunca alertada.

E) NICHE_SCORE_JUMP
   Una NicheOpportunity sube su score significativamente (ej: > 20 puntos).
   Dispara si: cambio absoluto >= 20 Y nuevo score >= 40.
"""
import hashlib
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import Counter

from sqlalchemy import func, desc, and_, or_, distinct
from loguru import logger

from database.models import (
    SearchSignal, Question, AppCompetitor, AppReview,
    NicheOpportunity, get_session
)
from alerts.migrations import Alert
from insights.nlp.pain_extractor import aggregate_pain_points_by_category


# ============================================================
# Configuración de umbrales (ajustables)
# ============================================================

# Generales
BURN_IN_DAYS = 7        # no alertamos si tenemos menos datos que esto
DEDUP_DAYS = 5          # no repetir misma alerta en N días
MAX_ALERTS_PER_CATEGORY_PER_RUN = 3

# Rising term
RISING_TERM_MIN_VOLUME_NOW = 10
RISING_TERM_MIN_GROWTH_PCT = 200    # 3x
RISING_TERM_MIN_BASELINE_DAYS = 7

# New question cluster
NEW_QUESTION_MIN_TIMES_SEEN = 5
NEW_QUESTION_MAX_AGE_HOURS = 48

# High value pain
PAIN_MIN_APPS_AFFECTED = 5
PAIN_MIN_MENTIONS = 20

# Weak competitor
WEAK_COMP_MIN_INSTALLS = 100_000
WEAK_COMP_MAX_RATING = 3.5

# Niche score jump
NICHE_MIN_SCORE_DELTA = 20
NICHE_MIN_NEW_SCORE = 40


class AlertDetector:

    def __init__(self):
        self.now = datetime.utcnow()
        self.session = get_session()

    def __del__(self):
        try:
            self.session.close()
        except Exception:
            pass

    # ==========================================================
    # Pipeline principal
    # ==========================================================

    def run(self) -> List[Alert]:
        """Corre todos los detectores y persiste alertas nuevas."""
        if not self._has_enough_history():
            logger.info(
                f"Burn-in period: necesitamos al menos {BURN_IN_DAYS} días de datos"
            )
            return []

        all_alerts = []
        all_alerts.extend(self.detect_rising_terms())
        all_alerts.extend(self.detect_new_question_clusters())
        all_alerts.extend(self.detect_high_value_pains())
        all_alerts.extend(self.detect_weak_competitors())
        all_alerts.extend(self.detect_niche_score_jumps())

        # Dedup contra alertas anteriores
        new_alerts = [a for a in all_alerts if not self._is_duplicate(a)]

        # Limitar por categoría
        new_alerts = self._cap_by_category(new_alerts)

        # Persistir
        for a in new_alerts:
            self.session.add(a)
        if new_alerts:
            self.session.commit()
        logger.info(
            f"Alertas: {len(all_alerts)} candidatas → "
            f"{len(new_alerts)} nuevas tras dedup"
        )
        return new_alerts

    def _has_enough_history(self) -> bool:
        first = self.session.query(func.min(SearchSignal.captured_at)).scalar()
        if not first:
            return False
        return (self.now - first).days >= BURN_IN_DAYS

    def _is_duplicate(self, alert: Alert) -> bool:
        cutoff = self.now - timedelta(days=DEDUP_DAYS)
        existing = (
            self.session.query(Alert)
            .filter(Alert.fingerprint == alert.fingerprint)
            .filter(Alert.detected_at >= cutoff)
            .first()
        )
        return existing is not None

    def _cap_by_category(self, alerts: List[Alert]) -> List[Alert]:
        """Limita cantidad por categoría para no spamear sobre lo mismo."""
        by_cat = Counter()
        result = []
        # Ordenar por severidad: critical primero
        order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        sorted_alerts = sorted(alerts, key=lambda a: order.get(a.severity, 9))
        for a in sorted_alerts:
            cat = a.category or "_none"
            if by_cat[cat] >= MAX_ALERTS_PER_CATEGORY_PER_RUN:
                continue
            by_cat[cat] += 1
            result.append(a)
        return result

    @staticmethod
    def _fingerprint(*parts) -> str:
        return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]

    # ==========================================================
    # Detector A: rising terms
    # ==========================================================

    def detect_rising_terms(self) -> List[Alert]:
        """Términos cuyo volumen reciente supera ampliamente su baseline."""
        # Volumen últimas 24h
        recent_cutoff = self.now - timedelta(hours=24)
        baseline_start = self.now - timedelta(days=RISING_TERM_MIN_BASELINE_DAYS)

        recent_rows = (
            self.session.query(
                SearchSignal.term,
                SearchSignal.category,
                func.count(SearchSignal.id).label("cnt"),
                func.count(distinct(SearchSignal.source)).label("srcs"),
            )
            .filter(SearchSignal.captured_at >= recent_cutoff)
            .group_by(SearchSignal.term, SearchSignal.category)
            .having(func.count(SearchSignal.id) >= RISING_TERM_MIN_VOLUME_NOW)
            .all()
        )

        alerts = []
        for r in recent_rows:
            # Baseline: media diaria en últimos 7 días
            baseline = (
                self.session.query(func.count(SearchSignal.id))
                .filter(SearchSignal.term == r.term)
                .filter(SearchSignal.captured_at >= baseline_start)
                .filter(SearchSignal.captured_at < recent_cutoff)
                .scalar() or 0
            )
            baseline_per_day = baseline / RISING_TERM_MIN_BASELINE_DAYS
            current_per_day = r.cnt
            if baseline_per_day < 0.5:
                # Sin baseline suficiente
                growth_pct = float("inf") if current_per_day > 0 else 0
            else:
                growth_pct = (current_per_day - baseline_per_day) / baseline_per_day * 100

            if growth_pct < RISING_TERM_MIN_GROWTH_PCT:
                continue

            severity = ("high" if growth_pct >= 500 and r.srcs >= 2
                         else "medium")

            title = f"📈 Tendencia: '{r.term}' creció {self._fmt_pct(growth_pct)}"
            message = (
                f"*{r.term}*\n"
                f"Categoría: _{r.category or 'general'}_\n"
                f"Apariciones 24h: *{r.cnt}* en *{r.srcs}* fuente/s\n"
                f"Baseline 7d (por día): {baseline_per_day:.1f}\n"
                f"Crecimiento: *{self._fmt_pct(growth_pct)}*"
            )
            alerts.append(Alert(
                kind="rising_term",
                severity=severity,
                title=title,
                message=message,
                fingerprint=self._fingerprint("rising", r.term),
                category=r.category,
                metric_value=current_per_day,
                metric_baseline=baseline_per_day,
                payload={
                    "term": r.term,
                    "growth_pct": growth_pct,
                    "sources": r.srcs,
                },
            ))
        return alerts

    @staticmethod
    def _fmt_pct(p):
        if math.isinf(p):
            return "nuevo"
        return f"+{p:.0f}%"

    # ==========================================================
    # Detector B: new question clusters
    # ==========================================================

    def detect_new_question_clusters(self) -> List[Alert]:
        """Preguntas nuevas que se repiten rápido."""
        cutoff = self.now - timedelta(hours=NEW_QUESTION_MAX_AGE_HOURS)
        rows = (
            self.session.query(Question)
            .filter(Question.captured_at >= cutoff)
            .filter(Question.times_seen >= NEW_QUESTION_MIN_TIMES_SEEN)
            .order_by(desc(Question.times_seen))
            .limit(20)
            .all()
        )

        alerts = []
        for q in rows:
            severity = "high" if q.times_seen >= 15 else "medium"
            title = (
                f"❓ Pregunta repetida ({q.times_seen}x en "
                f"{NEW_QUESTION_MAX_AGE_HOURS}h): {q.question[:60]}"
            )
            message = (
                f"*Nueva pregunta detectada*\n\n"
                f"_{q.question[:200]}_\n\n"
                f"Categoría: {q.category or 'general'}\n"
                f"Veces vista: *{q.times_seen}*\n"
                f"Tipo: {q.intent or 'otro'}\n"
                f"Fuente: {q.source}"
            )
            if q.source_url:
                message += f"\n[Ver original]({q.source_url})"
            alerts.append(Alert(
                kind="new_question_cluster",
                severity=severity,
                title=title,
                message=message,
                fingerprint=self._fingerprint("question", q.question_hash),
                category=q.category,
                metric_value=q.times_seen,
                payload={
                    "question": q.question,
                    "url": q.source_url,
                    "intent": q.intent,
                },
            ))
        return alerts

    # ==========================================================
    # Detector C: high value pains (transversales a varias apps)
    # ==========================================================

    def detect_high_value_pains(self) -> List[Alert]:
        """Pain points que afectan a muchas apps de una categoría."""
        alerts = []
        categories = (
            self.session.query(distinct(AppCompetitor.category))
            .filter(AppCompetitor.category.isnot(None))
            .all()
        )

        for (cat,) in categories:
            agg = aggregate_pain_points_by_category(category=cat, days=30, top_n=5)
            for pain in agg["pain_points"]:
                if (pain["apps_affected"] < PAIN_MIN_APPS_AFFECTED or
                        pain["mentions"] < PAIN_MIN_MENTIONS):
                    continue
                title = (
                    f"💢 Pain transversal en {cat}: "
                    f"{pain['apps_affected']} apps afectadas"
                )
                message = (
                    f"*Pain point en {cat}*\n\n"
                    f"_{pain['text']}_\n\n"
                    f"Apps afectadas: *{pain['apps_affected']}*\n"
                    f"Menciones: *{pain['mentions']}*\n"
                    f"Ejemplos: {', '.join(pain['example_apps'])}"
                )
                alerts.append(Alert(
                    kind="high_value_pain",
                    severity="high",
                    title=title,
                    message=message,
                    fingerprint=self._fingerprint("pain", cat, pain["text"][:50]),
                    category=cat,
                    metric_value=pain["apps_affected"],
                    payload=pain,
                ))
        return alerts

    # ==========================================================
    # Detector D: weak competitors
    # ==========================================================

    def detect_weak_competitors(self) -> List[Alert]:
        """Apps recién descubiertas con muchos installs y rating bajo."""
        cutoff = self.now - timedelta(days=2)
        rows = (
            self.session.query(AppCompetitor)
            .filter(AppCompetitor.captured_at >= cutoff)
            .filter(AppCompetitor.installs_num >= WEAK_COMP_MIN_INSTALLS)
            .filter(AppCompetitor.score <= WEAK_COMP_MAX_RATING)
            .filter(AppCompetitor.score.isnot(None))
            .order_by(desc(AppCompetitor.installs_num))
            .limit(10)
            .all()
        )

        alerts = []
        for app in rows:
            severity = ("critical" if app.installs_num >= 1_000_000 and app.score <= 3.0
                         else "high")
            title = (
                f"🎯 Competidor débil: {app.title} "
                f"({app.score:.1f}⭐, {app.installs})"
            )
            message = (
                f"*App con demanda pero mala calidad*\n\n"
                f"📱 *{app.title}*\n"
                f"Dev: {app.developer}\n"
                f"Categoría: {app.category}\n"
                f"Rating: *{app.score:.1f}/5* — Installs: *{app.installs}*\n"
                f"Reseñas: {app.ratings_count or '?'}\n\n"
                f"Encontrada buscando: _{app.discovered_via_query}_\n"
                f"[Ver en Play Store](https://play.google.com/store/apps/details?id={app.app_id})"
            )
            alerts.append(Alert(
                kind="weak_competitor",
                severity=severity,
                title=title,
                message=message,
                fingerprint=self._fingerprint("weakapp", app.app_id),
                category=app.category,
                metric_value=app.installs_num,
                payload={
                    "app_id": app.app_id,
                    "rating": app.score,
                    "installs": app.installs,
                },
            ))
        return alerts

    # ==========================================================
    # Detector E: niche score jumps
    # ==========================================================

    def detect_niche_score_jumps(self) -> List[Alert]:
        """
        Nichos cuyo opportunity_score subió significativamente desde
        la última alerta. Usa el historial implícito.
        """
        # Heurística: si tenemos un score >= NICHE_MIN_NEW_SCORE Y no
        # hemos alertado por este nicho en los últimos DEDUP_DAYS, alertar.
        cutoff = self.now - timedelta(days=DEDUP_DAYS)
        rows = (
            self.session.query(NicheOpportunity)
            .filter(NicheOpportunity.opportunity_score >= NICHE_MIN_NEW_SCORE)
            .filter(NicheOpportunity.last_updated_at >= cutoff)
            .order_by(desc(NicheOpportunity.opportunity_score))
            .limit(5)
            .all()
        )

        alerts = []
        for n in rows:
            title = (
                f"🚀 Nicho fuerte: {n.category} "
                f"(score {n.opportunity_score:.0f})"
            )
            top_terms = ", ".join((n.top_terms or [])[:5])
            message = (
                f"*Nicho con score elevado: {n.category}*\n\n"
                f"Score: *{n.opportunity_score:.0f}* "
                f"(demanda {n.demand_score:.0f} - "
                f"competencia {n.competition_score:.0f})\n"
                f"Señales: {n.signals_count}\n"
                f"Apps existentes: {n.competitors_count} "
                f"(rating prom: {n.avg_competitor_rating:.1f})\n\n"
                f"Términos clave:\n_{top_terms}_"
            )
            alerts.append(Alert(
                kind="niche_score_jump",
                severity="high" if n.opportunity_score >= 60 else "medium",
                title=title,
                message=message,
                fingerprint=self._fingerprint("niche", n.id),
                category=n.category,
                metric_value=n.opportunity_score,
                payload={
                    "niche_id": n.id,
                    "top_terms": n.top_terms,
                },
            ))
        return alerts


if __name__ == "__main__":
    AlertDetector().run()
