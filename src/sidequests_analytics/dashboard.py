import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from .db import get_engine


st.set_page_config(page_title="Sidequests Analytics", layout="wide")
st.title("Sidequests · BQ Dashboard")
st.caption("Shared Sprint 2 and Sprint 3 analytics results from the Sidequests database")

engine = get_engine()

# Sprint 4 BQ8: a reproducible live read-only view. It does not depend on
# the BQ8_EXPERIENCED result having been published in analytics.bq_results.
st.subheader("Sprint 4 · BQ8 — Recommendation Diversity")
st.caption(
    "Live PostgreSQL analysis · Users with at least two completions before "
    "exposure · Server experiment: control vs diverse"
)
refresh_bq8 = st.button("Refresh live BQ8", key="refresh_live_bq8")
if refresh_bq8 or "bq8_live_rows" not in st.session_state:
    try:
        from .pipeline import compute_bq8_experienced
        with st.spinner("Reading BQ8 cohorts from Supabase..."):
            st.session_state["bq8_live_rows"] = compute_bq8_experienced(engine)
            st.session_state["bq8_live_at"] = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        # Do not surface DB connection strings or driver exceptions to viewers.
        st.error("The live BQ8 query could not be completed. Verify database access and schema.")
        st.session_state.pop("bq8_live_rows", None)

live_rows = st.session_state.get("bq8_live_rows", [])
if live_rows:
    live_frame = pd.DataFrame(live_rows)
    required_columns = {
        "variant", "eligible_users", "comparable_batches",
        "avg_distinct_categories_per_list", "acceptance_rate_pct",
        "return_rate_24h_pct",
    }
    if required_columns.issubset(live_frame.columns):
        st.caption(
            f"Last read: {st.session_state.get('bq8_live_at', 'unknown')} · "
            "Read-only: no new results are stored"
        )
        control = live_frame.loc[live_frame["variant"] == "control"]
        diverse = live_frame.loc[live_frame["variant"] == "diverse"]
        left, right = st.columns(2)
        with left:
            st.metric("Eligible control users", int(control["eligible_users"].sum()))
        with right:
            st.metric("Eligible diverse users", int(diverse["eligible_users"].sum()))
        st.write("Category diversity (mean distinct categories per comparable visible list)")
        bars = live_frame.set_index("variant")[["avg_distinct_categories_per_list"]].copy()
        bars["avg_distinct_categories_per_list"] = pd.to_numeric(
            bars["avg_distinct_categories_per_list"], errors="coerce"
        )
        st.bar_chart(bars)
        st.write("Acceptance and observed return (percent, by experimental arm)")
        outcomes = live_frame.set_index("variant")[["acceptance_rate_pct", "return_rate_24h_pct"]].copy()
        outcomes = outcomes.apply(pd.to_numeric, errors="coerce")
        st.bar_chart(outcomes)
        st.dataframe(live_frame, use_container_width=True)
        st.warning(
            "These are observed associations, not causal evidence. "
            "Only a few experienced users are currently eligible; repeated "
            "recommendation batches are not independent participants."
        )
        st.caption(
            "Acceptance: distinct matured user/session/quest opportunities. "
            "Return: different instrumented session 30 min–24 h after first "
            "eligible exposure. An app opening without telemetry is not observed."
        )
else:
    st.info("There are no completed read-only BQ8 query results for this session.")

st.divider()
st.subheader("Previously stored Business Question results")

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
        if row["bq_key"] == "BQ3" and data and data[0].get("schema_version") == 2:
            bq3_frame = frame.sort_values("step_order").set_index("step_name")
            st.caption(f"Platform: {data[0]['platform']} · Initial instrumented setups: {data[0]['journeys_started']} · Observation horizon: {data[0]['observation_hours']:g} hours")
            left, right = st.columns(2)
            with left:
                st.write("Where setup stops")
                st.bar_chart(bq3_frame[["explicit_skip_count", "inactivity_dropoff_count"]])
            with right:
                st.write("First recommendation acceptance by step completion")
                st.bar_chart(bq3_frame[["completed_step_acceptance_rate_pct", "not_completed_step_acceptance_rate_pct"]])
                eligible = bq3_frame[["completed_step_eligible_first_shown", "not_completed_step_eligible_first_shown"]].sum().sum()
                accepted = bq3_frame[["completed_step_first_accepted", "not_completed_step_first_accepted"]].sum().sum()
                if eligible == 0:
                    st.info("No first exposures have a complete observation window yet; acceptance rates are pending.")
                elif accepted == 0:
                    st.info("Acceptance is 0% in the eligible groups for this observation window. A zero-height bar is not a missing chart. Groups without eligible exposures have no rate.")
            st.write("Acceptance counts and rates")
            summary = bq3_frame[[
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

        if row["bq_key"] == "BQ8_EXPERIENCED":
            st.caption(
                "BQ8 Sprint 4 · Users with at least 2 completed quests before the "
                "recommendation. Acceptance and a 24h different-session return proxy."
            )
            required = {
                "variant", "eligible_users", "comparable_batches",
                "avg_distinct_categories_per_list", "acceptance_rate_pct",
                "return_rate_24h_pct", "mature_return_users",
            }
            if not required.issubset(frame.columns):
                st.warning("The completed-user experiment result is missing required fields.")
            else:
                st.table(frame[[
                    "variant", "eligible_users", "comparable_batches",
                    "avg_distinct_categories_per_list",
                    "mature_acceptance_opportunities", "accepted_mature_opportunities",
                    "acceptance_rate_pct", "mature_return_users",
                    "observed_return_users_24h", "return_rate_24h_pct",
                ]])
                if (frame["eligible_users"].fillna(0) < 10).any():
                    st.warning(
                        "Sample too small for a reliable treatment effect. "
                        "Do not claim the diverse arm improves acceptance or retention."
                    )
                st.caption(
                    "Return proxy: a separately instrumented user session starting "
                    "30 minutes to 24 hours after first eligible exposure. "
                    "Only mature 24-hour cohorts enter outcome denominators; "
                    "missing or uninstrumented app opens cannot be detected. "
                    "This is observational evidence, not causal validation."
                )

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
