import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def render_status_pie(status_data: dict, title: str = "Claim Status Distribution"):
    if not status_data or sum(status_data.values()) == 0:
        st.info("No data available")
        return

    fig = px.pie(
        values=list(status_data.values()),
        names=list(status_data.keys()),
        title=title,
        color_discrete_map={
            "supported": "#2ecc71",
            "unsupported": "#e74c3c",
            "unclear": "#f39c12",
            "partially_supported": "#3498db",
        },
    )
    st.plotly_chart(fig, use_container_width=True)


def render_line_chart(
    df: pd.DataFrame, x: str, y: str, title: str = "", color: str = None
):
    if df.empty:
        st.info("No data available")
        return

    fig = px.line(df, x=x, y=y, color=color, title=title)
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def render_bar_chart(
    df: pd.DataFrame, x: str, y: str, title: str = "", color: str = None
):
    if df.empty:
        st.info("No data available")
        return

    fig = px.bar(df, x=x, y=y, color=color, title=title)
    st.plotly_chart(fig, use_container_width=True)


def render_heatmap(df: pd.DataFrame, x: str, y: str, z: str, title: str = ""):
    if df.empty:
        st.info("No data available")
        return

    fig = px.density_heatmap(df, x=x, y=y, z=z, title=title)
    st.plotly_chart(fig, use_container_width=True)


def render_gauge(
    value: float,
    title: str = "",
    min_val: float = 0,
    max_val: float = 1,
    threshold: float = 0.5,
):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            title={"text": title},
            gauge={
                "axis": {"range": [min_val, max_val]},
                "bar": {"color": "darkblue"},
                "steps": [
                    {"range": [min_val, threshold], "color": "lightgray"},
                    {"range": [threshold, max_val], "color": "lightgreen"},
                ],
                "threshold": {
                    "line": {"color": "red", "width": 4},
                    "thickness": 0.75,
                    "value": threshold,
                },
            },
        )
    )
    st.plotly_chart(fig, use_container_width=True)
