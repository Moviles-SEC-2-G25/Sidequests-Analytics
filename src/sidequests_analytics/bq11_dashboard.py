import pandas as pd
import streamlit as st


def render_bq11(rows):
    st.caption(
        "Completed physical quests with more than 20 minutes of observed activity "
        "in one mapped Bogotá pilot block. Completion and activity must be in the same "
        "Bogotá weekend. Last 30 days, Kotlin opt-in observations only. "
        "A block is shown after at least five distinct users qualify."
    )
    if not rows:
        st.info("No pilot block meets the reporting threshold for this window.")
        return

    frame = pd.DataFrame(rows).rename(columns={
        "commercial_block": "Commercial block",
        "qualifying_attempts": "Qualifying attempts",
        "distinct_users": "Distinct users",
        "mean_observed_minutes": "Mean observed minutes",
    })
    st.bar_chart(frame.set_index("Commercial block")[["Qualifying attempts"]], horizontal=True)
    st.dataframe(
        frame[["Commercial block", "Qualifying attempts", "Distinct users", "Mean observed minutes"]],
        hide_index=True,
    )
    st.caption("These observations describe opted-in quest participants, not total pedestrian traffic.")
