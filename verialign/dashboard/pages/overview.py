import streamlit as st
import pandas as pd
from verialign.dashboard.components.charts import render_status_pie


def render(df: pd.DataFrame):
    st.header("📊 Overview")

    if df.empty:
        st.info(
            "No traces found. Make some requests through VeriAlign to see data here."
        )
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Requests", len(df))

    with col2:
        total_claims = df.get("total_claims", pd.Series([0])).sum()
        st.metric("Total Claims", int(total_claims))

    with col3:
        supported = df.get("supported", pd.Series([0])).sum()
        st.metric("Supported", int(supported))

    with col4:
        unsupported = df.get("unsupported", pd.Series([0])).sum()
        st.metric("Unsupported", int(unsupported))

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Claims by Status")
        status_cols = ["supported", "unsupported", "unclear", "partially_supported"]
        status_data = {
            col: int(df.get(col, pd.Series([0])).sum())
            for col in status_cols
            if col in df.columns
        }
        if status_data:
            render_status_pie(status_data)

    with col2:
        st.subheader("Requests by Model")
        if "model" in df.columns:
            model_counts = df["model"].value_counts().reset_index()
            model_counts.columns = ["model", "count"]
            st.bar_chart(model_counts.set_index("model"))
