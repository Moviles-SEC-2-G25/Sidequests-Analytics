"""SQL used by the first implemented Sprint 2 analytics jobs.

BQ9 is fully computable from the current operational schema.
BQ6 currently covers abandonment reason, duration and cost. Distance segmentation
will be added when the mobile Context Manager starts sending distance_meters.
BQ3 relies on the `onboarding_step_completed` metadata contract defined in
docs/EVENT_SCHEMA.md (`step_order` int, `step_name` text). No client emits this
event yet, so the query is validated against seeded/synthetic data until Kotlin
and Flutter implement the contract.
"""

BQ3_ONBOARDING_DROPOFF_SQL = """
with steps as (
    select
        session_id,
        (metadata->>'step_order')::int as step_order,
        metadata->>'step_name' as step_name,
        occurred_at
    from public.analytics_events
    where event_type = 'onboarding_step_completed'
      and session_id is not null
      and metadata ? 'step_order'
),
first_completion as (
    -- collapse repeat/duplicate completions of the same step in a session
    select distinct on (session_id, step_order)
        session_id,
        step_order,
        step_name
    from steps
    order by session_id, step_order, occurred_at
),
step_labels as (
    select
        step_order,
        mode() within group (order by step_name) as step_name
    from first_completion
    group by step_order
),
reached as (
    select step_order, count(distinct session_id) as sessions_reached
    from first_completion
    group by step_order
),
funnel as (
    select
        r.step_order,
        sl.step_name,
        r.sessions_reached,
        lead(r.sessions_reached) over (order by r.step_order) as sessions_reached_next_step
    from reached r
    join step_labels sl using (step_order)
)
select
    step_order,
    step_name,
    sessions_reached,
    sessions_reached_next_step,
    round(
        100.0 * (sessions_reached - sessions_reached_next_step)
        / nullif(sessions_reached, 0),
        2
    ) as dropoff_rate_pct
from funnel
where sessions_reached_next_step is not null
order by dropoff_rate_pct desc nulls last, step_order;
"""

BQ9_CATEGORY_PERFORMANCE_SQL = """
with accepted as (
    select
        uq.id,
        q.category,
        uq.status
    from public.user_quests uq
    join public.quests q on q.id = uq.quest_id
    where uq.accepted_at >= now() - interval '30 days'
)
select
    category,
    count(*) as accepted_count,
    count(*) filter (where status = 'completed') as completed_count,
    round(
        100.0 * count(*) filter (where status = 'completed')
        / nullif(count(*), 0),
        2
    ) as completion_rate_pct
from accepted
group by category
order by completion_rate_pct asc nulls last, category;
"""

BQ6_ABANDONMENT_BASE_SQL = """
select
    coalesce(uq.abandon_reason, 'Unspecified') as abandon_reason,
    q.duration_minutes,
    q.estimated_cost,
    count(*) as abandoned_count
from public.user_quests uq
join public.quests q on q.id = uq.quest_id
where uq.status = 'abandoned'
group by
    coalesce(uq.abandon_reason, 'Unspecified'),
    q.duration_minutes,
    q.estimated_cost
order by abandoned_count desc, abandon_reason;
"""

USER_FEATURES_SQL = """
with per_user as (
    select
        uq.user_id,
        array_remove(
            array_agg(distinct q.category)
                filter (where uq.status = 'completed'),
            null
        ) as preferred_categories,
        avg(q.duration_minutes)
            filter (where uq.status = 'completed') as avg_completed_duration_minutes,
        count(*) filter (where uq.status = 'completed')::numeric
            / nullif(count(*), 0) as completion_rate
    from public.user_quests uq
    join public.quests q on q.id = uq.quest_id
    group by uq.user_id
)
select
    user_id,
    coalesce(preferred_categories, '{}'::text[]) as preferred_categories,
    avg_completed_duration_minutes,
    completion_rate
from per_user;
"""
