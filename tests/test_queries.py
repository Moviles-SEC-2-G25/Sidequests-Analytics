from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.queries import (
    BQ3_ONBOARDING_DROPOFF_SQL,
    BQ4_INSTANT_PLAN_SQL,
    BQ5_PERSONALIZED_RECOMMENDATION_SQL,
    BQ6_ABANDONMENT_BASE_SQL,
    BQ8_RECOMMENDATION_DIVERSITY_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    BQ10_LOCATION_INDEPENDENT_USAGE_SQL,
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


def test_bq8_compares_experiment_variants_over_time():
    sql = BQ8_RECOMMENDATION_DIVERSITY_SQL.lower()
    assert "recommendation_shown" in sql
    assert "metadata->>'variant'" in sql
    assert "metadata->>'batch_id'" in sql
    assert "date_trunc('week'" in sql
    assert "order by e.week_start desc, e.variant" in sql


def test_bq8_reports_diversity_metrics_and_acceptance_guardrail():
    sql = BQ8_RECOMMENDATION_DIVERSITY_SQL.lower()
    assert "avg_distinct_categories_per_list" in sql
    assert "category_entropy_norm" in sql
    assert "catalog_coverage_pct" in sql
    assert "repeat_exposure_pct" in sql
    assert "recommendation_accepted" in sql
    assert "acceptance_rate_pct" in sql


def test_bq4_compares_instant_plan_against_standard_start_path():
    sql = BQ4_INSTANT_PLAN_SQL.lower()
    assert "recommendation_accepted" in sql
    assert "quest_started" in sql
    assert "metadata ? 'start_path'" in sql
    assert "start_path" in sql
    assert "group by start_path" in sql


def test_bq4_reports_median_and_reduction_vs_standard():
    sql = BQ4_INSTANT_PLAN_SQL.lower()
    assert "percentile_cont(0.5)" in sql
    assert "median_seconds_to_start" in sql
    assert "avg_interactions_to_start" in sql
    assert "seconds_reduction_pct_vs_standard" in sql
    assert "interactions_reduction_pct_vs_standard" in sql
    assert "where start_path = 'standard'" in sql



def test_bq5_exposes_top_three_personalized_recommendations():
    sql = BQ5_PERSONALIZED_RECOMMENDATION_SQL.lower()
    assert "recommendation_shown" in sql
    assert "rank_position <= 3" in sql
    assert "available_minutes" in sql
    assert "social_level" in sql
    assert "location_mode" in sql
    assert "batch_id" in sql


def test_bq9_targets_last_30_days_and_completion():
    sql = BQ9_CATEGORY_PERFORMANCE_SQL.lower()
    assert "30 days" in sql
    assert "from results" in sql
    assert "case when time_of_day = 'overall' then 0 else 1 end" in sql
    assert "status = 'completed'" in sql
    assert "category" in sql


def test_bq6_uses_current_abandonment_sources():
    sql = BQ6_ABANDONMENT_BASE_SQL.lower()
    assert "abandon_reason" in sql
    assert "duration_minutes" in sql
    assert "estimated_cost" in sql
    assert "status = 'abandoned'" in sql


def test_bq6_segments_by_distance_from_abandon_events():
    sql = BQ6_ABANDONMENT_BASE_SQL.lower()
    assert "analytics_events" in sql
    assert "event_type = 'quest_abandoned'" in sql
    assert "distance_meters" in sql
    assert "distance_bucket" in sql


def test_user_features_are_per_user():
    sql = USER_FEATURES_SQL.lower()
    assert "group by uq.user_id" in sql
    assert "preferred_categories" in sql
    assert "completion_rate" in sql


def test_bq10_measures_location_independent_usage_by_session_and_context():
    sql = BQ10_LOCATION_INDEPENDENT_USAGE_SQL.lower()
    assert "location_independent_mode_selected" in sql
    assert "location_based_mode_selected" in sql
    assert "location_mode in ('gps', 'anywhere')" in sql
    assert "count(*) filter (where used_location_independent)" in sql
    assert "time_of_day" in sql
    assert "weather_condition" in sql
    assert "location_independent_usage_pct" in sql
    assert "30 days" in sql
