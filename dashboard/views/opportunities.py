"""
Vista: Oportunidades de negocio.

La pregunta que responde: "¿Qué app debería construir hoy?"

Diseño:
- Tarjetas con TOP oportunidades (tesis, evidencia, scores, MVP, monetización)
- Sección de "Apps a reemplazar" (alta demanda, mala calidad)
- Sección de "Preguntas sin responder por ninguna app"
"""
import streamlit as st
import pandas as pd
import plotly.express as px

from insights.opportunity_generator import OpportunityGenerator


def render():
    st.title("🎯 Oportunidades de negocio")
    st.caption(
        "Hipótesis de productos detectadas automáticamente cruzando demanda real "
        "(búsquedas, preguntas) con oferta actual (apps existentes y sus reviews)."
    )

    days = st.session_state.get("lookback_days", 30)
    gen = OpportunityGenerator(lookback_days=days)

    tab1, tab2, tab3 = st.tabs([
        "🏆 Top oportunidades por nicho",
        "🔄 Apps para reemplazar",
        "❓ Preguntas sin app que las resuelva",
    ])

    # ============================================================
    # TAB 1: Top oportunidades
    # ============================================================
    with tab1:
        opps = gen.top_opportunities(limit=15)
        if not opps:
            st.warning(
                "Aún no hay oportunidades calculadas. Corré:  \n"
                "`python run_all.py --tier 1,2 --analyze`"
            )
            return

        st.subheader(f"Top {len(opps)} oportunidades")

        # Filtros
        col_f1, col_f2, col_f3 = st.columns(3)
        cats = sorted(set(o["category"] for o in opps))
        sel_cats = col_f1.multiselect("Categoría", cats, default=cats)
        max_complexity = col_f2.slider("Complejidad máxima", 1, 5, 3,
                                        help="1=muy simple, 5=muy compleja. "
                                             "Empezá por las simples para ganar tracción.")
        min_score = col_f3.slider("Score mínimo", -100, 100, 0)

        filtered = [
            o for o in opps
            if o["category"] in sel_cats
            and o["complexity"] <= max_complexity
            and o["final_score"] >= min_score
        ]

        st.write(f"**{len(filtered)}** oportunidades cumplen tus filtros")

        # Renderizar tarjetas
        for opp in filtered:
            _render_opportunity_card(opp)

        # Export
        st.divider()
        if filtered:
            df = pd.DataFrame([
                {
                    "categoria": o["category"],
                    "score_final": o["final_score"],
                    "demanda": o["demand_score"],
                    "competencia": o["competition_score"],
                    "complejidad": o["complexity_label"],
                    "señales": o["signals_count"],
                    "competidores": o["competitors_count"],
                    "rating_promedio_competidores": o["avg_competitor_rating"],
                    "tesis": o["tesis"],
                    "top_terminos": ", ".join(o["top_terms"][:5]),
                    "mvp_features": " | ".join(o["mvp_features"]),
                    "monetizacion": " | ".join(o["monetization"]),
                }
                for o in filtered
            ])
            st.download_button(
                "📥 Exportar oportunidades a CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name=f"oportunidades_{days}d.csv",
                mime="text/csv",
            )

    # ============================================================
    # TAB 2: Apps a reemplazar
    # ============================================================
    with tab2:
        st.subheader("Apps con muchas instalaciones pero rating bajo")
        st.caption(
            "Estas apps **ya validaron la demanda** (la gente las descarga) "
            "pero los usuarios no están contentos. Es la oportunidad más clara: "
            "construir una mejor versión y tomar su mercado."
        )

        col1, col2 = st.columns(2)
        min_inst = col1.number_input(
            "Mínimo de instalaciones", 1000, 100_000_000, 50_000, step=10_000
        )
        max_rating = col2.slider("Rating máximo", 1.0, 5.0, 3.8, 0.1)

        apps = gen.underserved_apps(min_installs=min_inst, max_rating=max_rating)
        st.write(f"**{len(apps)} apps** cumplen criterios")

        if apps:
            df = pd.DataFrame(apps)

            # Plot
            fig = px.scatter(
                df,
                x="installs_num",
                y="rating",
                log_x=True,
                size="ratings_count",
                color="category",
                hover_data=["title", "developer", "discovered_via"],
                title="Cuanto más a la derecha y más abajo, mayor oportunidad",
                labels={"installs_num": "Instalaciones (log)", "rating": "Rating"},
            )
            fig.add_hline(y=4, line_dash="dash", line_color="gray",
                           annotation_text="Línea de calidad aceptable")
            st.plotly_chart(fig, use_container_width=True)

            # Tabla
            st.dataframe(
                df[["title", "developer", "category", "rating", "installs",
                    "ratings_count", "discovered_via"]]
                .rename(columns={
                    "title": "App",
                    "developer": "Desarrollador",
                    "category": "Categoría",
                    "rating": "Rating",
                    "installs": "Instalaciones",
                    "ratings_count": "# ratings",
                    "discovered_via": "Buscada vía",
                }),
                use_container_width=True,
                height=500,
            )

            st.download_button(
                "📥 Exportar apps a reemplazar (CSV)",
                df.to_csv(index=False).encode("utf-8"),
                file_name=f"apps_a_reemplazar.csv",
                mime="text/csv",
            )
        else:
            st.info("Sin apps con esos criterios. Probá ajustar los filtros.")

    # ============================================================
    # TAB 3: Preguntas no resueltas
    # ============================================================
    with tab3:
        st.subheader("Preguntas que ninguna app cubre bien")
        st.caption(
            "Preguntas que se repiten mucho y cuya intención NO aparece "
            "en descripciones de apps existentes. Cada una es una idea de feature/app."
        )

        unaddressed = gen.trending_questions_unaddressed(limit=50)
        if not unaddressed:
            st.info("Sin preguntas detectadas. Necesitás más datos de Reddit/Telegram.")
            return

        df = pd.DataFrame(unaddressed)
        df["coverage"] = (df["coverage"] * 100).round(0).astype(str) + "%"

        st.dataframe(
            df.rename(columns={
                "question": "Pregunta",
                "category": "Categoría",
                "intent": "Tipo",
                "times_seen": "Veces vista",
                "upvotes": "Likes",
                "coverage": "Cobertura en apps",
            }),
            use_container_width=True,
            height=500,
            column_config={
                "url": st.column_config.LinkColumn("Fuente"),
            }
        )

        st.download_button(
            "📥 Exportar preguntas no cubiertas",
            df.to_csv(index=False).encode("utf-8"),
            file_name="preguntas_no_cubiertas.csv",
            mime="text/csv",
        )


