"""Checks for Sebastián's new Sprint 3 business question.

These tests validate the SQL contract and pipeline wiring only. A run against
the real Supabase PostgreSQL database and a mobile demonstration are separate
acceptance criteria.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.queries import BQ12_SPONSORED_QUEST_PERFORMANCE_SQL
from sidequests_analytics import pipeline


def test_bq12_compares_sponsored_and_other_quests():
    sql = BQ12_SPONSORED_QUEST_PERFORMANCE_SQL.lower()
    assert "q.is_sponsored" in sql
    assert "recommendation_shown" in sql
    assert "accepted.event_type in ('quest_accepted', 'recommendation_accepted')" in sql
    assert "accepted.session_id is not distinct from i.session_id" in sql
    assert "public.user_quests" in sql
    assert "recommendation_acceptance_rate_pct" in sql
    assert "completion_rate_pct" in sql
    assert "accepted_at >= now() - interval '30 days'" in sql
    assert "status = 'completed'" in sql


def test_bq12_compares_declared_interests_without_exposing_user_ids():
    sql = BQ12_SPONSORED_QUEST_PERFORMANCE_SQL.lower()
    assert "public.user_preferences" in sql
    assert "unnest(up.interests)" in sql
    assert "interest_segment" in sql
    assert "none_declared" in sql
    assert "matching" in sql
    assert "not_matching" in sql
    # Only grouped public metrics are selected at the top level.
    selected = sql.split("\nselect\n")[-1]
    assert "user_id" not in selected
    assert "session_id" not in selected


def test_bq12_avoids_division_by_zero_and_duplicate_impressions():
    sql = BQ12_SPONSORED_QUEST_PERFORMANCE_SQL.lower()
    assert "distinct on (ae.user_id, ae.session_id, ae.quest_id)" in sql
    assert "nullif(s.recommendation_impressions, 0)" in sql
    assert "nullif(a.accepted_attempts, 0)" in sql


def test_pipeline_registers_bq12_job():
    assert callable(pipeline.compute_bq12)
    import inspect

    src = inspect.getsource(pipeline.run)
    assert '"bq12"' in src
    assert 'store_bq_result(engine, "BQ12", bq12)' in src
