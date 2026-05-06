"""Vista: Monitor activo en tiempo real - estado en vivo del sistema."""
import re
import time
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
from sqlalchemy import desc, func

from config.settings import LOG_DIR
from database.models import (
    ScrapeRun, SearchSignal, AppCompetitor, AppReview, get_session
)


SCRAPERS = {
    "google_suggest":  {"label": "Google Suggest",  "icon": "🔍", "freq_h": 6,  "freq_label": "cada 6h",  "color": "#4285f4"},
    "youtube_suggest": {"label": "YouTube Suggest", "icon": "▶️",  "freq_h": 6,  "freq_label": "cada 6h",  "color": "#ff0000"},
    "play_store":      {"label": "Play Store",      "icon": "📱", "freq_h": 24, "freq_label": "1x día",   "color": "#01875f"},
}

# Patrones de log → traducciones humanas en español
LOG_PATTERNS = [
    (r"=== Iniciando (\w+).*===",
        lambda m: f"▶️ Arrancó scraper: {m.group(1)}"),
    (r"=== JOB: (.+?) ===",
        lambda m: f"⚙️ Job programado disparó: {m.group(1).strip()}"),
    (r"✅ (\w+):\s+(\d+)\s+señales guardadas",
        lambda m: f"✅ {m.group(1)} terminó: capturó {m.group(2)} señales nuevas"),
    (r"❌ (\w+) falló: (.+?)$",
        lambda m: f"❌ {m.group(1)} ROMPIÓ: {m.group(2)[:80]}"),
    (r"intento (\d+)/(\d+) falló: (.+?)\.\s+Reintentando en (\d+)s",
        lambda m: f"⚠️ Reintento {m.group(1)}/{m.group(2)} falló ({m.group(3)[:50]}...) — esperando {m.group(4)}s"),
    (r"Bootstrap inicial",
        lambda m: "🚀 Bootstrap inicial — primera corrida de todos los scrapers"),
    (r"Scheduler iniciado",
        lambda m: "🟢 Scheduler arrancó OK"),
    (r"Snapshot:\s+(\d+)\s+niches",
        lambda m: f"📸 Snapshot diario guardado: {m.group(1)} niches"),
    (r"Detector:\s+(\d+)\s+alertas nuevas",
        lambda m: f"🔔 Detector encontró {m.group(1)} alertas nuevas"),
    (r"Shutdown signal",
        lambda m: "🛑 Señal de shutdown recibida"),
]


def _translate(msg: str) -> str:
    for pat, fn in LOG_PATTERNS:
        m = re.search(pat, msg)
        if m:
            return fn(m)
    return msg


# ============================================================
# Loaders
# ============================================================

@st.cache_data(ttl=4)
def _load_running():
    """Runs en curso (sin finished_at)."""
    session = get_session()
    try:
        rows = session.query(ScrapeRun).filter(
            ScrapeRun.finished_at.is_(None)
        ).order_by(desc(ScrapeRun.started_at)).all()
        return [
            {"scraper": r.scraper_name, "started_at": r.started_at, "run_id": r.id}
            for r in rows
        ]
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_full_stats():
    session = get_session()
    try:
        h24 = datetime.utcnow() - timedelta(hours=24)
        sem = datetime.utcnow() - timedelta(days=7)

        total_runs = session.query(func.count(ScrapeRun.id)).filter(
            ScrapeRun.finished_at.isnot(None)
        ).scalar() or 0
        ok_runs = session.query(func.count(ScrapeRun.id)).filter(
            ScrapeRun.status == "success"
        ).scalar() or 0
        success_pct = int(ok_runs / total_runs * 100) if total_runs else 100

        return {
            "signals_hoy": session.query(func.count(SearchSignal.id)).filter(SearchSignal.captured_at >= h24).scalar() or 0,
            "signals_total": session.query(func.count(SearchSignal.id)).scalar() or 0,
            "signals_semana": session.query(func.count(SearchSignal.id)).filter(SearchSignal.captured_at >= sem).scalar() or 0,
            "apps_total": session.query(func.count(AppCompetitor.id)).scalar() or 0,
            "reviews_total": session.query(func.count(AppReview.id)).scalar() or 0,
            "runs_hoy": session.query(func.count(ScrapeRun.id)).filter(ScrapeRun.started_at >= h24).scalar() or 0,
            "success_pct": success_pct,
        }
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_scraper_status():
    session = get_session()
    try:
        out = {}
        sem = datetime.utcnow() - timedelta(days=7)
        for name in SCRAPERS:
            last = session.query(ScrapeRun).filter(
                ScrapeRun.scraper_name == name
            ).order_by(desc(ScrapeRun.started_at)).first()

            runs_7d = session.query(func.count(ScrapeRun.id)).filter(
                ScrapeRun.scraper_name == name,
                ScrapeRun.started_at >= sem,
            ).scalar() or 0
            ok_7d = session.query(func.count(ScrapeRun.id)).filter(
                ScrapeRun.scraper_name == name,
                ScrapeRun.started_at >= sem,
                ScrapeRun.status == "success",
            ).scalar() or 0
            items_7d = session.query(func.sum(ScrapeRun.items_collected)).filter(
                ScrapeRun.scraper_name == name,
                ScrapeRun.started_at >= sem,
            ).scalar() or 0

            out[name] = {
                "last_run": last.started_at if last else None,
                "last_finish": last.finished_at if last else None,
                "status": (last.status if last else None) or "sin_datos",
                "items": (last.items_collected or 0) if last else 0,
                "duration": (last.duration_sec or 0) if last else 0,
                "is_running": (last is not None and last.finished_at is None),
                "runs_7d": runs_7d,
                "ok_7d": ok_7d,
                "items_7d": int(items_7d or 0),
            }
        return out
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_recent_signals(limit: int = 10):
    session = get_session()
    try:
        rows = session.query(SearchSignal).order_by(
            desc(SearchSignal.captured_at)
        ).limit(limit).all()
        return [{
            "fuente": r.source,
            "término": (r.raw_term or r.term or "")[:80],
            "categoría": r.category or "—",
            "score": round(r.score or 0, 1),
            "hora": r.captured_at,
        } for r in rows]
    finally:
        session.close()


