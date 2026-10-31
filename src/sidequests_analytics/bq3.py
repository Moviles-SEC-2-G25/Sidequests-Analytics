"""BQ3 v2: initial setup funnel and observational first-recommendation acceptance.

Keep open journeys and immature recommendation outcomes separate from drop-offs
and non-acceptances. Deduplicate deliveries by stable client event ID.
"""
from datetime import datetime, timedelta, timezone
import json
import math

STEPS = {1: "interests", 2: "difficulty", 3: "typical_time", 4: "budget_social"}


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def summarize_bq3(records, *, as_of=None, observation_hours=24.0, cohort_days=30):
    if not math.isfinite(observation_hours) or observation_hours <= 0 or cohort_days <= 0:
        raise ValueError("Observation hours and cohort days must be positive")
    as_of = _time(as_of or datetime.now(timezone.utc))
    horizon = timedelta(hours=observation_hours)
    events, seen = [], set()
    for record in records:
        metadata = record.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                continue
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("schema_version")) != "2" or metadata.get("bq_key") != "BQ3" or metadata.get("platform") != "kotlin":
            continue
        user, journey, event_id = record.get("user_id"), metadata.get("onboarding_id"), metadata.get("event_id")
        sequence = metadata.get("event_sequence")
        if not user or not journey or not event_id or type(sequence) is not int or sequence < 1:
            continue
        if str(record.get("session_id")) != str(journey):
            continue
        key = (str(user), str(journey), str(event_id))
        if key in seen:
            continue
        try:
            occurred_at = _time(record["occurred_at"])
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        if occurred_at > as_of:
            continue
        seen.add(key)
        events.append(dict(record, user=str(user), journey=str(journey), meta=metadata,
                           time=occurred_at, sequence=sequence))

    # Only each user's earliest instrumented initial setup belongs to the cohort.
    starts = {}
    for event in sorted(events, key=lambda e: (e["time"], e["sequence"], e["journey"])):
        if event["event_type"] == "onboarding_started":
            starts.setdefault(event["user"], event)
    journeys = []
    for user, start in starts.items():
        if start["time"] < as_of - timedelta(days=cohort_days):
            continue
        group = sorted((e for e in events if e["user"] == user and e["journey"] == start["journey"]),
                       key=lambda e: (e["sequence"], e["time"]))
        viewed, completed = set(), set()
        skipped_at = None
        ended = False
        last_activity = start["time"]
        first = None
        for event in group:
            if event["sequence"] < start["sequence"]:
                continue
            kind, step = event["event_type"], event["meta"].get("step_order")
            valid_step = type(step) is int and step in STEPS
            if kind in {"onboarding_started", "onboarding_resumed", "onboarding_step_viewed", "onboarding_step_completed"}:
                last_activity = max(last_activity, event["time"])
            if kind == "onboarding_step_viewed" and valid_step and not ended:
                viewed.add(step)
            elif kind == "onboarding_step_completed" and valid_step and step in viewed and not ended:
                completed.add(step)
            elif kind == "onboarding_skipped" and valid_step and not ended:
                skipped_at, ended = step, True
            elif kind == "onboarding_completed" and completed == set(STEPS):
                ended = True
            elif kind == "onboarding_first_recommendation_shown" and first is None and ended:
                if event.get("quest_id") and event["meta"].get("exposure_id"):
                    first = dict(event, completed_at_exposure=set(completed))
        accepted = False
        mature = first is not None and first["time"] + horizon <= as_of
        if first is not None:
            accepted = any(
                e["event_type"] == "onboarding_first_recommendation_accepted"
                and e.get("quest_id") == first["quest_id"]
                and e["meta"].get("exposure_id") == first["meta"]["exposure_id"]
                and e["sequence"] > first["sequence"]
                and first["time"] <= e["time"] <= first["time"] + horizon
                for e in group
            )
        inactive_at = None
        if not ended and last_activity + horizon <= as_of:
            unfinished = viewed - completed
            inactive_at = max(unfinished) if unfinished else None
        journeys.append(dict(viewed=viewed, completed=completed, skipped_at=skipped_at,
                             inactive_at=inactive_at, first=first, mature=mature, accepted=accepted))

    def rate(numerator, denominator):
        return round(100.0 * numerator / denominator, 2) if denominator else None

    rows = []
    for step, name in STEPS.items():
        reached = sum(step in j["viewed"] for j in journeys)
        completed = sum(step in j["completed"] for j in journeys)
        skipped = sum(j["skipped_at"] == step for j in journeys)
        inactive = sum(j["inactive_at"] == step for j in journeys)
        row = dict(schema_version=2, platform="kotlin", step_order=step, step_name=name,
                   cohort_started_from=(as_of - timedelta(days=cohort_days)).isoformat(),
                   as_of=as_of.isoformat(), observation_hours=observation_hours,
                   journeys_started=len(journeys), journeys_reached=reached,
                   journeys_completed=completed, explicit_skip_count=skipped,
                   inactivity_dropoff_count=inactive, dropoff_count=skipped + inactive,
                   pending_at_step=max(0, reached - completed - skipped - inactive),
                   resolved_step_journeys=completed + skipped + inactive,
                   dropoff_rate_pct=rate(skipped + inactive, completed + skipped + inactive))
        rates = []
        for label, did_complete in (("completed_step", True), ("not_completed_step", False)):
            exposed = [j for j in journeys if j["first"] is not None
                       and (step in j["first"]["completed_at_exposure"]) == did_complete]
            eligible = [j for j in exposed if j["mature"]]
            accepted = sum(j["accepted"] for j in eligible)
            row[f"{label}_first_shown"] = len(exposed)
            row[f"{label}_pending_outcomes"] = len(exposed) - len(eligible)
            row[f"{label}_eligible_first_shown"] = len(eligible)
            row[f"{label}_first_accepted"] = accepted
            row[f"{label}_acceptance_rate_pct"] = rate(accepted, len(eligible))
            rates.append(row[f"{label}_acceptance_rate_pct"])
        row["acceptance_difference_pp"] = round(rates[0] - rates[1], 2) if all(r is not None for r in rates) else None
        rows.append(row)
    return rows
