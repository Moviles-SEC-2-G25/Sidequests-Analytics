from pathlib import Path
import os
import sys
import uuid

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics import pipeline
from sidequests_analytics.queries import BQ14_SOCIAL_COMFORT_SQL


def test_bq14_reads_only_its_events_and_ignores_foreign_accounts():
    sql = BQ14_SOCIAL_COMFORT_SQL.lower()
    assert "'bq14_social_comfort_session'" in sql
    assert "'bq14_social_comfort_changed'" in sql
    assert "metadata->>'bq' = 'bq14'" in sql
    assert "metadata->>'account_user_id' = user_id::text" in sql
    assert "comfort in ('low', 'medium')" in sql


def test_bq14_compares_as_treated_and_intent_to_treat():
    sql = BQ14_SOCIAL_COMFORT_SQL.lower()
    assert "'as_treated'" in sql
    assert "'intent_to_treat'" in sql
    assert "arm = 'adapt_default'" in sql
    assert "uq.status <> 'skipped'" in sql
    assert "interval '7 days'" in sql
    assert "small_sample" in sql


def test_missing_rates_serialize_as_null(monkeypatch):
    frame = pd.DataFrame([{"comparison": "as_treated", "cohort": "adapted", "users": 1,
                           "completion_rate_pct": float("nan"), "return_rate_7d_pct": float("nan")}])
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: frame)
    row = pipeline.compute_bq14(object())[0]
    assert row["completion_rate_pct"] is None
    assert row["return_rate_7d_pct"] is None


def test_pipeline_exposes_bq14():
    source = Path(pipeline.__file__).read_text()
    assert 'store_bq_result(engine, "BQ14", bq14)' in source
    assert '"bq14"' in source


def test_bq14_postgresql_completion_and_return_by_cohort():
    from sqlalchemy import create_engine, text

    url = os.getenv("BQ14_TEST_DATABASE_URL") or os.getenv("BQ2_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Isolated PostgreSQL test database configured by CI only")
    engine = create_engine(url)
    adapted, control, high, foreign = (str(uuid.uuid4()) for _ in range(4))

    def event(user, comfort, arm, active, days_ago, account=None):
        return {
            "u": user, "t": "bq14_social_comfort_changed", "d": days_ago,
            "m": (
                '{"bq":"BQ14","comfort":"%s","arm":"%s","adaptation_active":%s,"account_user_id":"%s"}'
                % (comfort, arm, "true" if active else "false", account or user)
            ),
        }

    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("create temporary table quests(id text primary key)"))
            conn.execute(text(
                "create temporary table user_quests(id uuid primary key, user_id uuid, quest_id text, "
                "status text, accepted_at timestamptz)"
            ))
            conn.execute(text(
                "create temporary table analytics_events(user_id uuid, session_id text, event_type text, "
                "quest_id text, metadata jsonb, occurred_at timestamptz)"
            ))
            sql = BQ14_SOCIAL_COMFORT_SQL.replace("public.", "pg_temp.")
            events = [
                event(adapted, "low", "adapt_default", True, 10),
                event(control, "medium", "control", False, 10),
                event(high, "high", "adapt_default", False, 10),           # not low willingness
                event(foreign, "low", "adapt_default", True, 10, account=adapted),  # foreign upload
            ]
            for e in events:
                conn.execute(text(
                    "insert into pg_temp.analytics_events(user_id, session_id, event_type, metadata, occurred_at) "
                    "values (cast(:u as uuid), 's', :t, cast(:m as jsonb), now() - make_interval(days => :d))"
                ), e)
            # adapted user comes back 2 days later, control user never returns
            conn.execute(text(
                "insert into pg_temp.analytics_events(user_id, session_id, event_type, metadata, occurred_at) "
                "values (cast(:u as uuid), 's2', 'app_open', '{}'::jsonb, now() - interval '8 days')"
            ), {"u": adapted})
            attempts = [
                (adapted, "completed"), (adapted, "completed"), (adapted, "abandoned"), (adapted, "skipped"),
                (control, "completed"), (control, "abandoned"), (control, "abandoned"),
            ]
            for user, status in attempts:
                conn.execute(text(
                    "insert into pg_temp.user_quests values (cast(:id as uuid), cast(:u as uuid), 'q', :s, "
                    "now() - interval '9 days')"
                ), {"id": str(uuid.uuid4()), "u": user, "s": status})

            rows = {
                (r["comparison"], r["cohort"]): r
                for r in conn.execute(text(sql)).mappings().all()
            }
        finally:
            tx.rollback()

    treated = rows[("as_treated", "adapted")]
    assert treated["users"] == 1
    assert treated["accepted_attempts"] == 3
    assert treated["completed_attempts"] == 2
    assert float(treated["completion_rate_pct"]) == pytest.approx(66.67)
    assert float(treated["return_rate_7d_pct"]) == 100.0

    not_adapted = rows[("as_treated", "not_adapted")]
    assert not_adapted["users"] == 1
    assert float(not_adapted["completion_rate_pct"]) == pytest.approx(33.33)
    assert float(not_adapted["return_rate_7d_pct"]) == 0.0
    assert not_adapted["small_sample"] is True

    assert rows[("intent_to_treat", "adapted")]["users"] == 1
    assert sum(r["users"] for k, r in rows.items() if k[0] == "as_treated") == 2
