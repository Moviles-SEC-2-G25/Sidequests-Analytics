"""Streamlit entry point: streamlit run dashboard_app.py from this repository."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
runpy.run_module("sidequests_analytics.dashboard", run_name="__main__")
