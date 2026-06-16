import streamlit as st
import pandas as pd


def render(df: pd.DataFrame):
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
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Requests per Day")
            st.line_chart(daily.set_index("date")["requests"])

            st.subheader("Total Claims per Day")
            st.line_chart(daily.set_index("date")["total_claims"])

        with col2:
            st.subheader("Supported Claims per Day")
            st.line_chart(daily.set_index("date")["supported"])

            if "total_claims" in daily.columns and daily["total_claims"].sum() > 0:
                daily["support_rate"] = daily["supported"] / daily[
                    "total_claims"
                ].replace(0, 1)
                st.subheader("Support Rate Over Time")
                st.line_chart(daily.set_index("date")["support_rate"])
    else:
        st.info("Need more data over multiple days to show drift trends.")

    st.divider()

    st.subheader("Daily Summary")
    st.dataframe(daily.sort_values("date", ascending=False), use_container_width=True)
