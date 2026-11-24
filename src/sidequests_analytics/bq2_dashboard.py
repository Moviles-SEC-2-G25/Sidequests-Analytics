import pandas as pd
import streamlit as st


def render_bq2(frame: pd.DataFrame) -> None:
    if frame.empty or "row_type" not in frame:
        st.info("No BQ2 observations yet.")
        return
    operations = frame[frame["row_type"] == "operation"].copy()
    groups = frame[frame["row_type"] == "challenge"].copy()
    st.caption("Each unique server-received request counts once, including handled failures. "
               "Requests lost before reaching the server are not measured. "
               "Participants include the creator and count distinct memberships per challenge.")
    if not groups.empty:
        st.metric("Participant memberships (last 30 days)", int(groups["participants"].sum()))
        st.metric("Challenges", len(groups))
        st.dataframe(groups[["quest_title", "active", "participants", "completed_participants"]],
                     hide_index=True, use_container_width=True)
    else:
        st.info("No challenges created in the observation window.")
    if not operations.empty:
        st.write("Server operations")
        st.dataframe(operations[["operation", "attempts", "successes", "failures", "failure_rate_pct"]],
                     hide_index=True, use_container_width=True)
        if operations["attempts"].sum() > 0:
            counts = operations.set_index("operation")[["successes", "failures"]].apply(pd.to_numeric)
            st.bar_chart(counts)
        else:
            st.info("No server requests observed; failure rate is undefined, not 0%.")
