import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from .db import get_engine


st.set_page_config(page_title="Sidequests Analytics", layout="wide")
st.title("Sidequests · BQ Dashboard")
st.caption("Analytics outputs stored in analytics.bq_results")

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
        if row["bq_key"] == "BQ3" and data and data[0].get("schema_version") == 2:
            frame = pd.DataFrame(data).sort_values("step_order").set_index("step_name")
            st.caption(f"Platform: {data[0]['platform']} · Initial instrumented setups: {data[0]['journeys_started']} · Observation horizon: {data[0]['observation_hours']:g} hours")
            left, right = st.columns(2)
            with left:
                st.write("Where setup stops")
                st.bar_chart(frame[["explicit_skip_count", "inactivity_dropoff_count"]])
            with right:
                st.write("First recommendation acceptance by step completion")
                st.bar_chart(frame[["completed_step_acceptance_rate_pct", "not_completed_step_acceptance_rate_pct"]])
                eligible = frame[["completed_step_eligible_first_shown", "not_completed_step_eligible_first_shown"]].sum().sum()
                accepted = frame[["completed_step_first_accepted", "not_completed_step_first_accepted"]].sum().sum()
                if eligible == 0:
                    st.info("No first exposures have a complete observation window yet; acceptance rates are pending.")
                elif accepted == 0:
                    st.info("Acceptance is 0% in the eligible groups for this observation window. A zero-height bar is not a missing chart. Groups without eligible exposures have no rate.")
            st.write("Acceptance counts and rates")
            summary = frame[[
                "step_order", "completed_step_eligible_first_shown", "completed_step_first_accepted",
                "completed_step_acceptance_rate_pct", "completed_step_pending_outcomes",
                "not_completed_step_eligible_first_shown", "not_completed_step_first_accepted",
                "not_completed_step_acceptance_rate_pct", "not_completed_step_pending_outcomes",
            ]].rename(columns={
                "step_order": "Step",
                "completed_step_eligible_first_shown": "Completed: eligible",
                "completed_step_first_accepted": "Completed: accepted",
                "completed_step_acceptance_rate_pct": "Completed: acceptance (%)",
                "completed_step_pending_outcomes": "Completed: pending",
                "not_completed_step_eligible_first_shown": "Not completed: eligible",
                "not_completed_step_first_accepted": "Not completed: accepted",
                "not_completed_step_acceptance_rate_pct": "Not completed: acceptance (%)",
                "not_completed_step_pending_outcomes": "Not completed: pending",
            })
            st.table(summary)
            st.caption("Acceptance uses only first exposures with a complete observation window. Recent outcomes remain pending; no exposure is not a rejection. Differences are associations, not causal effects.")
        st.dataframe(pd.DataFrame(data), use_container_width=True)
