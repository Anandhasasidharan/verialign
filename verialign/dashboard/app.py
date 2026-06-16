import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="VeriAlign Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = Path("./verialign.sqlite3")


@st.cache_data(ttl=30)
def load_traces(limit: int = 100):
    if not DB_PATH.exists():
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT id, created_at, model, request_json, response_json, verification_json
        FROM traces
        ORDER BY id DESC
        LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(limit,))
    conn.close()

    if df.empty:
        return df

    def parse_verification(row):
        import json

        try:
            v = json.loads(row["verification_json"])
            return v.get("summary", {})
        except Exception:
            return {}

    summaries = df.apply(parse_verification, axis=1, result_type="expand")
    if not summaries.empty:
        df = pd.concat([df, summaries], axis=1)

    return df


def render_sidebar():
    st.sidebar.title("🔍 VeriAlign")
    st.sidebar.caption("Verification Support Proxy for LLM Outputs")

    st.sidebar.divider()

    limit = st.sidebar.slider("Traces to load", 10, 500, 100, step=10)

    st.sidebar.divider()
    st.sidebar.markdown("**Navigation**")
    page = st.sidebar.radio(
        "Select page",
        [
            "Overview",
            "Per Model",
            "Per Task",
            "Drift",
            "Contradictions",
            "Trace Detail",
        ],
        label_visibility="collapsed",
    )

    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    return limit, page


def render_overview(df):
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
            st.bar_chart(status_data)

    with col2:
        st.subheader("Requests by Model")
        if "model" in df.columns:
            model_counts = df["model"].value_counts()
            st.bar_chart(model_counts)


def render_per_model(df):
    st.header("🤖 Per Model Metrics")

    if df.empty:
        st.info("No traces found.")
        return

    if "model" not in df.columns:
        st.warning("Model data not available.")
        return

    models = df["model"].unique()
    selected_model = st.selectbox("Select Model", ["All"] + list(models))

    filtered_df = df if selected_model == "All" else df[df["model"] == selected_model]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Requests", len(filtered_df))
    with col2:
        total_claims = filtered_df.get("total_claims", pd.Series([0])).sum()
        st.metric("Total Claims", int(total_claims))
    with col3:
        avg_conf = (
            filtered_df.get("confidence", pd.Series([0])).mean()
            if "confidence" in filtered_df.columns
            else 0
        )
        st.metric("Avg Confidence", f"{avg_conf:.2f}")

    st.subheader("Claim Status Distribution")
    status_cols = ["supported", "unsupported", "unclear", "partially_supported"]
    status_data = {
        col: int(filtered_df.get(col, pd.Series([0])).sum())
        for col in status_cols
        if col in filtered_df.columns
    }
    if status_data:
        st.bar_chart(status_data)

    st.subheader("Recent Traces")
    display_cols = ["id", "created_at", "model"]
    status_cols_present = [c for c in status_cols if c in filtered_df.columns]
    display_cols.extend(status_cols_present)
    st.dataframe(filtered_df[display_cols].head(20), use_container_width=True)


