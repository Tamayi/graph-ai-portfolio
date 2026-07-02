"""Streamlit front end for the BVD/MVE sitrep RAG app.

This is a functional reference scaffold wiring the backend modules together:
a chat assistant that can plot charts, a data-quality module (single report and
two-report comparison), and a gaps/challenges analysis module. It is intentionally
plain. The polished UI is generated separately with Claude Design and dropped in
on top of these same backend calls.

Run:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import data_quality, topics  # noqa: E402
from src.chat import SitrepChat  # noqa: E402
from src.i18n import t  # noqa: E402
from src.retriever import load_manifest  # noqa: E402

st.set_page_config(page_title="SitRep RAG", layout="wide")


def render_chart(spec: dict):
    """Render a plot_chart tool spec with Plotly."""
    x = spec.get("x", [])
    rows = []
    for s in spec.get("series", []):
        for xi, yi in zip(x, s.get("y", []), strict=False):
            rows.append({"x": xi, "y": yi, "series": s.get("name", "")})
    df = pd.DataFrame(rows)
    if df.empty:
        return
    ct = spec.get("chart_type", "line")
    title = spec.get("title", "")
    if ct == "bar":
        fig = px.bar(df, x="x", y="y", color="series", title=title, barmode="group")
    elif ct == "pie":
        fig = px.pie(df, names="x", values="y", title=title)
    else:
        fig = px.line(df, x="x", y="y", color="series", markers=True, title=title)
    fig.update_layout(xaxis_title=spec.get("x_label", ""),
                      yaxis_title=spec.get("y_label", ""))
    st.plotly_chart(fig, use_container_width=True)


# --- Sidebar ---------------------------------------------------------------
lang = st.sidebar.selectbox("Langue / Language / Idioma",
                            config.SUPPORTED_LANGUAGES, index=0)
st.sidebar.title(t(lang, "app_title"))
page = st.sidebar.radio("", [t(lang, "nav_chat"), t(lang, "nav_quality"),
                             t(lang, "nav_topics")])

manifest = load_manifest()
report_numbers = sorted(int(r["sitrep_number"]) for r in manifest) if manifest else []

if not report_numbers:
    st.warning(t(lang, "no_data"))

# --- Chat ------------------------------------------------------------------
if page == t(lang, "nav_chat"):
    st.header(t(lang, "nav_chat"))
    if "chat" not in st.session_state or st.session_state.get("lang") != lang:
        st.session_state.chat = SitrepChat(language=lang)
        st.session_state.messages = []
        st.session_state.lang = lang

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            for spec in m.get("charts", []):
                render_chart(spec)

    if prompt := st.chat_input(t(lang, "ask_placeholder")):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("..."):
                result = st.session_state.chat.ask(prompt)
            st.markdown(result["text"])
            for spec in result["charts"]:
                render_chart(spec)
            with st.expander(t(lang, "sources")):
                for s in result["sources"]:
                    st.caption(f"SitRep N°{s['sitrep_number']} - {s['report_date']} - p.{s['page']}")
        st.session_state.messages.append({
            "role": "assistant", "content": result["text"],
            "charts": result["charts"]})

# --- Data quality ----------------------------------------------------------
elif page == t(lang, "nav_quality"):
    st.header(t(lang, "nav_quality"))
    tab1, tab2 = st.tabs([t(lang, "single_assess"), t(lang, "compare_assess")])
    with tab1:
        n = st.selectbox(t(lang, "select_report"), report_numbers, key="dq_single")
        if st.button(t(lang, "run"), key="dq_single_btn") and n:
            with st.spinner("..."):
                st.markdown(data_quality.assess_single(int(n), lang))
    with tab2:
        c1, c2 = st.columns(2)
        a = c1.selectbox(t(lang, "select_report_a"), report_numbers, key="dq_a")
        b = c2.selectbox(t(lang, "select_report_b"), report_numbers,
                         index=min(1, len(report_numbers) - 1), key="dq_b")
        if st.button(t(lang, "run"), key="dq_cmp_btn") and a and b:
            with st.spinner("..."):
                st.markdown(data_quality.compare(int(a), int(b), lang))

# --- Topics ----------------------------------------------------------------
elif page == t(lang, "nav_topics"):
    st.header(t(lang, "nav_topics"))
    cache = topics.cache_path()
    if st.button(t(lang, "extract_topics")):
        with st.spinner("..."):
            rows = topics.run_and_cache(lang)
    else:
        import json
        rows = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []

    if rows:
        df = pd.DataFrame(rows)
        counts = df.groupby("theme").size().reset_index(name="reports")
        st.plotly_chart(px.bar(counts.sort_values("reports"), x="reports",
                               y="theme", orientation="h",
                               title=t(lang, "nav_topics")),
                        use_container_width=True)
        st.markdown(topics.synthesise(rows, lang))
        st.dataframe(df, use_container_width=True)
