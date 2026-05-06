"""Vista: Apps competidoras del Play Store con análisis de mercado."""
import streamlit as st
import pandas as pd
import plotly.express as px

from database.models import AppCompetitor, get_session


@st.cache_data(ttl=60)
def _load():
    session = get_session()
    try:
        rows = session.query(AppCompetitor).all()
        return pd.DataFrame([{
            "id": r.id,
            "app_id": r.app_id,
            "title": r.title,
            "developer": r.developer,
            "category": r.category,
            "rating": r.score,
            "ratings_count": r.ratings_count,
            "reviews_count": r.reviews_count,
            "installs": r.installs,
            "installs_num": r.installs_num,
            "free": r.free,
            "discovered_via": r.discovered_via_query,
            "rank": r.rank_in_query,
            "summary": r.summary,
        } for r in rows])
    finally:
        session.close()


def render():
    st.title("📱 Apps competidoras del Play Store")
    df = _load()
    if df.empty:
        st.info("Sin apps. Corré PlayStoreScraper.")
        return

    c1, c2, c3 = st.columns(3)
    cats = c1.multiselect("Categoría", df["category"].dropna().unique())
    via = c2.multiselect("Buscada por query", df["discovered_via"].dropna().unique())
    only_free = c3.checkbox("Solo gratis", value=True)

    f = df.copy()
    if cats: f = f[f["category"].isin(cats)]
    if via:  f = f[f["discovered_via"].isin(via)]
    if only_free: f = f[f["free"] == True]

    st.write(f"**{len(f)}** apps")

    # Métricas clave
    if not f.empty:
        avg_rating = f["rating"].mean()
        total_inst = f["installs_num"].sum()
        weak = len(f[f["rating"] < 4])
        c1, c2, c3 = st.columns(3)
        c1.metric("Rating promedio", f"{avg_rating:.2f}")
        c2.metric("Instalaciones totales", f"{int(total_inst):,}")
        c3.metric("Apps con rating < 4", weak,
                   help="Oportunidades de reemplazo")

    # Scatter
    plotable = f.dropna(subset=["rating", "installs_num"])
    if not plotable.empty:
        st.subheader("Mapa de competencia")
        fig = px.scatter(
            plotable,
            x="installs_num", y="rating",
            log_x=True,
            size="ratings_count",
            color="category",
            hover_data=["title", "developer", "discovered_via"],
        )
        fig.add_hline(y=4, line_dash="dash", line_color="orange",
                       annotation_text="Línea de calidad")
        st.plotly_chart(fig, use_container_width=True)

    # Tabla
    display_cols = ["title", "developer", "category", "rating",
                     "installs", "ratings_count", "discovered_via"]
    st.dataframe(
        f[display_cols].rename(columns={
            "title": "App", "developer": "Dev", "category": "Cat",
            "rating": "⭐", "installs": "Installs",
            "ratings_count": "# Ratings", "discovered_via": "Buscada por",
        }).sort_values("# Ratings", ascending=False),
        use_container_width=True,
        height=500,
        hide_index=True,
    )

    st.download_button(
        "📥 Exportar CSV",
        f.to_csv(index=False).encode("utf-8"),
        file_name="apps_competidoras.csv",
        mime="text/csv",
    )
