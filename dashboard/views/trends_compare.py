"""Vista: Comparativa temporal entre períodos."""
import streamlit as st
import pandas as pd
import plotly.express as px

from insights.trend_analysis import TrendAnalyzer


def render():
    st.title("📈 Comparativa temporal")
    st.caption(
        "Compara qué creció, qué bajó, qué es nuevo y qué desapareció "
        "entre dos períodos consecutivos."
    )

    a = TrendAnalyzer()

    c1, c2, c3 = st.columns(3)
    period = c1.selectbox(
        "Período de comparación",
        [7, 14, 30, 60, 90],
        format_func=lambda x: f"Últimos {x} días vs {x} días previos",
    )
    dimension = c2.selectbox(
        "Dimensión",
        ["term", "category", "source"],
        format_func=lambda x: {"term": "Términos", "category": "Categorías",
                                "source": "Fuentes"}[x],
    )
    top_n = c3.number_input("Top N", 10, 200, 30)

    cat_filter = st.text_input(
        "Filtrar por categoría (opcional)",
        placeholder="ej: finanzas, tramites, trabajo",
    )

    cmp = a.compare_periods(
        period_days=period,
        dimension=dimension,
        top_n=top_n,
        category=cat_filter or None,
    )

    cur_s, cur_e = cmp["current_period"]
    prev_s, prev_e = cmp["previous_period"]
    st.markdown(
        f"**Período actual**: {cur_s.date()} → {cur_e.date()}  \n"
        f"**Período anterior**: {prev_s.date()} → {prev_e.date()}"
    )

    tab_rising, tab_falling, tab_new, tab_lost = st.tabs([
        f"📈 Subiendo ({len(cmp['rising'])})",
        f"📉 Bajando ({len(cmp['falling'])})",
        f"🆕 Nuevos ({len(cmp['new'])})",
        f"💀 Desaparecieron ({len(cmp['lost'])})",
    ])

    def _fmt_delta(p):
        if p == float("inf"):
            return "nuevo"
        return f"{p:+.0f}%"

    def _df_from(items):
        if not items:
            return pd.DataFrame()
        df = pd.DataFrame(items)
        df["delta"] = df["delta_pct"].apply(_fmt_delta)
        return df.rename(columns={"name": dimension})

    with tab_rising:
        df = _df_from(cmp["rising"])
        if df.empty:
            st.info("Sin items subiendo")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True, height=500)
            # Gráfico top 15
            top = df.head(15).copy()
            top["delta_pct_clip"] = top["delta_pct"].clip(upper=500)
            st.plotly_chart(
                px.bar(top, x=dimension, y="delta_pct_clip",
                       color="current",
                       title="Top 15 con mayor crecimiento (% capeado a 500%)",
                       labels={"delta_pct_clip": "% crecimiento"}),
                use_container_width=True,
            )

    with tab_falling:
        df = _df_from(cmp["falling"])
        if df.empty:
            st.info("Sin items bajando")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True, height=500)

    with tab_new:
        df = _df_from(cmp["new"])
        if df.empty:
            st.info("No aparecieron items nuevos")
        else:
            st.caption("Items que aparecieron por primera vez en el período actual.")
            st.dataframe(df[[dimension, "current"]], use_container_width=True,
                          hide_index=True, height=500)

    with tab_lost:
        df = _df_from(cmp["lost"])
        if df.empty:
            st.info("Ningún item desapareció")
        else:
            st.caption("Items que estaban presentes y dejaron de aparecer.")
            st.dataframe(df[[dimension, "previous"]], use_container_width=True,
                          hide_index=True, height=500)

    # ============================================================
    # Sección: serie temporal
    # ============================================================
    st.divider()
    st.subheader("Evolución diaria")

    days_chart = st.slider("Histórico (días)", 14, 180, 60)
    group_by = st.radio("Agrupar por", ["source", "category", "ninguno"], horizontal=True)
    group_param = group_by if group_by != "ninguno" else None

    series = a.daily_series(days=days_chart, group_by=group_param,
                              category=cat_filter or None)
    if series:
        df_s = pd.DataFrame(series)
        df_s["day"] = pd.to_datetime(df_s["day"])
        if group_param:
            fig = px.line(df_s, x="day", y="count", color=group_param, markers=False)
        else:
            fig = px.line(df_s, x="day", y="count", markers=True)
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos en este rango.")

    # ============================================================
    # Buscar evolución de un término
    # ============================================================
    st.divider()
    st.subheader("Evolución de un término específico")
    term = st.text_input("Término exacto", placeholder="ej: dolar blue, plazo fijo, sube")
    if term:
        history = a.term_history(term=term.lower(), days=days_chart)
        if not history:
            st.info("Sin histórico para ese término.")
        else:
            df_h = pd.DataFrame(history)
            df_h["day"] = pd.to_datetime(df_h["day"])
            st.plotly_chart(
                px.line(df_h, x="day", y="count", color="source", markers=True,
                        title=f"'{term}' en el tiempo"),
                use_container_width=True,
            )
