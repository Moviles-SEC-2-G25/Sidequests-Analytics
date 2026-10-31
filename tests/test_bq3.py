from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sidequests_analytics.bq3 import summarize_bq3

NOW = datetime(2026, 10, 29, 18, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=2)


def event(user, kind, sequence, *, step=None, quest=None, exposure=None, when=OLD, journey=None):
    journey = journey or f"journey-{user}"
    metadata = dict(schema_version=2, bq_key="BQ3", platform="kotlin", onboarding_id=journey,
                    event_id=f"{user}-{journey}-{sequence}", event_sequence=sequence)
    if step is not None:
        metadata["step_order"] = step
    if exposure:
        metadata["exposure_id"] = exposure
    return dict(user_id=user, session_id=journey, event_type=kind, quest_id=quest,
                occurred_at=when + timedelta(seconds=sequence), metadata=metadata)


def setup(user, completed, accepted=False, *, when=OLD, shown=True, journey=None):
    result = [event(user, "onboarding_started", 1, when=when, journey=journey)]
    sequence = 2
    for step in range(1, min(completed + 1, 4) + 1):
        result.append(event(user, "onboarding_step_viewed", sequence, step=step, when=when, journey=journey))
        sequence += 1
        if step <= completed:
            result.append(event(user, "onboarding_step_completed", sequence, step=step, when=when, journey=journey))
            sequence += 1
    result.append(event(user, "onboarding_completed" if completed == 4 else "onboarding_skipped",
                        sequence, step=min(completed + 1, 4), when=when, journey=journey))
    if shown:
        result.append(event(user, "onboarding_first_recommendation_shown", sequence + 1,
                            quest="first", exposure="first-exposure", when=when, journey=journey))
        if accepted:
            result.append(event(user, "onboarding_first_recommendation_accepted", sequence + 2,
                                quest="first", exposure="first-exposure", when=when, journey=journey))
    return result


def summarize(records, **kwargs):
    return summarize_bq3(records, as_of=NOW, **kwargs)


def test_both_halves_of_bq3_have_known_independent_denominators():
    records = setup("full-yes", 4, True) + setup("full-no", 4) + setup("skip-yes", 0, True) + setup("skip-no", 0)
    rows = summarize(records)
    assert len(rows) == 4
    assert rows[0]["journeys_started"] == 4
    assert rows[0]["dropoff_count"] == 2
    assert rows[0]["dropoff_rate_pct"] == 50.0
    for row in rows:
        assert row["completed_step_eligible_first_shown"] == 2
        assert row["not_completed_step_eligible_first_shown"] == 2
        assert row["completed_step_acceptance_rate_pct"] == 50.0
        assert row["not_completed_step_acceptance_rate_pct"] == 50.0
        assert row["acceptance_difference_pp"] == 0.0


def test_last_step_abandonment_is_not_lost_like_in_legacy_query():
    rows = summarize(setup("last-step-skip", 3))
    assert rows[3]["explicit_skip_count"] == 1
    assert rows[3]["dropoff_rate_pct"] == 100.0
    assert all(row["dropoff_count"] == 0 for row in rows[:3])


def test_first_step_exit_without_any_completion_is_visible():
    rows = summarize(setup("skip", 0))
    assert rows[0]["journeys_reached"] == 1
    assert rows[0]["journeys_completed"] == 0
    assert rows[0]["dropoff_count"] == 1


def test_killed_app_is_inferred_after_inactivity_horizon():
    records = [event("killed", "onboarding_started", 1), event("killed", "onboarding_step_viewed", 2, step=1)]
    row = summarize(records)[0]
    assert row["inactivity_dropoff_count"] == 1
    assert row["not_completed_step_eligible_first_shown"] == 0
    assert row["not_completed_step_acceptance_rate_pct"] is None


def test_recent_unfinished_setup_is_pending_not_abandoned():
    recent = NOW - timedelta(minutes=5)
    records = [event("active", "onboarding_started", 1, when=recent), event("active", "onboarding_step_viewed", 2, step=1, when=recent)]
    row = summarize(records)[0]
    assert row["inactivity_dropoff_count"] == 0
    assert row["pending_at_step"] == 1
    assert row["dropoff_rate_pct"] is None


def test_recent_first_recommendation_is_censored_even_when_accepted_early():
    records = setup("recent-yes", 4, True, when=NOW - timedelta(minutes=5))
    row = summarize(records)[0]
    assert row["completed_step_first_shown"] == 1
    assert row["completed_step_pending_outcomes"] == 1
    assert row["completed_step_eligible_first_shown"] == 0
    assert row["completed_step_acceptance_rate_pct"] is None


