import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from .db import get_engine


st.set_page_config(page_title="Sidequests Analytics", layout="wide")
st.title("Sidequests · BQ Dashboard")
st.caption("Shared Sprint 2 and Sprint 3 analytics results from the Sidequests database")

engine = get_engine()

rows = pd.read_sql(
    text(
        """
        select distinct on (bq_key)
            bq_key,
            computed_at,
            payload
        from analytics.bq_results
        order by bq_key, computed_at desc
        """
    ),
    engine,
)

if rows.empty:
    st.info("No BQ results have been computed yet.")
else:
    for _, row in rows.iterrows():
        st.subheader(row["bq_key"])
        st.caption(f"Computed at {row['computed_at']}")
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        data = payload.get("rows", [])
        frame = pd.DataFrame(data)

        if row["bq_key"] == "BQ1":
            st.caption(
                "BQ1 · Which module fails most often after returning to the app "
                "after >10 min with an active Nearby quest?"
            )
            if frame.empty:
                st.info("No resume after a long background period has been recorded yet.")
            elif {"module", "failure_rate_pct", "app_version"}.issubset(frame.columns):
                latest = frame[frame["app_version"] == frame["app_version"].max()].copy()
                latest["Failure rate (%)"] = pd.to_numeric(latest["failure_rate_pct"], errors="coerce")
                st.bar_chart(latest.set_index("module")[["Failure rate (%)"]])
                st.caption(
                    "Failure rate = resumes with at least one failure of the module (while online) "
                    "/ resumes after >10 min with a Nearby quest, latest app version, last 30 days. "
                    "Offline failures are listed separately in the table."
                )
            else:
                st.warning("BQ1 is missing the fields needed for the failure chart.")

        if row["bq_key"] == "BQ9":
            st.caption("BQ9 · Which quest categories are completed most often?")
            if frame.empty:
                st.info("No category activity has been recorded yet.")
            elif {"category", "completion_rate_pct", "accepted_count", "completed_count"}.issubset(frame.columns):
                category_rates = frame[
                    ["category", "completion_rate_pct", "accepted_count", "completed_count"]
                ].copy()
                category_rates["Completion rate (%)"] = pd.to_numeric(
                    category_rates["completion_rate_pct"], errors="coerce"
                )
                st.bar_chart(category_rates.set_index("category")[["Completion rate (%)"]])
                st.caption(
                    "Completion rate = completed quest attempts / accepted quest attempts "
                    "for each activity category during the last 30 days. "
                    "The table below also shows the sample sizes."
                )
            else:
                st.warning("BQ9 is missing the fields needed for the completion chart.")

        st.dataframe(frame, use_container_width=True)
