"""
Agregar tabla Alert al schema.
Ejecutar: python -m alerts.migrations
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON, Index

from database.models import Base, engine


class Alert(Base):
    """
    Alerta detectada. Guardamos historial para:
    1. Evitar mandar la misma alerta dos veces en N días
    2. Tener un feed visible en el dashboard
    3. Aprender qué tipo de alertas son útiles (con feedback manual)
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Tipo de alerta determina la lógica de detección
    kind = Column(String(50), nullable=False, index=True)
    # rising_term, new_question_cluster, high_value_pain, weak_competitor,
    # category_surge, niche_score_jump

    severity = Column(String(20), default="info")
    # critical, high, medium, info

    title = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    # texto formateado listo para enviar por Telegram

    # Datos para deduplicar y contextualizar
    fingerprint = Column(String(200), index=True)
    # hash de los elementos clave (categoría + término) para deduplicar

    category = Column(String(100), index=True)
    metric_value = Column(Float)       # valor numérico que disparó la alerta
    metric_baseline = Column(Float)    # contra qué se comparó

    # Estado
    notified_at = Column(DateTime)
    notified_channel = Column(String(50))   # telegram, log
    user_feedback = Column(String(20))      # useful, noise, null
    user_feedback_at = Column(DateTime)

    # Datos adicionales
    payload = Column(JSON)  # ej: lista de términos relacionados, links

    __table_args__ = (
        Index("ix_alerts_fingerprint_time", "fingerprint", "detected_at"),
    )


def migrate():
    Base.metadata.create_all(engine)
    print("✅ Tabla 'alerts' creada/actualizada")


if __name__ == "__main__":
    migrate()
