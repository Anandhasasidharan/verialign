import streamlit as st
import pandas as pd
import json


def render(df: pd.DataFrame):
    st.header("🔍 Trace Detail")

    if df.empty:
        st.info("No traces found.")
        return

    trace_ids = df["id"].tolist()
    selected_id = st.selectbox("Select Trace ID", trace_ids, key="trace_detail_select")

    trace = df[df["id"] == selected_id].iloc[0]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Request")
        st.json(json.loads(trace["request_json"]))

    with col2:
        st.subheader("Response")
        st.json(json.loads(trace["response_json"]))

    st.divider()
    st.subheader("Verification")
    verification = json.loads(trace["verification_json"])
    st.json(verification)

    if verification.get("claims"):
        st.subheader("Claims")
        claims_df = pd.DataFrame(verification["claims"])
        if not claims_df.empty:
            display_cols = ["claim_id", "text", "status", "confidence", "sources"]
            available_cols = [c for c in display_cols if c in claims_df.columns]
            st.dataframe(claims_df[available_cols], use_container_width=True)

    if verification.get("contradictions"):
        st.subheader("Contradictions")
        for c in verification["contradictions"]:
            with st.expander(
                f"{c['type'].title()}: {c['claim_a'][:50]}... vs {c['claim_b'][:50]}..."
            ):
                st.write(f"**Claim A:** {c['claim_a']}")
                st.write(f"**Claim B:** {c['claim_b']}")
                st.write(f"**Type:** {c['type']}")
                st.write(f"**Confidence:** {c['confidence']}")

    if verification.get("checklist"):
        st.subheader("Verification Checklist")
        for item in verification["checklist"]:
            priority_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                item.get("priority", ""), "⚪"
            )
            st.markdown(
                f"{priority_color} **{item['category']}**: {item['description']}"
            )
