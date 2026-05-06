"""Vista: Preguntas reales que hacen los argentinos."""
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px

from database.models import Question, get_session
from sqlalchemy import desc


@st.cache_data(ttl=60)
def _load(days: int):
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (session.query(Question)
                .filter(Question.last_seen_at >= since)
                .order_by(desc(Question.times_seen))
                .limit(2000).all())
        return pd.DataFrame([{
            "question": r.question,
            "source": r.source,
            "category": r.category,
            "intent": r.intent,
            "times_seen": r.times_seen,
            "upvotes": r.upvotes,
            "answers": r.answers_count,
            "url": r.source_url,
            "last_seen": r.last_seen_at,
        } for r in rows])
    finally:
        session.close()


def render():
    st.title("❓ Preguntas trending")
    st.caption(
        "Preguntas reales detectadas en Reddit, Telegram y otros canales. "
        "Cada pregunta repetida es una idea de feature o app potencial."
    )

    days = st.session_state.get("lookback_days", 30)
    df = _load(days)
    if df.empty:
        st.info("Sin preguntas en este período. Corré los scrapers de Reddit y Telegram.")
        return

    # Filtros
    c1, c2, c3, c4 = st.columns(4)
    cats = c1.multiselect("Categoría", df["category"].dropna().unique())
    intents = c2.multiselect("Tipo de pregunta", df["intent"].dropna().unique())
    sources = c3.multiselect("Fuente", df["source"].dropna().unique())
    min_seen = c4.number_input("Mín. veces vista", 1, 100, 1)

    f = df.copy()
    if cats:    f = f[f["category"].isin(cats)]
    if intents: f = f[f["intent"].isin(intents)]
    if sources: f = f[f["source"].isin(sources)]
    f = f[f["times_seen"] >= min_seen]

    st.write(f"**{len(f)}** preguntas")

    # Distribución por intent
    if "intent" in f.columns and not f["intent"].dropna().empty:
        col_a, col_b = st.columns(2)
        with col_a:
            by_intent = f["intent"].value_counts().reset_index()
            by_intent.columns = ["intent", "count"]
            st.plotly_chart(
                px.pie(by_intent, names="intent", values="count",
                       title="Distribución por tipo"),
                use_container_width=True,
            )
        with col_b:
            by_cat = f["category"].fillna("sin").value_counts().head(10).reset_index()
            by_cat.columns = ["categoria", "count"]
            st.plotly_chart(
                px.bar(by_cat, x="categoria", y="count",
                       title="Top categorías"),
                use_container_width=True,
            )

    st.subheader("Lista")
    st.dataframe(
        f.sort_values("times_seen", ascending=False),
        use_container_width=True,
        height=600,
        column_config={
            "url": st.column_config.LinkColumn("Fuente", width="small"),
            "question": st.column_config.TextColumn("Pregunta", width="large"),
            "times_seen": st.column_config.NumberColumn("Veces", width="small"),
        },
        hide_index=True,
    )

    st.download_button(
        "📥 Exportar CSV",
        f.to_csv(index=False).encode("utf-8"),
        file_name="preguntas.csv",
        mime="text/csv",
    )
