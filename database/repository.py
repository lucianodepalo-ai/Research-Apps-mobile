"""
Repositorio: capa de acceso a la DB.
Encapsula lógica de upsert, deduplicación y queries comunes.
"""
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from unidecode import unidecode

from sqlalchemy import func, desc, and_
from database.models import (
    SearchSignal, Question, AppCompetitor, AppReview,
    NicheOpportunity, ScrapeRun, get_session
)


def normalize_term(text: str) -> str:
    """Normaliza un término: lowercase, sin acentos, sin espacios extras."""
    if not text:
        return ""
    return unidecode(text.strip().lower())


def hash_question(text: str) -> str:
    """Hash determinístico para deduplicar preguntas."""
    norm = normalize_term(text)
    # quitar signos para que "como tramitar dni" == "como tramitar dni?"
    norm = "".join(c for c in norm if c.isalnum() or c.isspace())
    norm = " ".join(norm.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


# =========================================================
# SearchSignal
# =========================================================

def save_signal(
    source: str,
    term: str,
    *,
    source_subtype: str = None,
    category: str = None,
    score: float = 0,
    volume: int = 0,
    growth_pct: float = None,
    is_rising: bool = False,
    url: str = None,
    extra: dict = None,
    region: str = "AR",
) -> SearchSignal:
    """Guarda una señal nueva."""
    session = get_session()
    try:
        sig = SearchSignal(
            source=source,
            source_subtype=source_subtype,
            term=normalize_term(term),
            raw_term=term,
            category=category,
            region=region,
            score=score,
            volume=volume,
            growth_pct=growth_pct,
            is_rising=is_rising,
            url=url,
            extra=extra or {},
        )
        session.add(sig)
        session.commit()
        session.refresh(sig)
        return sig
    finally:
        session.close()


def save_signals_bulk(signals: List[Dict]) -> int:
    """Inserta múltiples señales. Cada dict debe tener al menos source y term."""
    session = get_session()
    try:
        objs = []
        for s in signals:
            objs.append(SearchSignal(
                source=s["source"],
                source_subtype=s.get("source_subtype"),
                term=normalize_term(s["term"]),
                raw_term=s["term"],
                category=s.get("category"),
                region=s.get("region", "AR"),
                score=s.get("score", 0),
                volume=s.get("volume", 0),
                growth_pct=s.get("growth_pct"),
                is_rising=s.get("is_rising", False),
                url=s.get("url"),
                extra=s.get("extra", {}),
            ))
        session.bulk_save_objects(objs)
        session.commit()
        return len(objs)
    finally:
        session.close()


# =========================================================
# Question
# =========================================================

def save_question(
    question: str,
    source: str,
    *,
    source_url: str = None,
    category: str = None,
    upvotes: int = 0,
    answers_count: int = 0,
    intent: str = None,
    extra: dict = None,
) -> Question:
    """
    Upsert de pregunta: si ya existe (por hash), incrementa times_seen
    y actualiza last_seen_at. Si no, la crea.
    """
    session = get_session()
    try:
        h = hash_question(question)
        existing = session.query(Question).filter_by(question_hash=h).first()
        if existing:
            existing.times_seen += 1
            existing.last_seen_at = datetime.utcnow()
            existing.upvotes = max(existing.upvotes or 0, upvotes)
            existing.answers_count = max(existing.answers_count or 0, answers_count)
            session.commit()
            return existing
        q = Question(
            question=question,
            question_hash=h,
            source=source,
            source_url=source_url,
            category=category,
            upvotes=upvotes,
            answers_count=answers_count,
            intent=intent,
            extra=extra or {},
        )
        session.add(q)
        session.commit()
        session.refresh(q)
        return q
    finally:
        session.close()


# =========================================================
# AppCompetitor + Reviews
# =========================================================

def upsert_app(app_data: dict, query: str = None, rank: int = None) -> AppCompetitor:
    """Crea o actualiza una app del Play Store."""
    session = get_session()
    try:
        existing = session.query(AppCompetitor).filter_by(
            app_id=app_data["app_id"]
        ).first()

        installs_num = _parse_installs(app_data.get("installs", ""))

        if existing:
            existing.title = app_data.get("title", existing.title)
            existing.score = app_data.get("score", existing.score)
            existing.ratings_count = app_data.get("ratings_count", existing.ratings_count)
            existing.reviews_count = app_data.get("reviews_count", existing.reviews_count)
            existing.installs = app_data.get("installs", existing.installs)
            existing.installs_num = installs_num or existing.installs_num
            existing.captured_at = datetime.utcnow()
            session.commit()
            return existing

        app = AppCompetitor(
            app_id=app_data["app_id"],
            title=app_data.get("title", ""),
            developer=app_data.get("developer"),
            category=app_data.get("category"),
            score=app_data.get("score"),
            ratings_count=app_data.get("ratings_count"),
            reviews_count=app_data.get("reviews_count"),
            installs=app_data.get("installs"),
            installs_num=installs_num,
            free=app_data.get("free", True),
            price=app_data.get("price", 0),
            description=app_data.get("description"),
            summary=app_data.get("summary"),
            discovered_via_query=query,
            rank_in_query=rank,
            extra=app_data.get("extra", {}),
        )
        session.add(app)
        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def save_reviews_bulk(app_pk: int, reviews: List[Dict]) -> int:
    """Guarda reviews de una app, evitando duplicados por review_id."""
    session = get_session()
    try:
        existing_ids = {
            r[0] for r in session.query(AppReview.review_id)
            .filter(AppReview.app_id_fk == app_pk).all()
        }
        new_reviews = [r for r in reviews if r.get("review_id") not in existing_ids]
        objs = []
        for r in new_reviews:
            objs.append(AppReview(
                app_id_fk=app_pk,
                review_id=r["review_id"],
                user_name=r.get("user_name"),
                score=r.get("score"),
                content=r.get("content"),
                thumbs_up=r.get("thumbs_up", 0),
                review_date=r.get("review_date"),
            ))
        if objs:
            session.bulk_save_objects(objs)
            session.commit()
        return len(objs)
    finally:
        session.close()


def _parse_installs(installs: str) -> Optional[int]:
    """'1,000,000+' -> 1000000"""
    if not installs:
        return None
    try:
        return int(installs.replace(",", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return None


# =========================================================
# ScrapeRun (auditoría)
# =========================================================

def start_run(scraper_name: str) -> int:
    session = get_session()
    try:
        run = ScrapeRun(scraper_name=scraper_name, started_at=datetime.utcnow())
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id
    finally:
        session.close()


def finish_run(run_id: int, status: str, items: int = 0,
               errors: int = 0, error_log: str = None):
    session = get_session()
    try:
        run = session.query(ScrapeRun).get(run_id)
        if not run:
            return
        run.finished_at = datetime.utcnow()
        run.status = status
        run.items_collected = items
        run.errors_count = errors
        run.error_log = error_log
        if run.started_at:
            run.duration_sec = (run.finished_at - run.started_at).total_seconds()
        session.commit()
    finally:
        session.close()


# =========================================================
# Queries de análisis
# =========================================================

def trending_terms(days: int = 7, limit: int = 50) -> List[Dict]:
    """Términos con más señales en los últimos N días."""
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(
                SearchSignal.term,
                func.count(SearchSignal.id).label("signal_count"),
                func.count(func.distinct(SearchSignal.source)).label("source_count"),
                func.avg(SearchSignal.score).label("avg_score"),
            )
            .filter(SearchSignal.captured_at >= since)
            .group_by(SearchSignal.term)
            .order_by(desc("signal_count"))
            .limit(limit)
            .all()
        )
        return [
            {
                "term": r.term,
                "signal_count": r.signal_count,
                "source_count": r.source_count,
                "avg_score": float(r.avg_score or 0),
            }
            for r in rows
        ]
    finally:
        session.close()


def top_questions(category: str = None, limit: int = 50) -> List[Dict]:
    session = get_session()
    try:
        q = session.query(Question)
        if category:
            q = q.filter(Question.category == category)
        rows = q.order_by(desc(Question.times_seen)).limit(limit).all()
        return [
            {
                "id": r.id,
                "question": r.question,
                "source": r.source,
                "category": r.category,
                "times_seen": r.times_seen,
                "upvotes": r.upvotes,
                "intent": r.intent,
            }
            for r in rows
        ]
    finally:
        session.close()


def saturated_categories() -> List[Dict]:
    """Categorías con muchas apps competidoras."""
    session = get_session()
    try:
        rows = (
            session.query(
                AppCompetitor.category,
                func.count(AppCompetitor.id).label("apps"),
                func.avg(AppCompetitor.score).label("avg_rating"),
                func.sum(AppCompetitor.installs_num).label("total_installs"),
            )
            .filter(AppCompetitor.category.isnot(None))
            .group_by(AppCompetitor.category)
            .order_by(desc("apps"))
            .all()
        )
        return [
            {
                "category": r.category,
                "apps": r.apps,
                "avg_rating": float(r.avg_rating or 0),
                "total_installs": int(r.total_installs or 0),
            }
            for r in rows
        ]
    finally:
        session.close()
