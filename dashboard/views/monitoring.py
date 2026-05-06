"""Vista: Monitor activo — estado en tiempo real de los scrapers."""
from datetime import datetime, timedelta
import time
import streamlit as st
import pandas as pd
from sqlalchemy import desc, func

from database.models import ScrapeRun, SearchSignal, AppCompetitor, get_session


SCRAPERS = {
    "google_suggest": {"label": "Google Suggest", "icon": "🔍", "freq": "cada 6h"},
    "youtube_suggest": {"label": "YouTube Suggest", "icon": "▶️", "freq": "cada 6h"},
    "play_store": {"label": "Play Store", "icon": "📱", "freq": "1x día"},
}

SOURCE_COLORS = {
    "google_suggest": "#4285f4",
    "youtube_suggest": "#ff0000",
    "play_store": "#01875f",
}


@st.cache_data(ttl=8)
def _load_stats():
    session = get_session()
    try:
        hoy = datetime.utcnow() - timedelta(hours=24)
        signals_hoy = session.query(func.count(SearchSignal.id)).filter(
            SearchSignal.captured_at >= hoy
        ).scalar() or 0
        signals_total = session.query(func.count(SearchSignal.id)).scalar() or 0
        apps_total = session.query(func.count(AppCompetitor.id)).scalar() or 0
        runs_hoy = session.query(func.count(ScrapeRun.id)).filter(
            ScrapeRun.started_at >= hoy
        ).scalar() or 0
        total_runs = session.query(func.count(ScrapeRun.id)).scalar() or 0
        success_runs = session.query(func.count(ScrapeRun.id)).filter(
            ScrapeRun.status == "success"
        ).scalar() or 0
        success_pct = int(success_runs / total_runs * 100) if total_runs > 0 else 100
        return dict(
            signals_hoy=signals_hoy,
            signals_total=signals_total,
            apps_total=apps_total,
            runs_hoy=runs_hoy,
            success_pct=success_pct,
        )
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_scraper_status():
    session = get_session()
    try:
        result = {}
        for name in SCRAPERS:
            last = (
                session.query(ScrapeRun)
                .filter(ScrapeRun.scraper_name == name)
                .order_by(desc(ScrapeRun.started_at))
                .first()
            )
            result[name] = {
                "last_run": last.started_at if last else None,
                "status": last.status if last else "sin datos",
                "items": last.items_collected or 0 if last else 0,
                "duration": last.duration_sec or 0 if last else 0,
            }
        return result
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_recent_signals(limit: int = 14):
    session = get_session()
    try:
        rows = (
            session.query(SearchSignal)
            .order_by(desc(SearchSignal.captured_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "fuente": r.source,
                "término": r.raw_term or r.term,
                "categoría": r.category or "—",
                "score": round(r.score or 0, 1),
            }
            for r in rows
        ]
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_run_log(limit: int = 60):
    session = get_session()
    try:
        rows = (
            session.query(ScrapeRun)
            .order_by(desc(ScrapeRun.started_at))
            .limit(limit)
            .all()
        )
        return pd.DataFrame([
            {
                "hora": r.started_at.strftime("%H:%M:%S") if r.started_at else "—",
                "scraper": r.scraper_name,
                "status": r.status or "running",
                "items": r.items_collected or 0,
                "duración s": round(r.duration_sec or 0, 1),
                "errores": r.errors_count or 0,
            }
            for r in rows
        ])
    finally:
        session.close()


def _time_ago(dt) -> str:
    if not dt:
        return "nunca"
    mins = int((datetime.utcnow() - dt).total_seconds() / 60)
    if mins < 1:
        return "hace menos de 1m"
    if mins < 60:
        return f"hace {mins}m"
    hours = mins // 60
    return f"hace {hours}h" if hours < 24 else f"hace {hours // 24}d"


def render():
    now_ar = datetime.utcnow() - timedelta(hours=3)

    # ── Header ──────────────────────────────────────────────
    col_h, col_t = st.columns([3, 1])
    with col_h:
        st.markdown(
            "<h1 style='margin-bottom:0'>🟢 Monitor activo</h1>"
            "<p style='color:#6b7280;margin-top:0'>Scrapers corriendo 24/7 · Argentina Insights</p>",
            unsafe_allow_html=True,
        )
    with col_t:
        st.markdown(
            f"<div style='text-align:right;padding-top:1rem'>"
            f"<span style='color:#6b7280;font-size:0.8rem'>Último update</span><br>"
            f"<b style='font-size:1.1rem'>{now_ar.strftime('%H:%M:%S')}</b><br>"
            f"<span style='color:#6b7280;font-size:0.75rem'>refresh cada 10s</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Stats cards ─────────────────────────────────────────
    stats = _load_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔍 Señales hoy", f"{stats['signals_hoy']:,}")
    c2.metric("📦 Señales total", f"{stats['signals_total']:,}")
    c3.metric("📱 Apps relevadas", f"{stats['apps_total']:,}")
    c4.metric("✅ Éxito scrapers", f"{stats['success_pct']}%")

    # ── Fuentes activas ──────────────────────────────────────
    st.markdown("### Fuentes activas")
    status = _load_scraper_status()
    cols = st.columns(len(SCRAPERS))
    for i, (name, meta) in enumerate(SCRAPERS.items()):
        info = status[name]
        s = info["status"]
        dot = "🟢" if s == "success" else "🔴" if s == "error" else "⚪"
        with cols[i]:
            st.markdown(
                f"<div style='background:#1e293b;padding:1rem;border-radius:10px;"
                f"border:1px solid #334155'>"
                f"<div style='font-size:1rem;font-weight:bold'>{dot} {meta['icon']} {meta['label']}</div>"
                f"<div style='color:#9ca3af;font-size:0.8rem;margin-top:4px'>{_time_ago(info['last_run'])}</div>"
                f"<div style='color:#6b7280;font-size:0.75rem'>{meta['freq']}</div>"
                f"<div style='margin-top:8px;font-size:0.88rem'>"
                f"📦 <b>{info['items']}</b> items &nbsp;·&nbsp; ⏱ {info['duration']:.0f}s"
                f"</div></div>",
                unsafe_allow_html=True,
            )

    # ── Últimas capturas ─────────────────────────────────────
    st.markdown("### Últimas capturas")
    signals = _load_recent_signals()
    if not signals:
        st.info("Aún no hay señales. El bootstrap inicial está corriendo...")
    else:
        col_a, col_b = st.columns(2)
        for i, row in enumerate(signals):
            color = SOURCE_COLORS.get(row["fuente"], "#6b7280")
            target = col_a if i % 2 == 0 else col_b
            with target:
                st.markdown(
                    f"<div style='background:#1e293b;padding:0.7rem 1rem;border-radius:8px;"
                    f"border:1px solid #334155;margin-bottom:0.5rem'>"
                    f"<span style='background:{color};color:white;font-size:0.7rem;"
                    f"padding:2px 8px;border-radius:4px'>{row['fuente']}</span>"
                    f"<div style='margin-top:6px;font-size:0.95rem'>{row['término']}</div>"
                    f"<div style='color:#6b7280;font-size:0.75rem'>"
                    f"{row['categoría']} · score {row['score']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── Log en tiempo real ───────────────────────────────────
    st.markdown("### Log en tiempo real")
    log_df = _load_run_log()
    if log_df.empty:
        st.info("Sin runs registradas aún.")
    else:
        def _color_status(val):
            c = "#10b981" if val == "success" else "#ef4444" if val == "error" else "#f59e0b"
            return f"color: {c}; font-weight: bold"

        st.dataframe(
            log_df.style.map(_color_status, subset=["status"]),
            use_container_width=True,
            height=320,
            hide_index=True,
        )

    # ── Auto-refresh ─────────────────────────────────────────
    if st.sidebar.checkbox("🔄 Auto-refresh (10s)", value=True):
        time.sleep(10)
        st.rerun()
