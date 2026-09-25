"""SQL used by the first implemented Sprint 2 analytics jobs.

BQ9 is fully computable from the current operational schema.
BQ6 currently covers abandonment reason, duration and cost. Distance segmentation
will be added when the mobile Context Manager starts sending distance_meters.
BQ3 relies on the `onboarding_step_completed` metadata contract defined in
docs/EVENT_SCHEMA.md (`step_order` int, `step_name` text). No client emits this
event yet, so the query is validated against seeded/synthetic data until Kotlin
and Flutter implement the contract.
BQ8 is a Type 3 experiment (control vs diverse arm of `public.recommend_quests`).
It relies on `metadata.variant` / `metadata.batch_id` / `metadata.rank` of
`recommendation_shown` events (docs/EVENT_SCHEMA.md); events without them fall
back to variant 'unassigned' and a session/second batch key.
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

BQ8_RECOMMENDATION_DIVERSITY_SQL = """
with shown_raw as (
    select
        ae.user_id,
        ae.session_id,
        ae.quest_id,
        q.category,
        ae.occurred_at,
        coalesce(ae.metadata->>'variant', 'unassigned') as variant,
        coalesce(
            ae.metadata->>'batch_id',
            ae.session_id::text || '|' || date_trunc('second', ae.occurred_at)::text,
            ae.id::text
        ) as batch_id
    from public.analytics_events ae
    join public.quests q on q.id = ae.quest_id
    where ae.event_type = 'recommendation_shown'
      and ae.occurred_at >= now() - interval '30 days'
),
shown_dedup as (
    -- one row per quest per recommendation list
    select distinct on (variant, batch_id, user_id, quest_id)
        user_id,
        session_id,
        quest_id,
        category,
        occurred_at,
        variant,
        batch_id,
        date_trunc('week', occurred_at)::date as week_start
    from shown_raw
    order by variant, batch_id, user_id, quest_id, occurred_at
),
shown as (
    select
        sd.*,
        lag(occurred_at) over (
            partition by user_id, quest_id order by occurred_at
        ) as prev_shown_at
    from shown_dedup sd
),
batch_stats as (
    select
        variant,
        week_start,
        batch_id,
        count(*) as list_size,
        count(distinct category) as distinct_categories
    from shown
    group by variant, week_start, batch_id
),
list_diversity as (
    select
        variant,
        week_start,
        count(*) as lists_shown,
        round(avg(distinct_categories), 2) as avg_distinct_categories_per_list,
        round(avg(distinct_categories::numeric / list_size), 3) as avg_category_diversity_ratio
    from batch_stats
    where list_size >= 2
    group by variant, week_start
),
exposure as (
    select
        variant,
        week_start,
        count(*) as impressions,
        count(distinct user_id) as users,
        count(distinct quest_id) as distinct_quests_shown,
        round(
            100.0 * count(*) filter (
                where prev_shown_at is not null
                  and occurred_at - prev_shown_at <= interval '7 days'
            ) / nullif(count(*), 0),
            2
        ) as repeat_exposure_pct
    from shown
    group by variant, week_start
),
category_share as (
    select
        variant,
        week_start,
        category,
        count(*)::numeric / sum(count(*)) over (partition by variant, week_start) as p
    from shown
    group by variant, week_start, category
),
entropy as (
    -- Shannon entropy of shown categories, normalised by the active catalogue's
    -- category count (0 = one category only, 1 = perfectly even spread).
    select
        cs.variant,
        cs.week_start,
        round(
            (-sum(cs.p * ln(cs.p)) / nullif(ln(cat.total_categories), 0))::numeric,
            3
        ) as category_entropy_norm
    from category_share cs
    cross join (
        select count(distinct category)::numeric as total_categories
        from public.quests
        where is_active = true
    ) cat
    group by cs.variant, cs.week_start, cat.total_categories
),
catalog as (
    select count(*)::numeric as active_quests
    from public.quests
    where is_active = true
),
accepted as (
    -- guardrail: accepted recommendations must not collapse under the diverse arm
    select distinct
        s.variant,
        s.week_start,
        s.user_id,
        s.session_id,
        s.quest_id
    from shown s
    join public.analytics_events a
      on a.user_id = s.user_id
     and a.session_id is not distinct from s.session_id
     and a.quest_id = s.quest_id
     and a.event_type = 'recommendation_accepted'
),
acceptance as (
    select
        variant,
        week_start,
        count(*) as accepted_count
    from accepted
    group by variant, week_start
)
select
    e.variant,
    e.week_start,
    e.users,
    coalesce(ld.lists_shown, 0) as lists_shown,
    e.impressions,
    ld.avg_distinct_categories_per_list,
    ld.avg_category_diversity_ratio,
    en.category_entropy_norm,
    e.distinct_quests_shown,
    round(100.0 * e.distinct_quests_shown / nullif(c.active_quests, 0), 2) as catalog_coverage_pct,
    e.repeat_exposure_pct,
    coalesce(a.accepted_count, 0) as accepted_count,
    round(100.0 * coalesce(a.accepted_count, 0) / nullif(e.impressions, 0), 2) as acceptance_rate_pct
from exposure e
left join list_diversity ld using (variant, week_start)
left join entropy en using (variant, week_start)
left join acceptance a using (variant, week_start)
cross join catalog c
order by e.week_start desc, e.variant;
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