def render_per_task(df):
    st.header("📋 Per Task Metrics")

    if df.empty:
        st.info("No traces found.")
        return

    def classify_task(row):
        import json

        try:
            req = json.loads(row["request_json"])
            messages = req.get("messages", [])
            user_content = ""
            for msg in messages:
                if msg.get("role") == "user":
                    user_content = str(msg.get("content", "")).lower()
                    break

            keywords = {
                "coding": [
                    "code",
                    "function",
                    "class",
                    "api",
                    "bug",
                    "debug",
                    "implement",
                    "refactor",
                    "python",
                    "javascript",
                    "sql",
                ],
                "writing": [
                    "write",
                    "essay",
                    "article",
                    "blog",
                    "email",
                    "story",
                    "creative",
                    "copy",
                    "content",
                ],
                "analysis": [
                    "analyze",
                    "compare",
                    "evaluate",
                    "assess",
                    "review",
                    "critique",
                    "examine",
                ],
                "question_answering": [
                    "what",
                    "how",
                    "why",
                    "when",
                    "where",
                    "who",
                    "explain",
                    "define",
                    "describe",
                ],
                "summarization": ["summarize", "summary", "tldr", "brief", "condense"],
                "translation": ["translate", "translation", "language"],
            }

            for task, kws in keywords.items():
                if any(kw in user_content for kw in kws):
                    return task
            return "general"
        except Exception:
            return "unknown"

    df["task"] = df.apply(classify_task, axis=1)

    task_stats = (
        df.groupby("task")
        .agg(
            requests=("id", "count"),
            total_claims=("total_claims", "sum")
            if "total_claims" in df.columns
            else ("id", "count"),
            supported=("supported", "sum")
            if "supported" in df.columns
            else ("id", "count"),
            unsupported=("unsupported", "sum")
            if "unsupported" in df.columns
            else ("id", "count"),
            unclear=("unclear", "sum") if "unclear" in df.columns else ("id", "count"),
        )
        .reset_index()
    )

    st.dataframe(task_stats, use_container_width=True)


def render_drift(df):
    st.header("📈 Verification Drift Over Time")

    if df.empty:
        st.info("No traces found.")
        return

    df["date"] = pd.to_datetime(df["created_at"]).dt.date

    daily = (
        df.groupby("date")
        .agg(
            requests=("id", "count"),
            total_claims=("total_claims", "sum")
            if "total_claims" in df.columns
            else ("id", "count"),
            supported=("supported", "sum")
            if "supported" in df.columns
            else ("id", "count"),
        )
        .reset_index()
    )

    if len(daily) > 1:
        st.subheader("Requests per Day")
        st.line_chart(daily.set_index("date")["requests"])

        st.subheader("Supported Claims per Day")
        st.line_chart(daily.set_index("date")["supported"])

        if "total_claims" in daily.columns and daily["total_claims"].sum() > 0:
            daily["support_rate"] = daily["supported"] / daily["total_claims"].replace(
                0, 1
            )
            st.subheader("Support Rate Over Time")
            st.line_chart(daily.set_index("date")["support_rate"])
    else:
        st.info("Need more data over multiple days to show drift.")


def render_contradictions(df):
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

    if "type" in contra_df.columns:
        st.subheader("By Type")
        st.bar_chart(contra_df["type"].value_counts())

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


def render_trace_detail(df):
    st.header("🔍 Trace Detail")

    if df.empty:
        st.info("No traces found.")
        return

    trace_ids = df["id"].tolist()
    selected_id = st.selectbox("Select Trace ID", trace_ids)

    trace = df[df["id"] == selected_id].iloc[0]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Request")
        import json

        st.json(json.loads(trace["request_json"]))

    with col2:
        st.subheader("Response")
        st.json(json.loads(trace["response_json"]))

    st.divider()
    st.subheader("Verification")
    import json

    verification = json.loads(trace["verification_json"])

    st.json(verification)

    if verification.get("claims"):
        st.subheader("Claims")
        claims_df = pd.DataFrame(verification["claims"])
        if not claims_df.empty:
            st.dataframe(
                claims_df[["claim_id", "text", "status", "confidence"]],
                use_container_width=True,
            )

    if verification.get("contradictions"):
        st.subheader("Contradictions")
        st.json(verification["contradictions"])

    if verification.get("checklist"):
        st.subheader("Verification Checklist")
        for item in verification["checklist"]:
            priority_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                item.get("priority", ""), "⚪"
            )
            st.markdown(
                f"{priority_color} **{item['category']}**: {item['description']}"
            )


def main():
    limit, page = render_sidebar()
    df = load_traces(limit)

    if page == "Overview":
        render_overview(df)
    elif page == "Per Model":
        render_per_model(df)
    elif page == "Per Task":
        render_per_task(df)
    elif page == "Drift":
        render_drift(df)
    elif page == "Contradictions":
        render_contradictions(df)
    elif page == "Trace Detail":
        render_trace_detail(df)


if __name__ == "__main__":
    main()