def test_duplicate_deliveries_reordered_rows_and_refreshes_do_not_inflate_metrics():
    records = setup("one", 2, True)
    records += [event("one", "onboarding_first_recommendation_shown", 20, quest="later", exposure="later-exposure"),
                event("one", "onboarding_first_recommendation_accepted", 21, quest="later", exposure="later-exposure")]
    row = summarize(list(reversed(records + records)))[0]
    assert row["journeys_started"] == 1
    assert row["completed_step_eligible_first_shown"] == 1
    assert row["completed_step_first_accepted"] == 1


@pytest.mark.parametrize("quest,exposure,user", [("different", "first-exposure", "one"), ("first", "wrong", "one"), ("first", "first-exposure", "another")])
def test_acceptance_must_match_user_journey_exposure_and_quest(quest, exposure, user):
    records = setup("one", 4)
    records += [event(user, "onboarding_first_recommendation_accepted", 20, quest=quest, exposure=exposure)]
    assert summarize(records)[0]["completed_step_first_accepted"] == 0


def test_acceptance_after_observation_horizon_is_not_attributed():
    records = setup("late", 4)
    records += [event("late", "onboarding_first_recommendation_accepted", 20,
                      quest="first", exposure="first-exposure", when=OLD + timedelta(hours=25))]
    assert summarize(records)[0]["completed_step_first_accepted"] == 0


def test_repeat_setup_for_same_account_is_not_a_second_initial_user():
    records = setup("one", 0, journey="initial") + setup("one", 4, True, when=OLD + timedelta(hours=1), journey="repeat")
    row = summarize(records)[0]
    assert row["journeys_started"] == 1
    assert row["journeys_completed"] == 0
    assert row["not_completed_step_first_accepted"] == 0


def test_missing_exposure_and_legacy_events_are_not_treated_as_rejected_recommendations():
    records = setup("none", 0, shown=False)
    legacy = event("legacy", "onboarding_step_completed", 1, step=1)
    legacy["metadata"].pop("schema_version")
    row = summarize(records + [legacy])[0]
    assert row["journeys_started"] == 1
    assert row["not_completed_step_first_shown"] == 0


def test_zero_data_preserves_all_four_steps_and_null_rates():
    rows = summarize([])
    assert [r["step_order"] for r in rows] == [1, 2, 3, 4]
    assert all(r["dropoff_rate_pct"] is None and r["acceptance_difference_pp"] is None for r in rows)


def test_old_initial_setup_is_not_recounted_when_user_returns_in_window():
    records = setup("old", 0, when=NOW - timedelta(days=40), journey="initial")
    records += setup("old", 4, True, when=OLD, journey="return")
    assert summarize(records)[0]["journeys_started"] == 0


def test_demo_horizon_is_explicit_in_output_and_changes_maturity():
    records = setup("demo", 4, True, when=NOW - timedelta(minutes=5))
    row = summarize(records, observation_hours=1 / 60)[0]
    assert row["completed_step_first_accepted"] == 1
    assert row["observation_hours"] == 1 / 60


def test_resuming_an_unfinished_setup_refreshes_activity_without_an_extra_user():
    records = [event("resume", "onboarding_started", 1),
               event("resume", "onboarding_step_viewed", 2, step=1),
               event("resume", "onboarding_resumed", 3, step=1, when=NOW - timedelta(minutes=2))]
    row = summarize(records)[0]
    assert row["journeys_started"] == 1
    assert row["journeys_reached"] == 1
    assert row["inactivity_dropoff_count"] == 0
    assert row["pending_at_step"] == 1


def test_platforms_with_an_unmapped_step_taxonomy_are_not_mixed_into_kotlin():
    records = setup("other", 4, True)
    for record in records:
        record["metadata"]["platform"] = "flutter"
    assert summarize(records)[0]["journeys_started"] == 0


@pytest.mark.parametrize("hours", [0, -1, float("nan"), float("inf")])
def test_invalid_horizon_is_rejected(hours):
    with pytest.raises(ValueError):
        summarize([], observation_hours=hours)


def test_source_sql_and_pipeline_execute_against_fixture_database():
    import json
    from sqlalchemy import create_engine, text
    from sidequests_analytics.pipeline import compute_bq3
    engine = create_engine("sqlite://")
    records = setup("full", 4, True) + setup("skip", 0)
    with engine.begin() as conn:
        conn.execute(text("attach database ':memory:' as public"))
        conn.execute(text("create table public.analytics_events (id integer primary key, user_id text, session_id text, event_type text, quest_id text, occurred_at text, metadata text)"))
        for index, record in enumerate(records):
            conn.execute(text("insert into public.analytics_events values (:id, :user_id, :session_id, :event_type, :quest_id, :occurred_at, :metadata)"),
                         dict(record, id=index, occurred_at=record["occurred_at"].isoformat(), metadata=json.dumps(record["metadata"])))
    result = compute_bq3(engine, as_of=NOW)
    assert result == summarize(records)
