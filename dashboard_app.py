"""Streamlit entry point: python -m streamlit run dashboard_app.py."""

import os
from pathlib import Path
import runpy
import sys

import streamlit as st

# Existing DATABASE_URL configuration still works. For a one-click local demo,
# Streamlit can also load the git-ignored .streamlit/secrets.toml file.
if not os.getenv("DATABASE_URL"):
    try:
        database_url = st.secrets.get("DATABASE_URL")
    except (FileNotFoundError, PermissionError, OSError):
        database_url = None
    if not database_url:
        st.error(
            "Missing database connection. Run scripts/configure_bq8_dashboard.py "
            "once, or set DATABASE_URL in this process."
        )
        st.stop()
    os.environ["DATABASE_URL"] = str(database_url)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
runpy.run_module("sidequests_analytics.dashboard", run_name="__main__")
