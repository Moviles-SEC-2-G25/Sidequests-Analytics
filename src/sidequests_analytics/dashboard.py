import json

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

from .bq12 import bq12_compare, bq12_headline, bq12_level
from .db import get_engine


def _pct(value):
    return "—" if value is None else f"{value:.1f}%"


def _gap(value):
    return None if value is None else f"{value:+.1f} pp vs non-sponsored"


def render_bq12(data):
    st.caption(
        "BQ12 · Acceptance and completion of sponsored vs non-sponsored quests, "
        "by sponsor business category and declared interest (last 30 days)."
    )
    if not data or "segment_level" not in data[0]:
        st.info("No recommendation or quest activity has been recorded yet.")
        return

    headline = bq12_headline(data)
    sponsored, non_sponsored = headline["sponsored"], headline["non_sponsored"]
    columns = st.columns(4)
    columns[0].metric("Sponsored acceptance", _pct(sponsored.get("acceptance_rate_pct")),
                      _gap(headline["acceptance_gap_pp"]))
    columns[1].metric("Non-sponsored acceptance", _pct(non_sponsored.get("acceptance_rate_pct")))
    columns[2].metric("Sponsored completion", _pct(sponsored.get("completion_rate_pct")),
                      _gap(headline["completion_gap_pp"]))
    columns[3].metric("Non-sponsored completion", _pct(non_sponsored.get("completion_rate_pct")))
    if not headline["comparable"]:
        st.info(
            "Not enough sample to compare sponsored and non-sponsored quests yet: "
            f"a rate needs {data[0].get('min_impressions')} impressions or "
            f"{data[0].get('min_attempts')} accepted attempts. Counts are in the table."
        )

    by_business = bq12_level(data, "business_category")
    if not by_business.empty:
        st.write("By sponsor business category (`none` = non-sponsored baseline)")
        st.bar_chart(
            by_business.set_index("business_category")[["acceptance_rate_pct", "completion_rate_pct"]],
            stack=False,
        )

    left, right = st.columns(2)
    acceptance_by_interest = bq12_compare(data, "interest", "interest", "acceptance_rate_pct")
    completion_by_interest = bq12_compare(data, "interest", "interest", "completion_rate_pct")
    if not acceptance_by_interest.empty:
        with left:
            st.write("Acceptance (%) by declared interest")
            st.bar_chart(acceptance_by_interest, stack=False)
        with right:
            st.write("Completion (%) by declared interest")
            st.bar_chart(completion_by_interest, stack=False)

    grid = bq12_level(data, "business_category_x_interest")
    if not grid.empty:
        st.write("Acceptance (%) by business category × interest (empty cell = no rate)")
        heatmap = alt.Chart(grid).mark_rect().encode(
            x=alt.X("interest:N", title="Declared interest"),
            y=alt.Y("business_category:N", title="Business category"),
            color=alt.Color("acceptance_rate_pct:Q", title="Acceptance (%)"),
            tooltip=["business_category", "interest", "impressions", "acceptance_rate_pct",
                     "accepted_attempts", "completion_rate_pct"],
        )
        st.altair_chart(heatmap, use_container_width=True)

    match = bq12_level(data, "interest_match")
    if not match.empty:
        st.write("Does the quest match a declared interest?")
        st.table(match[["sponsor_type", "interest_match", "impressions", "acceptance_rate_pct",
                        "accepted_attempts", "completion_rate_pct"]])

    st.caption(
        "Acceptance = accepted unique recommendation impressions (one per user, session and "
        "quest) / impressions. Completion = completed / accepted attempts, skips excluded. "
        "Rates are empty below the sample threshold or without exposure. A user with several "
        "interests counts in each of them, so interest rows don't add up to the total. "
        "Observational evidence, not a causal effect of sponsorship."
    )


def render_bq12_weekly(frame):
    st.caption("BQ12 · Weekly trend, sponsored vs non-sponsored. Recent weeks still have open attempts.")
    if frame.empty or "week_start" not in frame.columns:
        st.info("No weekly BQ12 data yet.")
        return
    trend = frame.copy()
    trend["acceptance_rate_pct"] = pd.to_numeric(trend["acceptance_rate_pct"], errors="coerce")
    wide = trend.pivot(index="week_start", columns="sponsor_type", values="acceptance_rate_pct")
    st.write("Acceptance (%) per week")
    st.line_chart(wide)


st.set_page_config(page_title="Sidequests Analytics", layout="wide")
st.title("Sidequests · BQ Dashboard")
st.caption("Shared Sprint 2 and Sprint 3 analytics results from the Sidequests database")

engine = get_engine()

with st.expander("Sprint 4 · BQ2 — Group Challenge Module"):
    st.caption("Live, read-only comparison of server-received requests in the last 30 days.")
    if st.button("Load / refresh BQ2", key="refresh_bq2"):
        try:
            from .pipeline import bq2_schema_ready, compute_bq2
            if bq2_schema_ready(engine):
                st.session_state["bq2_live"] = compute_bq2(engine)
            else:
                st.session_state.pop("bq2_live", None)
                st.warning("The shared group challenge backend has not been deployed.")
        except Exception:
            st.session_state.pop("bq2_live", None)
            st.error("BQ2 could not be loaded. Check database access and migration status.")
    if "bq2_live" in st.session_state:
        from .bq2_dashboard import render_bq2
        render_bq2(pd.DataFrame(st.session_state["bq2_live"]))

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
        if row["bq_key"] == "BQ2":
            from .bq2_dashboard import render_bq2
            render_bq2(frame)

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

        if row["bq_key"] == "BQ12":
            render_bq12(data)

        if row["bq_key"] == "BQ12_WEEKLY":
            render_bq12_weekly(frame)

        st.dataframe(frame, use_container_width=True)
