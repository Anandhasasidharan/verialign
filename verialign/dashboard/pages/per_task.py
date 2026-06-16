import streamlit as st
import pandas as pd


def classify_task(user_content: str) -> str:
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

    user_lower = user_content.lower()
    for task, kws in keywords.items():
        if any(kw in user_lower for kw in kws):
            return task
    return "general"


def render(df: pd.DataFrame):
    st.header("📋 Per Task Metrics")

    if df.empty:
        st.info("No traces found.")
        return

    def extract_task(row):
        import json

        try:
            req = json.loads(row["request_json"])
            messages = req.get("messages", [])
            user_content = ""
            for msg in messages:
                if msg.get("role") == "user":
                    user_content = str(msg.get("content", ""))
                    break
            return classify_task(user_content)
        except Exception:
            return "unknown"

    df["task"] = df.apply(extract_task, axis=1)

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

    st.divider()

    st.subheader("Task Distribution")
    st.bar_chart(task_stats.set_index("task")["requests"])
