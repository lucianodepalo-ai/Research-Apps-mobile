"""
Argentina Insights Dashboard.
Ejecutar: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard.views import (
    overview, opportunities, niches, questions,
    competitors, pain_points, terms_explorer,
    monitoring, alerts_view, trends_compare,
)


st.set_page_config(
    page_title="Argentina Insights — Builder Dashboard",
    page_icon="🇦🇷",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    .stMetric {
        background: #0e1117;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #1f2937;
    }
    .opportunity-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid #334155;
        margin-bottom: 1rem;
    }
    .score-high { color: #10b981; font-weight: bold; }
    .score-mid { color: #f59e0b; font-weight: bold; }
    .score-low { color: #ef4444; font-weight: bold; }
    h1 { font-size: 2rem !important; }
    h2 { font-size: 1.4rem !important; margin-top: 1.5rem !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🇦🇷 Insights")
    st.caption("Detección de oportunidades")

    view = st.radio(
        "Vista",
        [
            "🎯 Oportunidades de negocio",
            "🔔 Alertas",
            "📈 Comparativa temporal",
            "📊 Resumen general",
            "🧩 Nichos por categoría",
            "❓ Preguntas trending",
            "📱 Apps competidoras",
            "💢 Reviews & dolores",
            "🔍 Explorador de términos",
            "⚙️ Monitoreo & runs",
        ],
        index=0,
    )

    st.divider()
    st.session_state["lookback_days"] = st.slider(
        "Período de análisis (días)", 1, 90, 30
    )

    st.divider()
    st.caption(
        "💡 Empezá por **Oportunidades** y revisá **Alertas** para enterarte "
        "rápido de cambios. **Comparativa** muestra qué creció vs el período previo."
    )


router = {
    "🎯": opportunities,
    "🔔": alerts_view,
    "📈": trends_compare,
    "📊": overview,
    "🧩": niches,
    "❓": questions,
    "📱": competitors,
    "💢": pain_points,
    "🔍": terms_explorer,
    "⚙️": monitoring,
}

prefix = view.split()[0]
module = router.get(prefix, overview)
module.render()
