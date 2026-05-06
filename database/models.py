"""
Modelos SQLAlchemy.

Esquema diseñado alrededor de tres entidades:
1. SearchSignal: cualquier observación de interés sobre un término
2. Question: pregunta concreta detectada (más accionable)
3. AppCompetitor: app del Play Store con sus métricas
4. NicheOpportunity: nicho detectado por el analyzer
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Text, Boolean, Index, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config.settings import DATABASE_URL

Base = declarative_base()


class SearchSignal(Base):
    """Señal individual de interés sobre un término en una fuente y momento."""
    __tablename__ = "search_signals"

    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    source = Column(String(50), nullable=False, index=True)
    # google_trends, google_suggest, youtube_suggest, reddit, youtube, wikipedia,
    # mercadolibre, play_store, instagram, twitter, tiktok

    source_subtype = Column(String(50))
    # ej: para reddit -> "post" / "comment", para play_store -> "review" / "search"

    term = Column(String(500), nullable=False, index=True)
    raw_term = Column(String(500))

    category = Column(String(100), index=True)
    region = Column(String(20), default="AR")

    score = Column(Float, default=0)        # normalizado 0-100
    volume = Column(Integer, default=0)     # absoluto si lo da la fuente
    growth_pct = Column(Float)              # variación % vs período anterior
    is_rising = Column(Boolean, default=False)

    url = Column(Text)
    extra = Column(JSON)  # campos extra específicos de cada fuente

    __table_args__ = (
        Index("ix_term_source_time", "term", "source", "captured_at"),
        Index("ix_source_category_time", "source", "category", "captured_at"),
    )


class Question(Base):
    """
    Pregunta concreta extraída de cualquier fuente.
    Más accionable que un keyword suelto: ya tiene forma de problema a resolver.
    """
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    question = Column(Text, nullable=False)
    question_hash = Column(String(64), unique=True, index=True)
    # SHA1 del texto normalizado para deduplicar

    source = Column(String(50), nullable=False, index=True)
    source_url = Column(Text)
    category = Column(String(100), index=True)

    times_seen = Column(Integer, default=1)
    # cada vez que la detectamos de nuevo, incrementamos

    upvotes = Column(Integer, default=0)
    answers_count = Column(Integer, default=0)

    intent = Column(String(50), index=True)
    # how_to, what_is, where, when, why, comparison, problem, price

    extra = Column(JSON)

    __table_args__ = (
        Index("ix_question_category_seen", "category", "times_seen"),
    )


class AppCompetitor(Base):
    """
    App del Play Store identificada como competencia en un nicho.
    Acá vamos a guardar métricas de competencia y reviews para detectar gaps.
    """
    __tablename__ = "app_competitors"

    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    app_id = Column(String(200), unique=True, nullable=False, index=True)
    # ej: com.mercadopago.wallet

    title = Column(String(300), nullable=False)
    developer = Column(String(200))
    category = Column(String(100), index=True)

    score = Column(Float)         # rating promedio
    ratings_count = Column(Integer)
    reviews_count = Column(Integer)
    installs = Column(String(50))     # ej "1,000,000+"
    installs_num = Column(Integer)    # parsed lower bound
    free = Column(Boolean)
    price = Column(Float)

    description = Column(Text)
    summary = Column(String(500))

    # Para qué query la encontramos
    discovered_via_query = Column(String(300), index=True)
    rank_in_query = Column(Integer)  # posición en el ranking de esa query

    last_updated_play = Column(DateTime)
    extra = Column(JSON)

    reviews = relationship("AppReview", back_populates="app", cascade="all, delete-orphan")


class AppReview(Base):
    """
    Review de Play Store. Mina de oro para entender qué le falta a las apps.
    Especialmente las de 1-2 estrellas: dicen los problemas reales.
    """
    __tablename__ = "app_reviews"

    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    app_id_fk = Column(Integer, ForeignKey("app_competitors.id"), index=True)
    review_id = Column(String(200), unique=True, index=True)

    user_name = Column(String(200))
    score = Column(Integer)        # 1-5
    content = Column(Text)
    thumbs_up = Column(Integer, default=0)
    review_date = Column(DateTime, index=True)

    # Análisis posterior
    sentiment = Column(String(20))    # positive / neutral / negative
    pain_points = Column(JSON)        # lista de problemas detectados por NLP
    feature_requests = Column(JSON)   # features pedidas

    app = relationship("AppCompetitor", back_populates="reviews")


class NicheOpportunity(Base):
    """
    Nicho detectado por el analyzer.
    Una NicheOpportunity es una hipótesis con datos: "hay demanda X, competencia Y, gap Z".
    """
    __tablename__ = "niche_opportunities"

    id = Column(Integer, primary_key=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated_at = Column(DateTime, default=datetime.utcnow)

    name = Column(String(300), nullable=False)
    category = Column(String(100), index=True)
    description = Column(Text)

    # Métricas agregadas que justifican el nicho
    demand_score = Column(Float)         # 0-100, basado en volumen de señales
    competition_score = Column(Float)    # 0-100, qué tan saturado (más bajo = mejor)
    opportunity_score = Column(Float, index=True)  # demanda - competencia, normalizado

    # Volúmenes que respaldan
    signals_count = Column(Integer)
    questions_count = Column(Integer)
    avg_competitor_rating = Column(Float)
    competitors_count = Column(Integer)

    # Términos clave del nicho
    top_terms = Column(JSON)
    top_questions = Column(JSON)
    top_pain_points = Column(JSON)

    # Estado de revisión
    status = Column(String(30), default="detected")
    # detected, reviewing, validated, building, discarded

    notes = Column(Text)


class ScrapeRun(Base):
    """Auditoría de cada corrida de scraper."""
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime)

    scraper_name = Column(String(100), nullable=False, index=True)
    status = Column(String(20))   # success, partial, failed
    items_collected = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    error_log = Column(Text)
    duration_sec = Column(Float)


# === Engine y session ===
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    """Context manager simple para sesiones."""
    return SessionLocal()


def init_db():
    """Crea todas las tablas."""
    Base.metadata.create_all(engine)
    print(f"✅ DB inicializada en {DATABASE_URL}")


if __name__ == "__main__":
    init_db()
