"""Vista: Nichos por categoría con análisis de cuadrante demanda/competencia."""
import streamlit as st
import pandas as pd
import plotly.express as px

from insights.opportunity_generator import OpportunityGenerator


def render():
    st.title("🧩 Nichos por categoría")
    st.caption(
        "Cada punto es una categoría. El cuadrante de arriba a la izquierda "
        "(alta demanda, baja competencia) es donde están las oportunidades."
    )

    days = st.session_state.get("lookback_days", 30)
    gen = OpportunityGenerator(lookback_days=days)
    quads = gen.category_quadrants()

    if not quads:
        st.warning("Sin datos. Corré `python run_all.py --tier 1,2`.")
        return

    df = pd.DataFrame(quads)

    # Métrica de oportunidad simple para colorear
    df["oportunidad"] = (
        df["demand_signals"] / (df["competition_apps"].clip(lower=1) * 5)
        - df["competition_avg_rating"]
    ).round(2)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Mapa de oportunidad")
        fig = px.scatter(
            df,
            x="competition_apps",
            y="demand_signals",
            size="demand_unique_terms",
            color="oportunidad",
            color_continuous_scale="RdYlGn",
            text="category",
            hover_data={
                "competition_avg_rating": ":.2f",
                "competition_total_installs": ":,",
                "demand_unique_terms": True,
            },
            labels={
                "competition_apps": "# apps competidoras",
                "demand_signals": "Señales de demanda",
            },
        )
        fig.update_traces(textposition="top center")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Ranking")
        ranked = df.sort_values("oportunidad", ascending=False)[
            ["category", "demand_signals", "competition_apps",
             "competition_avg_rating", "oportunidad"]
        ].rename(columns={
            "category": "Categoría",
            "demand_signals": "Demanda",
            "competition_apps": "Apps",
            "competition_avg_rating": "Rating prom.",
            "oportunidad": "Score",
        })
        st.dataframe(ranked, use_container_width=True, height=500, hide_index=True)

    st.divider()
    st.subheader("Tabla completa")
    st.dataframe(df.sort_values("oportunidad", ascending=False),
                 use_container_width=True, hide_index=True)
