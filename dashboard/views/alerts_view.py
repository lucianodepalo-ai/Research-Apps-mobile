"""
Vista: Alertas detectadas.

Muestra el historial de alertas y permite dar feedback (útil/ruido)
para ajustar umbrales en el futuro.
"""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import desc

from database.models import get_session
from alerts.migrations import Alert
from alerts.detector import AlertDetector
from alerts.telegram_notifier import TelegramNotifier


def _load_alerts(days: int):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(Alert)
            .filter(Alert.detected_at >= since)
            .order_by(desc(Alert.detected_at))
            .all()
        )
        return rows
    finally:
        session.close()


def _set_feedback(alert_id: int, feedback: str):
    session = get_session()
    try:
        a = session.query(Alert).filter(Alert.id == alert_id).first()
        if a:
            a.user_feedback = feedback
            a.user_feedback_at = datetime.utcnow()
            session.commit()
    finally:
        session.close()


def render():
    st.title("🔔 Alertas")
    st.caption(
        "Eventos significativos detectados automáticamente. "
        "Marcá cada alerta como útil o ruido para ajustar umbrales."
    )

    # Acciones manuales
    c1, c2, c3 = st.columns(3)
    if c1.button("🔄 Detectar ahora"):
        with st.spinner("Detectando..."):
            new = AlertDetector().run()
            st.success(f"{len(new)} alertas nuevas")
    if c2.button("📤 Enviar pendientes a Telegram"):
        with st.spinner("Enviando..."):
            sent = TelegramNotifier().send_pending_alerts(batch_size=20)
            st.success(f"{sent} mensajes enviados")
    if c3.button("📅 Mandar digest 24h"):
        with st.spinner("Enviando digest..."):
            ok = TelegramNotifier().send_daily_digest()
            st.success("Digest enviado") if ok else st.warning("Sin alertas o falló")

    days = st.session_state.get("lookback_days", 30)
    alerts = _load_alerts(days)
    if not alerts:
        st.info(
            f"Sin alertas en los últimos {days} días. "
            "Tocá 'Detectar ahora' o esperá a que el scheduler corra."
        )
        return

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(alerts))
    c2.metric("Críticas/Altas",
              sum(1 for a in alerts if a.severity in ("critical", "high")))
    c3.metric("Notificadas",
              sum(1 for a in alerts if a.notified_at))
    c4.metric("Marcadas útiles",
              sum(1 for a in alerts if a.user_feedback == "useful"))

    # Distribución
    df = pd.DataFrame([{
        "id": a.id,
        "kind": a.kind,
        "severity": a.severity,
        "category": a.category,
        "title": a.title,
        "detected_at": a.detected_at,
        "notified": bool(a.notified_at),
        "feedback": a.user_feedback,
    } for a in alerts])

    col_a, col_b = st.columns(2)
    with col_a:
        by_kind = df["kind"].value_counts().reset_index()
        by_kind.columns = ["kind", "count"]
        st.plotly_chart(
            px.pie(by_kind, names="kind", values="count", title="Por tipo"),
            use_container_width=True,
        )
    with col_b:
        by_sev = df["severity"].value_counts().reset_index()
        by_sev.columns = ["severity", "count"]
        st.plotly_chart(
            px.bar(by_sev, x="severity", y="count",
                   color="severity",
                   color_discrete_map={
                       "critical": "#ef4444", "high": "#f59e0b",
                       "medium": "#3b82f6", "info": "#6b7280",
                   }),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Feed de alertas")

    # Filtros
    cf1, cf2, cf3 = st.columns(3)
    sel_kinds = cf1.multiselect("Tipo", df["kind"].unique())
    sel_sev = cf2.multiselect("Severidad", df["severity"].unique())
    sel_cat = cf3.multiselect("Categoría", df["category"].dropna().unique())

    filtered = alerts
    if sel_kinds:
        filtered = [a for a in filtered if a.kind in sel_kinds]
    if sel_sev:
        filtered = [a for a in filtered if a.severity in sel_sev]
    if sel_cat:
        filtered = [a for a in filtered if a.category in sel_cat]

    severity_color = {
        "critical": "🚨", "high": "⚠️", "medium": "🔔", "info": "ℹ️",
    }
    for a in filtered[:50]:
        emoji = severity_color.get(a.severity, "🔔")
        with st.container():
            st.markdown(
                f"### {emoji} {a.title}  \n"
                f"_{a.detected_at.strftime('%Y-%m-%d %H:%M')} · "
                f"`{a.kind}` · "
                f"{'✅ Notificada' if a.notified_at else '📨 Pendiente'}_"
            )
            st.markdown(a.message)

            # Feedback
            fb_cols = st.columns([1, 1, 4])
            current_fb = a.user_feedback
            if fb_cols[0].button(
                "👍 Útil" + (" ✓" if current_fb == "useful" else ""),
                key=f"useful_{a.id}",
            ):
                _set_feedback(a.id, "useful")
                st.rerun()
            if fb_cols[1].button(
                "👎 Ruido" + (" ✓" if current_fb == "noise" else ""),
                key=f"noise_{a.id}",
            ):
                _set_feedback(a.id, "noise")
                st.rerun()

            st.divider()
