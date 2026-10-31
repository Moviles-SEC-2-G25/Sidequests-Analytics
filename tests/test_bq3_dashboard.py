from pathlib import Path
import sys

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def test_real_streamlit_entrypoint_renders_empty_bq3_and_survives_rerun(monkeypatch):
    from sidequests_analytics import db
    from sidequests_analytics.bq3 import summarize_bq3
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: pd.DataFrame([
        dict(bq_key="BQ3", computed_at="test fixture", payload={"rows": summarize_bq3([])})
    ]))
    app = AppTest.from_file(str(ROOT / "dashboard_app.py")).run(timeout=20)
    assert not app.exception
    assert len(app.dataframe) == 1
    assert len(app.get("arrow_vega_lite_chart")) == 2
    assert len(app.table) == 1
    assert len(app.info) == 1
    assert "pending" in app.info[0].value
    app.run(timeout=20)
    assert not app.exception
    assert len(app.dataframe) == 1


def test_zero_acceptance_is_visible_as_counts_and_zero_rates(monkeypatch):
    from sidequests_analytics import db
    from sidequests_analytics.bq3 import summarize_bq3
    from test_bq3 import NOW, setup
    records = setup("complete", 4) + setup("skip", 0)
    rows = summarize_bq3(records, as_of=NOW)
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: pd.DataFrame([
        dict(bq_key="BQ3", computed_at="test fixture", payload={"rows": rows})
    ]))
    app = AppTest.from_file(str(ROOT / "dashboard_app.py")).run(timeout=20)
    assert not app.exception
    assert "0%" in app.info[0].value
    summary = app.table[0].value
    assert list(summary["Step"]) == [1, 2, 3, 4]
    assert summary["Completed: eligible"].tolist() == [1, 1, 1, 1]
    assert summary["Completed: acceptance (%)"].tolist() == [0.0] * 4
    assert summary["Not completed: accepted"].tolist() == [0] * 4


def test_connection_helper_encodes_special_password_characters_without_manual_edits():
    from run_bq3_local import connection_url
    url = connection_url("postgresql://postgres.project:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres", "test/p@ss:?#%")
    assert url.password == "test/p@ss:?#%"
    assert "%2F" in url.render_as_string(hide_password=False)
    assert url.query["sslmode"] == "require"


def test_shared_dashboard_keeps_bq1_and_bq9_charts_with_bq3(monkeypatch):
    from sidequests_analytics import db
    from sidequests_analytics.bq3 import summarize_bq3
    stored = pd.DataFrame([
        dict(bq_key="BQ1", computed_at="fixture", payload={"rows": [
            dict(module="context", failure_rate_pct=25, app_version="0.2.0")
        ]}),
        dict(bq_key="BQ3", computed_at="fixture", payload={"rows": summarize_bq3([])}),
        dict(bq_key="BQ9", computed_at="fixture", payload={"rows": [
            dict(category="Outdoors", completion_rate_pct=50, accepted_count=2, completed_count=1)
        ]}),
    ])
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: stored)
    app = AppTest.from_file(str(ROOT / "dashboard_app.py")).run(timeout=20)
    assert not app.exception
    assert [item.value for item in app.subheader] == ["BQ1", "BQ3", "BQ9"]
    assert len(app.get("arrow_vega_lite_chart")) == 4
    assert len(app.dataframe) == 3
    assert app.dataframe[0].value["module"].tolist() == ["context"]
    assert app.dataframe[1].value["step_name"].tolist() == [
        "interests", "difficulty", "typical_time", "budget_social"
    ]
    assert app.dataframe[2].value["category"].tolist() == ["Outdoors"]
