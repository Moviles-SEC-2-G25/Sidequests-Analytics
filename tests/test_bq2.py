from pathlib import Path

import pandas as pd

from sidequests_analytics import pipeline
from sidequests_analytics.queries import BQ2_GROUP_CHALLENGES_SQL


def test_bq2_query_counts_members_and_failed_requests_not_fake_events():
    sql = BQ2_GROUP_CHALLENGES_SQL.lower()
    assert "sidequests_group_private.members" in sql
    assert "sidequests_group_private.operations" in sql
    assert "filter(where not succeeded)" in sql
    assert "nullif(o.attempts,0)" in sql
    assert "m.progress=c.total_steps" in sql
    assert "recommendation_shown" not in sql


def test_missing_failure_rate_serializes_as_null(monkeypatch):
    frame = pd.DataFrame([{"row_type":"operation","operation":"join","attempts":0,
                           "failure_rate_pct":float("nan")}])
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: frame)
    assert pipeline.compute_bq2(object())[0]["failure_rate_pct"] is None


def test_pipeline_exposes_bq2():
    source = Path(pipeline.__file__).read_text()
    assert 'store_bq_result(engine, "BQ2", bq2)' in source
    assert 'elif args.job == "bq2"' in source