def _render_opportunity_card(opp):
    """Tarjeta visual para una oportunidad."""
    score = opp["final_score"]
    if score >= 30:
        score_class, score_emoji = "score-high", "🔥"
    elif score >= 0:
        score_class, score_emoji = "score-mid", "⚡"
    else:
        score_class, score_emoji = "score-low", "❄️"

    with st.container():
        st.markdown(
            f"""
            <div class="opportunity-card">
                <h3 style="margin-top:0">
                    {score_emoji} {opp["category"].title()} —
                    <span class="{score_class}">Score {score}</span>
                </h3>
                <p style="font-size:1.05em; margin: 0.5rem 0">{opp["tesis"]}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Demanda", f"{opp['demand_score']:.0f}",
                   help="Volumen de señales detectadas")
        c2.metric("Competencia", f"{opp['competition_score']:.0f}",
                   help="Más bajo = mejor oportunidad")
        c3.metric("Complejidad", opp["complexity_label"],
                   help="Estimación de esfuerzo de desarrollo")
        c4.metric("Apps existentes", opp["competitors_count"])

        with st.expander("📋 Detalle: tesis, MVP y monetización"):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**🎯 Términos top que la gente busca:**")
                for t in opp["top_terms"][:8]:
                    st.markdown(f"- `{t}`")

                st.markdown("**🛠️ Features sugeridos para MVP:**")
                for f in opp["mvp_features"]:
                    st.markdown(f"- {f}")

            with col_b:
                st.markdown("**💰 Modelos de monetización viables:**")
                for m in opp["monetization"]:
                    st.markdown(f"- {m}")

                st.markdown("**📊 Métricas clave:**")
                st.markdown(f"- Señales totales: **{opp['signals_count']}**")
                st.markdown(
                    f"- Apps competidoras: **{opp['competitors_count']}**"
                )
                if opp["avg_competitor_rating"]:
                    rating = opp["avg_competitor_rating"]
                    quality = ("🟢 Alta" if rating >= 4.2
                                else "🟡 Media" if rating >= 3.5
                                else "🔴 Baja (oportunidad)")
                    st.markdown(
                        f"- Calidad de competencia: **{rating:.1f}/5** ({quality})"
                    )
