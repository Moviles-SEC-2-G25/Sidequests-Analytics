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
        st.dataframe(pd.DataFrame(data), use_container_width=True)
