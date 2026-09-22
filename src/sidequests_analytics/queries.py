"""SQL used by the first implemented Sprint 2 analytics jobs.

BQ9 is fully computable from the current operational schema.
BQ6 currently covers abandonment reason, duration and cost. Distance segmentation
will be added when the mobile Context Manager starts sending distance_meters.
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
