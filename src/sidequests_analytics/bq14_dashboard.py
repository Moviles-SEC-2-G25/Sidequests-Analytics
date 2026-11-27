import pandas as pd
import streamlit as st

REQUIRED = {
    "comparison", "cohort", "users", "accepted_attempts", "completed_attempts",
    "completion_rate_pct", "return_eligible_users", "returned_users", "return_rate_7d_pct",
}


def render_bq14(frame: pd.DataFrame):
    st.caption(
        "BQ14 · For users with low willingness to join socially demanding activities, "
        "does adapting Smart Picks to their social comfort level increase completion "
        "and 7-day return?"
    )
    if frame.empty:
        st.info("No user with low or medium social comfort has been recorded in the last 30 days.")
        return
    if not REQUIRED.issubset(frame.columns):
        st.warning("BQ14 is missing the fields needed for the comparison charts.")
        return

    data = frame.copy()
    for column in ("completion_rate_pct", "return_rate_7d_pct"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["Cohort"] = data["cohort"].map({"adapted": "Adapted", "not_adapted": "Not adapted"}).fillna(data["cohort"])

    treated = data[data["comparison"] == "as_treated"].set_index("Cohort")
    left, right = st.columns(2)
    with left:
        st.write("Completion rate (%)")
        st.bar_chart(treated[["completion_rate_pct"]].rename(columns={"completion_rate_pct": "Completion (%)"}))
    with right:
        st.write("7-day return rate (%)")
        st.bar_chart(treated[["return_rate_7d_pct"]].rename(columns={"return_rate_7d_pct": "Return 7d (%)"}))

    st.write("Comparison table")
    st.table(data[[
        "comparison", "Cohort", "users", "accepted_attempts", "completed_attempts",
        "completion_rate_pct", "return_eligible_users", "returned_users", "return_rate_7d_pct",
    ]].rename(columns={
        "comparison": "Comparison",
        "users": "Users",
        "accepted_attempts": "Accepted",
        "completed_attempts": "Completed",
        "completion_rate_pct": "Completion (%)",
        "return_eligible_users": "Return-eligible users",
        "returned_users": "Returned",
        "return_rate_7d_pct": "Return 7d (%)",
    }))
    if (data["users"].fillna(0) < 10).any():
        st.warning(
            "At least one cohort has fewer than 10 users. Treat the difference as "
            "exploratory, not as evidence that adaptation works."
        )
    st.caption(
        "As treated = adaptation active in the user's latest BQ14 event. Intent to treat = "
        "hash-assigned arm, which only sets the default of the switch. Completion = completed / "
        "accepted attempts since the first low-comfort exposure (skips excluded). Return = app "
        "activity on a later day within 7 days; only users exposed 7+ days ago count. "
        "Last 30 days. Observational, not causal."
    )
