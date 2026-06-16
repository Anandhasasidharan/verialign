import streamlit as st
from datetime import date, timedelta


def render_date_range_filter(key: str = "date_range") -> tuple:
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=date.today() - timedelta(days=30),
            key=f"{key}_start",
        )
    with col2:
        end_date = st.date_input(
            "End Date",
            value=date.today(),
            key=f"{key}_end",
        )
    return start_date, end_date


def render_model_filter(
    models: list, key: str = "model_filter", default: str = "All"
) -> str:
    options = ["All"] + sorted(models)
    return st.selectbox("Model", options, key=key)


def render_status_filter(key: str = "status_filter") -> list:
    statuses = ["supported", "unsupported", "unclear", "partially_supported"]
    return st.multiselect("Claim Status", statuses, default=statuses, key=key)


def render_priority_filter(key: str = "priority_filter") -> list:
    priorities = ["high", "medium", "low"]
    return st.multiselect("Priority", priorities, default=priorities, key=key)


def render_task_filter(
    tasks: list, key: str = "task_filter", default: str = "All"
) -> str:
    options = ["All"] + sorted(tasks)
    return st.selectbox("Task Category", options, key=key)


def render_limit_slider(
    key: str = "limit",
    min_val: int = 10,
    max_val: int = 500,
    default: int = 100,
    step: int = 10,
) -> int:
    return st.slider("Limit", min_val, max_val, default, step, key=key)
