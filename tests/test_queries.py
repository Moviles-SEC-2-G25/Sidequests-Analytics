from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.queries import (
    BQ6_ABANDONMENT_BASE_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    USER_FEATURES_SQL,
)


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
