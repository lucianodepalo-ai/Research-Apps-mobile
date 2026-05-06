"""Vista: Resumen general - dashboard principal con KPIs."""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px

from database.models import (
    SearchSignal, Question, AppCompetitor, AppReview,
    NicheOpportunity, ScrapeRun, get_session
)
from sqlalchemy import func, desc


@st.cache_data(ttl=60)
def _kpis(days: int):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        signals = session.query(func.count(SearchSignal.id)).filter(
            SearchSignal.captured_at >= since
        ).scalar()
        questions = session.query(func.count(Question.id)).filter(
            Question.last_seen_at >= since
        ).scalar()
        apps = session.query(func.count(AppCompetitor.id)).scalar()
        reviews = session.query(func.count(AppReview.id)).scalar()
        opps = session.query(func.count(NicheOpportunity.id)).scalar()
        sources = session.query(
            func.count(func.distinct(SearchSignal.source))
        ).filter(SearchSignal.captured_at >= since).scalar()
        return {
            "signals": signals or 0,
            "questions": questions or 0,
            "apps": apps or 0,
            "reviews": reviews or 0,
            "opportunities": opps or 0,
            "sources": sources or 0,
        }
    finally:
        session.close()


@st.cache_data(ttl=60)
def _signals_by_day(days: int):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = session.query(SearchSignal).filter(
            SearchSignal.captured_at >= since
        ).all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "date": r.captured_at.date(),
            "source": r.source,
            "category": r.category,
        } for r in rows])
        return df
    finally:
        session.close()


def render():
    st.title("📊 Resumen general")
    days = st.session_state.get("lookback_days", 30)

    k = _kpis(days)

    if k["signals"] == 0:
        st.warning(
            f"No hay señales en los últimos {days} días.  \n"
            "Corré: `python run_all.py --init --tier 1,2 --analyze`"
        )
        return

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Señales", f"{k['signals']:,}")
    c2.metric("Preguntas únicas", f"{k['questions']:,}")
    c3.metric("Apps mapeadas", f"{k['apps']:,}")
    c4.metric("Reviews", f"{k['reviews']:,}")
    c5.metric("Nichos detectados", f"{k['opportunities']:,}")
    c6.metric("Fuentes activas", k['sources'])

    df = _signals_by_day(days)
    if df.empty:
        return

    st.subheader("Volumen de señales en el tiempo")
    daily = df.groupby(["date", "source"]).size().reset_index(name="count")
    fig = px.area(daily, x="date", y="count", color="source",
                   title=f"Últimos {days} días")
    st.plotly_chart(fig, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Por fuente")
        by_src = df["source"].value_counts().reset_index()
        by_src.columns = ["fuente", "señales"]
        st.plotly_chart(
            px.bar(by_src, x="fuente", y="señales"),
            use_container_width=True,
        )
    with col_b:
        st.subheader("Por categoría")
        by_cat = df["category"].fillna("sin_categoria").value_counts().head(10).reset_index()
        by_cat.columns = ["categoria", "señales"]
        st.plotly_chart(
            px.bar(by_cat, x="categoria", y="señales"),
            use_container_width=True,
        )
