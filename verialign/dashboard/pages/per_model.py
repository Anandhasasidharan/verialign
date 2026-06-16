import streamlit as st
import pandas as pd
from verialign.dashboard.components.charts import render_status_pie
from verialign.dashboard.components.filters import render_model_filter


def render(df: pd.DataFrame):
    st.header("🤖 Per Model Metrics")

    if df.empty:
        st.info("No traces found.")
        return

    if "model" not in df.columns:
        st.warning("Model data not available.")
        return

    models = df["model"].unique().tolist()
    selected_model = render_model_filter(models, key="per_model")

    filtered_df = df if selected_model == "All" else df[df["model"] == selected_model]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Requests", len(filtered_df))
    with col2:
        total_claims = filtered_df.get("total_claims", pd.Series([0])).sum()
        st.metric("Total Claims", int(total_claims))
    with col3:
        if "confidence" in filtered_df.columns:
            avg_conf = filtered_df["confidence"].mean()
        elif (
            "supported" in filtered_df.columns and "total_claims" in filtered_df.columns
        ):
            avg_conf = (
                filtered_df["supported"].sum()
                / filtered_df["total_claims"].replace(0, 1).sum()
            )
        else:
            avg_conf = 0
        st.metric("Avg Confidence", f"{avg_conf:.2f}")

    st.divider()

    st.subheader("Claim Status Distribution")
    status_cols = ["supported", "unsupported", "unclear", "partially_supported"]
    status_data = {
        col: int(filtered_df.get(col, pd.Series([0])).sum())
        for col in status_cols
        if col in filtered_df.columns
    }
    if status_data:
        render_status_pie(status_data, f"Status Distribution - {selected_model}")

    st.subheader("Recent Traces")
    display_cols = ["id", "created_at", "model"]
    status_cols_present = [c for c in status_cols if c in filtered_df.columns]
    display_cols.extend(status_cols_present)
    st.dataframe(filtered_df[display_cols].head(20), use_container_width=True)
