from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.queries import (
    BQ3_ONBOARDING_DROPOFF_SQL,
    BQ6_ABANDONMENT_BASE_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    USER_FEATURES_SQL,
)


def test_bq3_ranks_steps_by_dropoff_using_session_funnel():
    sql = BQ3_ONBOARDING_DROPOFF_SQL.lower()
    assert "onboarding_step_completed" in sql
    assert "step_order" in sql
    assert "session_id is not null" in sql
    assert "distinct session_id" in sql
    assert "dropoff_rate_pct" in sql
    assert "order by dropoff_rate_pct desc" in sql


def test_bq3_excludes_final_step_with_no_next_step():
    sql = BQ3_ONBOARDING_DROPOFF_SQL.lower()
    assert "where sessions_reached_next_step is not null" in sql


def test_bq9_targets_last_30_days_and_completion():
    sql = BQ9_CATEGORY_PERFORMANCE_SQL.lower()
    assert "30 days" in sql
    assert "status = 'completed'" in sql
    assert "category" in sql


def test_bq6_uses_current_abandonment_sources():
    sql = BQ6_ABANDONMENT_BASE_SQL.lower()
    assert "abandon_reason" in sql
    assert "duration_minutes" in sql
    assert "estimated_cost" in sql
    assert "status = 'abandoned'" in sql


def test_user_features_are_per_user():
    sql = USER_FEATURES_SQL.lower()
    assert "group by uq.user_id" in sql
    assert "preferred_categories" in sql
    assert "completion_rate" in sql
