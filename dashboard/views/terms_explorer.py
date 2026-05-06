"""Vista: Explorador libre de términos."""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px

from database.models import SearchSignal, get_session
from sqlalchemy import func, desc, and_


@st.cache_data(ttl=60)
def _trending(days: int, source: str = None, category: str = None,
               search: str = None, limit: int = 200):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        q = (
            session.query(
                SearchSignal.term,
                SearchSignal.category,
                func.count(SearchSignal.id).label("signals"),
                func.count(func.distinct(SearchSignal.source)).label("sources"),
                func.avg(SearchSignal.score).label("avg_score"),
                func.sum(SearchSignal.volume).label("volume"),
            )
            .filter(SearchSignal.captured_at >= since)
        )
        if source: q = q.filter(SearchSignal.source == source)
        if category: q = q.filter(SearchSignal.category == category)
        if search:
            q = q.filter(SearchSignal.term.ilike(f"%{search}%"))
        rows = (q.group_by(SearchSignal.term, SearchSignal.category)
                .order_by(desc("signals")).limit(limit).all())
        return pd.DataFrame([{
            "termino": r.term, "categoria": r.category,
            "señales": r.signals, "fuentes": r.sources,
            "avg_score": float(r.avg_score or 0),
            "volumen": int(r.volume or 0),
        } for r in rows])
    finally:
        session.close()


@st.cache_data(ttl=60)
def _term_evolution(term: str, days: int):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = session.query(SearchSignal).filter(
            SearchSignal.term == term,
            SearchSignal.captured_at >= since,
        ).all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "date": r.captured_at.date(),
            "source": r.source,
            "score": r.score,
        } for r in rows])
        return df.groupby(["date", "source"]).size().reset_index(name="count")
    finally:
        session.close()


def render():
    st.title("🔍 Explorador de términos")
    days = st.session_state.get("lookback_days", 30)

    c1, c2, c3 = st.columns(3)
    sources = ["", "google_suggest", "youtube_suggest", "reddit",
               "telegram", "play_store", "tiktok", "instagram", "twitter"]
    src = c1.selectbox("Fuente", sources)
    cats = ["", "finanzas", "tramites", "trabajo", "compras", "salud",
            "transporte", "general", "social_media"]
    cat = c2.selectbox("Categoría", cats)
    search = c3.text_input("Buscar contiene…", placeholder="ej: dolar")

    df = _trending(days, src or None, cat or None, search or None)
    if df.empty:
        st.info("Sin términos con esos filtros.")
        return

    st.write(f"**{len(df)}** términos únicos encontrados")
    st.dataframe(df, use_container_width=True, height=500, hide_index=True)

    st.divider()
    st.subheader("📈 Evolución de un término")
    sel = st.selectbox("Elegí un término", df["termino"].head(50).tolist())
    if sel:
        evo = _term_evolution(sel, days)
        if not evo.empty:
            fig = px.line(evo, x="date", y="count", color="source",
                           markers=True, title=f"'{sel}' a lo largo del tiempo")
            st.plotly_chart(fig, use_container_width=True)

    st.download_button("📥 CSV", df.to_csv(index=False).encode("utf-8"),
                        file_name="terminos.csv", mime="text/csv")
