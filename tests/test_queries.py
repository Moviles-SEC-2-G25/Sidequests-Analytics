from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.queries import (
    BQ1_MODULE_FAILURES_AFTER_RESUME_SQL,
    BQ3_ONBOARDING_DROPOFF_SQL,
    BQ4_INSTANT_PLAN_SQL,
    BQ5_PERSONALIZED_RECOMMENDATION_SQL,
    BQ6_ABANDONMENT_BASE_SQL,
    BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL,
    BQ8_RECOMMENDATION_DIVERSITY_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    BQ10_LOCATION_INDEPENDENT_USAGE_SQL,
    USER_FEATURES_SQL,
)


def test_bq3_extracts_only_versioned_linkable_source_events():
    sql = BQ3_ONBOARDING_DROPOFF_SQL.lower()
    assert "metadata->>'bq_key' = 'bq3'" in sql
    assert "cast(metadata->>'schema_version' as text) = '2'" in sql
    assert "session_id is not null" in sql
    assert "user_id is not null" in sql


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
    assert "status = 'completed'" in sql
    assert "category" in sql


def test_bq9_measures_recommendation_acceptance_per_category():
    sql = BQ9_CATEGORY_PERFORMANCE_SQL.lower()
    assert "recommendation_shown" in sql
    assert "recommendation_accepted" in sql
    assert "recommendation_skipped" in sql
    assert "session_id is not distinct from s.session_id" in sql
    assert "recommendation_acceptance_rate_pct" in sql
    assert "recommendation_skip_rate_pct" in sql


def test_bq9_does_not_match_actions_before_or_long_after_recommendations():
    sql = BQ9_CATEGORY_PERFORMANCE_SQL.lower()
    assert "min(ae.occurred_at) as first_shown_at" in sql
    assert "a.occurred_at >= s.first_shown_at" in sql
    assert "a.occurred_at < s.first_shown_at + interval '1 day'" in sql
    assert "k.occurred_at >= s.first_shown_at" in sql
    assert "k.occurred_at < s.first_shown_at + interval '1 day'" in sql


def test_bq9_compares_categories_against_overall_baseline():
    sql = BQ9_CATEGORY_PERFORMANCE_SQL.lower()
    assert "status <> 'skipped'" in sql
    assert "abandonment_rate_pct" in sql
    assert "resolved_completion_rate_pct" in sql
    assert "median_minutes_to_complete" in sql
    assert "acceptance_rate_vs_overall_pp" in sql
    assert "completion_rate_vs_overall_pp" in sql
    assert "order by\n    completion_rate_pct desc nulls last" in sql


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


def test_bq6_normalizes_old_flutter_reason_codes_to_kotlin():
    sql = BQ6_ABANDONMENT_BASE_SQL
    for old, new in [
        ("place_closed", "place_unavailable"),
        ("too_hard", "too_difficult"),
        ("bad_weather", "weather_or_mood_changed"),
        ("lost_interest", "other"),
        ("not_specified", "other"),
    ]:
        assert f"when '{old}' then '{new}'" in sql
    assert "coalesce(uq.abandon_reason, 'Unspecified')" in sql


def test_bq6_links_events_by_attempt_and_prefers_the_shared_band():
    sql = BQ6_ABANDONMENT_BASE_SQL
    assert "ae.metadata->>'attempt_id' = cast(uq.id as text)" in sql
    assert "metadata->>'quest_distance_band'" in sql
    assert "legacy_gps_" in sql
    assert "quest_distance_source" in sql
    assert "metadata->>'platform'" in sql


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
    assert "from results" in sql
    assert "case when time_of_day = 'overall' then 0 else 1 end" in sql



def test_bq7_compares_group_and_individual_quest_adoption():
    sql = BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL.lower()
    assert "public.user_quests" in sql
    assert "public.quests" in sql
    assert "q.is_group" in sql
    assert "'group'" in sql
    assert "'individual'" in sql
    assert "adopting_users" in sql
    assert "adoption_share_pct" in sql


def test_bq7_reports_completion_and_abandonment_metrics():
    sql = BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL.lower()
    assert "completed_attempts" in sql
    assert "abandoned_attempts" in sql
    assert "open_attempts" in sql
    assert "completion_rate_pct" in sql
    assert "resolved_completion_rate_pct" in sql
    assert "abandonment_rate_pct" in sql
    assert "median_minutes_to_complete" in sql
    assert "average_rating" in sql


def test_bq7_reports_users_who_choose_both_quest_types():
    sql = BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL.lower()
    assert "users_with_both_types" in sql
    assert "group_only_users" in sql
    assert "individual_only_users" in sql


def test_bq7_uses_a_30_day_window_and_excludes_skipped_attempts():
    sql = BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL.lower()
    assert "30 days" in sql
    assert "status <> 'skipped'" in sql


def test_bq1_uses_resume_and_failure_events_from_kotlin():
    sql = BQ1_MODULE_FAILURES_AFTER_RESUME_SQL.lower()
    assert "bq1_resume_after_background" in sql
    assert "module_failure" in sql
    assert "metadata->>'bq' = 'bq1'" in sql
    assert "after_long_resume" in sql


def test_bq1_rate_uses_resumes_as_denominator_and_excludes_offline_failures():
    sql = BQ1_MODULE_FAILURES_AFTER_RESUME_SQL.lower()
    assert "long_resumes" in sql
    assert "resume_at_millis" in sql
    assert "online is not false" in sql
    assert "failure_rate_pct" in sql
    assert "nullif(r.long_resumes, 0)" in sql


def test_bq1_ranks_modules_per_app_version_and_uses_device_event_time():
    sql = BQ1_MODULE_FAILURES_AFTER_RESUME_SQL.lower()
    assert "partition by f.app_version" in sql
    assert "module_rank" in sql
    assert "occurred_at_millis" in sql