@st.cache_data(ttl=8)
def _load_run_log(limit: int = 80):
    session = get_session()
    try:
        rows = session.query(ScrapeRun).order_by(
            desc(ScrapeRun.started_at)
        ).limit(limit).all()
        ar_offset = timedelta(hours=3)
        return pd.DataFrame([{
            "hora": (r.started_at - ar_offset).strftime("%H:%M:%S") if r.started_at else "—",
            "scraper": r.scraper_name,
            "status": r.status or "running",
            "items": r.items_collected or 0,
            "duración s": round(r.duration_sec or 0, 1),
            "errores": r.errors_count or 0,
        } for r in rows])
    finally:
        session.close()


@st.cache_data(ttl=30)
def _load_hourly_activity():
    """Runs por hora (AR) últimas 24h."""
    session = get_session()
    try:
        h24 = datetime.utcnow() - timedelta(hours=24)
        rows = session.query(ScrapeRun.started_at).filter(
            ScrapeRun.started_at >= h24
        ).all()
        buckets = {}
        for (st_at,) in rows:
            if st_at:
                local = st_at - timedelta(hours=3)
                key = local.strftime("%H")
                buckets[key] = buckets.get(key, 0) + 1
        return buckets
    finally:
        session.close()


@st.cache_data(ttl=4)
def _tail_logs(n_lines: int = 50):
    """Lee tail de logs/*.log, parsea formato loguru y traduce."""
    if not LOG_DIR.exists():
        return []

    raw = []
    for log_file in LOG_DIR.glob("*.log"):
        try:
            with open(log_file, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 80_000))
                content = f.read().decode("utf-8", errors="replace")
            for line in content.splitlines()[-(n_lines * 2):]:
                if line.strip():
                    raw.append((line, log_file.stem))
        except Exception:
            continue

    parsed = []
    # loguru format: 2026-05-06 04:37:18.123 | INFO     | module:func:line - mensaje
    pat = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\s*\|\s*(\w+)\s*\|\s*[^|]*?-\s*(.+)$"
    )
    for line, source in raw:
        m = pat.match(line)
        if not m:
            continue
        ts_str, lvl, msg = m.group(1), m.group(2), m.group(3)
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        parsed.append({
            "ts": ts,
            "level": lvl,
            "msg": _translate(msg),
            "raw": msg,
            "source": source,
        })

    parsed.sort(key=lambda x: x["ts"], reverse=True)
    return parsed[:n_lines]


# ============================================================
# Helpers
# ============================================================

def _time_ago(dt) -> str:
    if not dt:
        return "nunca"
    secs = int((datetime.utcnow() - dt).total_seconds())
    if secs < 0:
        return "ahora"
    if secs < 60:
        return f"hace {secs}s"
    mins = secs // 60
    if mins < 60:
        return f"hace {mins}m"
    hours = mins // 60
    if hours < 24:
        return f"hace {hours}h"
    return f"hace {hours // 24}d"


def _next_run_str(scraper_name: str, last_run) -> str:
    if not last_run:
        return "—"
    freq_h = SCRAPERS[scraper_name]["freq_h"]
    nxt = last_run + timedelta(hours=freq_h)
    delta_s = int((nxt - datetime.utcnow()).total_seconds())
    if delta_s <= 0:
        return "🟡 corriendo pronto"
    h = delta_s // 3600
    m = (delta_s % 3600) // 60
    if h > 0:
        return f"en {h}h {m}m"
    return f"en {m}m"


