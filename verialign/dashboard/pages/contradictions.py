import streamlit as st
import pandas as pd


def render(df: pd.DataFrame):
    st.header("⚠️ Contradictions")

    if df.empty:
        st.info("No traces found.")
        return

    all_contradictions = []
    for _, row in df.iterrows():
        import json

        try:
            v = json.loads(row["verification_json"])
            contradictions = v.get("contradictions", [])
            for c in contradictions:
                c["trace_id"] = row["id"]
                c["model"] = row["model"]
                c["created_at"] = row["created_at"]
                all_contradictions.append(c)
        except Exception:
            pass

    if not all_contradictions:
        st.info("No contradictions detected in loaded traces.")
        return

    contra_df = pd.DataFrame(all_contradictions)
    st.metric("Total Contradictions", len(contra_df))

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("By Type")
        if "type" in contra_df.columns:
            type_counts = contra_df["type"].value_counts().reset_index()
            type_counts.columns = ["type", "count"]
            st.bar_chart(type_counts.set_index("type"))

    with col2:
        st.subheader("By Model")
        if "model" in contra_df.columns:
            model_counts = contra_df["model"].value_counts().reset_index()
            model_counts.columns = ["model", "count"]
            st.bar_chart(model_counts.set_index("model"))

    st.divider()

    st.subheader("Recent Contradictions")
    display_cols = [
        "trace_id",
        "model",
        "created_at",
        "type",
        "confidence",
        "claim_a",
        "claim_b",
    ]
    available_cols = [c for c in display_cols if c in contra_df.columns]
    st.dataframe(contra_df[available_cols].head(50), use_container_width=True)
