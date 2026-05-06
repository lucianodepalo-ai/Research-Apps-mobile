"""Vista: Monitoreo y auditoría de scrapers."""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px

from database.models import ScrapeRun, get_session
from sqlalchemy import desc


@st.cache_data(ttl=30)
def _runs(limit: int = 200):
    session = get_session()
    try:
        rows = session.query(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(limit).all()
        return pd.DataFrame([{
            "scraper": r.scraper_name,
            "started_at": r.started_at,
            "duration_s": r.duration_sec,
            "status": r.status,
            "items": r.items_collected,
            "errors": r.errors_count,
            "error_log": (r.error_log or "")[:500],
        } for r in rows])
    finally:
        session.close()


def render():
    st.title("⚙️ Monitoreo & runs")
    df = _runs()
    if df.empty:
        st.info("Sin runs registradas.")
        return

    # KPIs
    last_24h = df[df["started_at"] >= datetime.utcnow() - timedelta(hours=24)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs últimas 24h", len(last_24h))
    c2.metric("Items últimas 24h", int(last_24h["items"].sum()) if not last_24h.empty else 0)
    success_pct = ((df["status"] == "success").mean() * 100) if len(df) else 0
    c3.metric("% éxito", f"{success_pct:.0f}%")
    c4.metric("Scrapers activos", df["scraper"].nunique())

    # Por scraper
    st.subheader("Performance por scraper")
    by_scr = df.groupby("scraper").agg(
        runs=("scraper", "count"),
        items_total=("items", "sum"),
        avg_duration=("duration_s", "mean"),
        errors=("errors", "sum"),
    ).reset_index()
    st.dataframe(by_scr, use_container_width=True, hide_index=True)

    # Timeline
    st.subheader("Timeline reciente")
    fig = px.scatter(
        df.head(100), x="started_at", y="scraper",
        color="status", size="items",
        hover_data=["duration_s", "errors"],
    )
    st.plotly_chart(fig, use_container_width=True)

    # Tabla detallada
    st.subheader("Detalle de runs")
    st.dataframe(df, use_container_width=True, height=500, hide_index=True)