# ============================================================
# Render
# ============================================================

def render():
    now_ar = datetime.utcnow() - timedelta(hours=3)
    running = _load_running()
    is_active = len(running) > 0

    # ── HERO BANNER ─────────────────────────────────────────
    if is_active:
        names = ", ".join(r["scraper"] for r in running)
        c = "#10b981"
        glow = "0 0 40px rgba(16,185,129,0.45)"
        title = "🟢 SISTEMA TRABAJANDO"
        sub = f"Corriendo ahora mismo: <b>{names}</b>"
    else:
        c = "#64748b"
        glow = "none"
        title = "⚪ SISTEMA EN ESPERA"
        sub = "Idle — los scrapers están durmiendo, próxima corrida programada abajo"

    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,{c}26,{c}05);
                    border:2px solid {c};border-radius:14px;padding:1.5rem 2rem;
                    box-shadow:{glow};margin-bottom:1rem'>
          <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap'>
            <div>
              <div style='font-size:1.9rem;font-weight:bold;color:{c}'>{title}</div>
              <div style='color:#cbd5e1;font-size:0.95rem;margin-top:6px'>{sub}</div>
            </div>
            <div style='text-align:right'>
              <div style='color:#94a3b8;font-size:0.78rem'>Hora Argentina · UTC-3</div>
              <div style='font-size:2rem;font-weight:bold;font-variant-numeric:tabular-nums;color:#f1f5f9'>
                {now_ar.strftime('%H:%M:%S')}
              </div>
              <div style='color:#94a3b8;font-size:0.75rem'>{now_ar.strftime('%a %d %b %Y')}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── STATS CARDS ─────────────────────────────────────────
    stats = _load_full_stats()
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🔍 Señales 24h", f"{stats['signals_hoy']:,}")
    c2.metric("📦 Señales total", f"{stats['signals_total']:,}")
    c3.metric("📱 Apps Play", f"{stats['apps_total']:,}")
    c4.metric("⭐ Reviews", f"{stats['reviews_total']:,}")
    c5.metric("🔁 Runs 24h", f"{stats['runs_hoy']}")
    c6.metric("✅ Éxito", f"{stats['success_pct']}%")

    st.markdown("---")

    # ── SCRAPER CARDS ───────────────────────────────────────
    st.markdown("### 📡 Estado por scraper")
    status = _load_scraper_status()
    cols = st.columns(len(SCRAPERS))
    for i, (name, meta) in enumerate(SCRAPERS.items()):
        info = status[name]
        if info["is_running"]:
            dot, lbl, c_color = "🟢", "TRABAJANDO", "#10b981"
        elif info["status"] == "success":
            dot, lbl, c_color = "🟢", "OK", "#10b981"
        elif info["status"] in ("error", "failed"):
            dot, lbl, c_color = "🔴", "ERROR", "#ef4444"
        else:
            dot, lbl, c_color = "⚪", "SIN DATOS", "#64748b"

        ok_pct = int(info["ok_7d"] / info["runs_7d"] * 100) if info["runs_7d"] else 0
        next_str = _next_run_str(name, info["last_run"])

        with cols[i]:
            st.markdown(
                f"""
                <div style='background:#1e293b;padding:1.2rem;border-radius:12px;
                            border:1px solid {c_color}55;border-left:5px solid {c_color}'>
                  <div style='display:flex;justify-content:space-between;align-items:start'>
                    <div style='font-size:1.05rem;font-weight:bold;color:#f1f5f9'>
                      {meta['icon']} {meta['label']}
                    </div>
                    <span style='background:{c_color};color:white;font-size:0.68rem;
                                  padding:3px 9px;border-radius:6px;font-weight:bold'>
                      {dot} {lbl}
                    </span>
                  </div>
                  <div style='color:#94a3b8;font-size:0.8rem;margin-top:8px'>
                    Última corrida: <b style='color:#e5e7eb'>{_time_ago(info['last_run'])}</b>
                  </div>
                  <div style='color:#94a3b8;font-size:0.8rem'>
                    Próxima: <b style='color:#e5e7eb'>{next_str}</b> · {meta['freq_label']}
                  </div>
                  <div style='margin-top:12px;padding-top:10px;border-top:1px solid #334155;
                              display:flex;justify-content:space-between;font-size:0.88rem;color:#e5e7eb'>
                    <span>📦 <b>{info['items']}</b><br>
                          <span style='color:#64748b;font-size:0.7rem'>último</span></span>
                    <span>⏱ <b>{info['duration']:.0f}s</b><br>
                          <span style='color:#64748b;font-size:0.7rem'>duración</span></span>
                    <span>📊 <b>{ok_pct}%</b><br>
                          <span style='color:#64748b;font-size:0.7rem'>éxito 7d</span></span>
                  </div>
                  <div style='margin-top:8px;font-size:0.75rem;color:#64748b'>
                    7 días: {info['runs_7d']} runs · {info['items_7d']:,} ítems totales
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("")

    # ── LIVE LOG ────────────────────────────────────────────
    st.markdown("### 📺 Log en vivo (traducido al español)")
    log_lines = _tail_logs(50)
    if not log_lines:
        st.info(
            "Aún no hay logs. Esperando que los scrapers escriban en `logs/*.log`. "
            "Si recién arrancó el sistema, dale 1-2 minutos y refrescá."
        )
    else:
        html = []
        for ln in log_lines:
            ts_local = (ln["ts"] - timedelta(hours=3)).strftime("%H:%M:%S")
            lvl = ln["level"]
            color = {
                "ERROR": "#ef4444",
                "WARNING": "#f59e0b",
                "INFO": "#10b981",
                "DEBUG": "#64748b",
            }.get(lvl, "#cbd5e1")
            html.append(
                f"<div style='padding:4px 8px;border-bottom:1px solid #1f2937'>"
                f"<span style='color:#64748b;font-size:0.75rem'>{ts_local}</span> "
                f"<span style='color:{color};font-weight:bold;font-size:0.74rem'>[{lvl}]</span> "
                f"<span style='color:#475569;font-size:0.72rem'>({ln['source']})</span> "
                f"<span style='color:#e5e7eb;font-size:0.85rem'>{ln['msg']}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='background:#0b1120;border:1px solid #1e293b;border-radius:10px;"
            f"font-family:Consolas,Menlo,monospace;height:420px;overflow-y:auto'>"
            f"{''.join(html)}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── ACTIVIDAD POR HORA + ÚLTIMAS SEÑALES ────────────────
    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.markdown("### 📊 Actividad por hora (24h)")
        hourly = _load_hourly_activity()
        hours_seq = [(now_ar - timedelta(hours=i)).strftime("%H") for i in reversed(range(24))]
        df_act = pd.DataFrame({
            "hora": [f"{h}h" for h in hours_seq],
            "runs": [hourly.get(h, 0) for h in hours_seq],
        })
        if df_act["runs"].sum() == 0:
            st.info("Sin runs registradas en las últimas 24h")
        else:
            st.bar_chart(df_act.set_index("hora"), height=320, color="#10b981")

    with col_r:
        st.markdown("### 🆕 Últimas señales capturadas")
        signals = _load_recent_signals(8)
        if not signals:
            st.info("Sin señales aún")
        else:
            for r in signals:
                color = SCRAPERS.get(r["fuente"], {}).get("color", "#64748b")
                ago = _time_ago(r["hora"])
                st.markdown(
                    f"<div style='background:#1e293b;padding:0.6rem 0.9rem;border-radius:8px;"
                    f"border-left:3px solid {color};margin-bottom:0.4rem'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                    f"<span style='color:#f1f5f9;font-size:0.88rem'>{r['término']}</span>"
                    f"<span style='color:#64748b;font-size:0.7rem'>{ago}</span></div>"
                    f"<div style='color:#94a3b8;font-size:0.72rem;margin-top:3px'>"
                    f"<span style='background:{color};color:white;padding:1px 6px;"
                    f"border-radius:3px;font-size:0.65rem'>{r['fuente']}</span> "
                    f"· {r['categoría']} · score {r['score']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── HISTÓRICO RUNS ──────────────────────────────────────
    st.markdown("### 📋 Histórico de corridas (últimas 80)")
    log_df = _load_run_log(80)
    if log_df.empty:
        st.info("Sin runs registradas aún.")
    else:
        def _color_status(val):
            if val == "success":
                return "color:#10b981;font-weight:bold"
            if val in ("error", "failed"):
                return "color:#ef4444;font-weight:bold"
            return "color:#f59e0b;font-weight:bold"

        st.dataframe(
            log_df.style.map(_color_status, subset=["status"]),
            use_container_width=True,
            height=320,
            hide_index=True,
        )

    # ── SIDEBAR: AUTO-REFRESH ───────────────────────────────
    st.sidebar.markdown("### Monitor")
    refresh = st.sidebar.checkbox("🔄 Auto-refresh", value=True)
    interval = st.sidebar.slider("Intervalo (segundos)", 3, 30, 5)
    st.sidebar.caption(
        f"{'🟢 ACTIVO' if is_active else '⚪ IDLE'} · "
        f"última actualización {datetime.utcnow().strftime('%H:%M:%S')} UTC"
    )

    if refresh:
        time.sleep(interval)
        st.rerun()
