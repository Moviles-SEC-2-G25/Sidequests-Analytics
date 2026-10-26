import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from .db import get_engine


st.set_page_config(page_title="Sidequests Analytics", layout="wide")
st.title("Sidequests · BQ Dashboard")
st.caption("Sprint 2 analytics outputs stored in analytics.bq_results")

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
        if row["bq_key"] == "BQ12":
            st.caption(
                "Sprint 3 · Sponsored vs regular quests. "
                "Acceptance uses recommendation events; completion uses accepted attempts."
            )
            if frame.empty:
                st.info("BQ12 has no recorded observations yet.")
            else:
                count_columns = [
                    "recommendation_impressions",
                    "accepted_recommendations",
                    "accepted_attempts",
                    "completed_attempts",
                ]
                for column in count_columns:
                    frame[column] = pd.to_numeric(
                        frame[column], errors="coerce"
                    ).fillna(0)

                totals = frame.groupby("is_sponsored", as_index=False)[
                    count_columns
                ].sum()
                if not (totals["is_sponsored"] == True).any():
                    st.warning(
                        "No sponsored observations are available. "
                        "The comparison cannot support a conclusion about sponsorship."
                    )
                totals["type"] = totals["is_sponsored"].map(
                    {True: "Sponsored", False: "Regular"}
                )
                totals["Recommendation acceptance %"] = (
                    100 * totals["accepted_recommendations"]
                    / totals["recommendation_impressions"].replace(0, float("nan"))
                )
                totals["Quest completion %"] = (
                    100 * totals["completed_attempts"]
                    / totals["accepted_attempts"].replace(0, float("nan"))
                )
                st.bar_chart(
                    totals.set_index("type")[
                        ["Recommendation acceptance %", "Quest completion %"]
                    ]
                )
                st.caption(
                    "The table below preserves the business-category, activity-category "
                    "and declared-interest breakdown. Missing classifications appear as "
                    "'unclassified'. Current interests may not match historical interests."
                )
        st.dataframe(frame, use_container_width=True)
