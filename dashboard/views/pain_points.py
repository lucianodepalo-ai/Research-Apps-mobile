"""
Vista: Reviews & dolores reales.

Esta vista es CLAVE: las reviews 1-2 estrellas son el roadmap
de producto de tu próxima app.

Si Ollama corrió la extracción NLP, mostramos pain_points y feature_requests
estructurados. Si no, fallback a heurísticas en vivo.
"""
import re
from collections import Counter
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import desc

from database.models import AppReview, AppCompetitor, get_session
from insights.nlp.pain_extractor import (
    PainExtractor, aggregate_pain_points_by_category
)


@st.cache_data(ttl=60)
def _load_reviews(min_score: int, max_score: int, category: str = None):
    session = get_session()
    try:
        q = (
            session.query(AppReview, AppCompetitor.title,
                            AppCompetitor.category, AppCompetitor.app_id)
            .join(AppCompetitor, AppReview.app_id_fk == AppCompetitor.id)
            .filter(AppReview.score.between(min_score, max_score))
        )
        if category:
            q = q.filter(AppCompetitor.category == category)
        rows = q.order_by(desc(AppReview.thumbs_up)).limit(2000).all()
        return pd.DataFrame([{
            "review_id": r.id,
            "app": title,
            "category": cat,
            "app_id": app_id,
            "score": r.score,
            "content": r.content,
            "thumbs_up": r.thumbs_up,
            "review_date": r.review_date,
            "pain_points": r.pain_points or [],
            "feature_requests": r.feature_requests or [],
            "has_nlp": bool(r.pain_points or r.feature_requests),
        } for r, title, cat, app_id in rows])
    finally:
        session.close()


def render():
    st.title("💢 Reviews & dolores reales")
    st.caption(
        "Reviews 1-2 estrellas de apps competidoras. "
        "Cada queja es una feature que tu app puede hacer bien para diferenciarse."
    )

    # Acción para correr el extractor manual
    with st.expander("⚙️ Procesar reviews con NLP (Ollama)"):
        col_a, col_b = st.columns(2)
        limit = col_a.number_input("Cuántas procesar", 10, 5000, 200)
        force = col_b.checkbox("Reprocesar todas (no solo nuevas)")
        if st.button("🤖 Extraer pain points"):
            with st.spinner("Procesando con Ollama..."):
                n = PainExtractor().process_pending(limit=limit, force=force)
                st.success(f"{n} reviews procesadas")
                st.cache_data.clear()

    c1, c2 = st.columns(2)
    score_range = c1.slider("Rango de estrellas", 1, 5, (1, 2))
    cat = c2.selectbox(
        "Categoría",
        [""] + ["finanzas", "tramites", "trabajo", "compras",
                 "salud", "transporte", "general"],
    )

    df = _load_reviews(score_range[0], score_range[1], cat or None)
    if df.empty:
        st.info("Sin reviews con esos criterios.")
        return

    st.write(f"**{len(df)} reviews** entre {score_range[0]}-{score_range[1]} ⭐")

    # =========================================================
    # Pain points agregados (NLP)
    # =========================================================
    if cat:
        st.subheader(f"🧠 Pain points y feature requests en {cat}")
        agg = aggregate_pain_points_by_category(category=cat, days=90, top_n=15)

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("### 💢 Pain points más mencionados")
            if agg["pain_points"]:
                pdf = pd.DataFrame(agg["pain_points"])
                pdf["example_apps"] = pdf["example_apps"].apply(lambda l: ", ".join(l))
                st.dataframe(
                    pdf.rename(columns={
                        "text": "Pain point",
                        "mentions": "Menciones",
                        "apps_affected": "Apps afectadas",
                        "example_apps": "Ejemplos",
                    }),
                    use_container_width=True, hide_index=True, height=400,
                )
            else:
                st.info("Sin pain points procesados. Corré el extractor arriba.")

        with col_b:
            st.markdown("### 💡 Features que piden los usuarios")
            if agg["feature_requests"]:
                fdf = pd.DataFrame(agg["feature_requests"])
                fdf["example_apps"] = fdf["example_apps"].apply(lambda l: ", ".join(l))
                st.dataframe(
                    fdf.rename(columns={
                        "text": "Feature request",
                        "mentions": "Menciones",
                        "apps_affected": "Apps con esta queja",
                        "example_apps": "Ejemplos",
                    }),
                    use_container_width=True, hide_index=True, height=400,
                )
            else:
                st.info("Sin feature requests procesados.")

    # =========================================================
    # Top apps con quejas
    # =========================================================
    st.divider()
    st.subheader("Apps con más quejas")
    by_app = df.groupby("app").agg(
        quejas=("content", "count"),
        avg_likes=("thumbs_up", "mean"),
    ).sort_values("quejas", ascending=False).head(15).reset_index()
    fig = px.bar(by_app, x="app", y="quejas", color="avg_likes",
                  color_continuous_scale="Reds")
    fig.update_xaxes(tickangle=45)
    st.plotly_chart(fig, use_container_width=True)

    # =========================================================
    # Reviews top
    # =========================================================
    st.subheader("Top reviews por likes")

    nlp_count = df["has_nlp"].sum()
    if nlp_count > 0:
        st.caption(f"📊 {nlp_count}/{len(df)} reviews con análisis NLP")

    display = df.sort_values("thumbs_up", ascending=False).head(50)
    for _, row in display.iterrows():
        with st.expander(
            f"{'⭐' * row['score']}  ·  👍 {row['thumbs_up']}  ·  {row['app']}  "
            f"·  {(row['content'] or '')[:100]}…"
        ):
            st.write(row["content"])
            if row["pain_points"]:
                st.markdown("**Pain points detectados:**")
                for p in row["pain_points"]:
                    st.markdown(f"- {p}")
            if row["feature_requests"]:
                st.markdown("**Features pedidos:**")
                for f in row["feature_requests"]:
                    st.markdown(f"- {f}")
