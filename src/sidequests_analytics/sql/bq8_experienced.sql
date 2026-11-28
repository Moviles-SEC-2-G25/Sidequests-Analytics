-- BQ8 Sprint 4: experienced users only (>=2 completed BEFORE the exposure).
-- Correlational 30-day window. A new session within 24h is only a return proxy.
-- Read-only; does not alter analytics_events, quests or user_quests.
with arm as (
    select 'control'::text as variant
    union all
    select 'diverse'::text
),
raw_exposures as (
    select
        ae.user_id, ae.session_id, ae.quest_id, q.category, ae.occurred_at,
        ae.metadata->>'variant' as variant,
        coalesce(nullif(ae.metadata->>'batch_id', ''), ae.id::text) as batch_id
    from public.analytics_events ae
    join public.quests q on q.id = ae.quest_id
    where ae.event_type = 'recommendation_shown'
      and ae.metadata->>'variant' in ('control', 'diverse')
      and ae.user_id is not null
      and ae.session_id is not null
      and ae.occurred_at <= now()
      and ae.occurred_at >= now() - interval '30 days'
),
unique_exposures as (
    select distinct on (user_id, session_id, batch_id, quest_id)
        user_id, session_id, quest_id, category, occurred_at, variant, batch_id
    from raw_exposures
    order by user_id, session_id, batch_id, quest_id, occurred_at, variant
),
experienced_exposures as (
    select e.*
    from unique_exposures e
    where (
        select count(distinct uq.id)
        from public.user_quests uq
        where uq.user_id = e.user_id
          and uq.status = 'completed'
          and uq.completed_at is not null
          and uq.completed_at < e.occurred_at
    ) >= 2
),
list_stats as (
    select
        variant, user_id, session_id, batch_id,
        count(*) as visible_items,
        count(distinct category) as unique_categories
    from experienced_exposures
    group by variant, user_id, session_id, batch_id
),
list_summary as (
    select
        variant,
        count(*) as observed_batches,
        count(*) filter (where visible_items >= 2) as comparable_batches,
        round(avg(unique_categories) filter (where visible_items >= 2), 2)
            as avg_distinct_categories_per_list,
        round(avg(unique_categories::numeric / visible_items)
              filter (where visible_items >= 2), 3) as avg_category_diversity_ratio
    from list_stats
    group by variant
),
user_session_quest_first as (
    -- Repeated impressions of one quest in one session are not separate
    -- acceptance opportunities.
    select distinct on (user_id, session_id, quest_id)
        user_id, session_id, quest_id, variant, occurred_at as first_shown_at
    from experienced_exposures
    order by user_id, session_id, quest_id, occurred_at, variant
),
accepted_summary as (
    select
        variant,
        count(*) as distinct_exposed_session_quests,
        count(*) filter (where first_shown_at <= now() - interval '24 hours')
            as mature_acceptance_opportunities,
        count(*) filter (
            where first_shown_at <= now() - interval '24 hours'
              and exists (
                  select 1
                  from public.analytics_events a
                  where a.user_id = s.user_id
                    and a.session_id is not distinct from s.session_id
                    and a.quest_id = s.quest_id
                    and a.event_type = 'recommendation_accepted'
                    and a.occurred_at >= s.first_shown_at
                    and a.occurred_at < s.first_shown_at + interval '24 hours'
              )
        ) as accepted_mature_opportunities
    from user_session_quest_first s
    group by variant
),
first_exposure_per_user as (
    select distinct on (user_id)
        user_id, session_id, variant, occurred_at as first_shown_at
    from experienced_exposures
    order by user_id, occurred_at, session_id, variant
),
return_cohort as (
    select
        variant,
        count(*) as experienced_users,
        count(*) filter (where first_shown_at <= now() - interval '24 hours')
            as mature_return_users,
        count(*) filter (
            where first_shown_at <= now() - interval '24 hours'
              and exists (
                  select 1
                  from public.analytics_events r
                  where r.user_id = f.user_id
                    and r.session_id is not null
                    and r.session_id is distinct from f.session_id
                    and r.occurred_at >= f.first_shown_at + interval '30 minutes'
                    and r.occurred_at < f.first_shown_at + interval '24 hours'
              )
        ) as observed_return_users_24h
    from first_exposure_per_user f
    group by variant
)
select
    arm.variant,
    coalesce(rc.experienced_users, 0) as eligible_users,
    coalesce(ls.observed_batches, 0) as observed_batches,
    coalesce(ls.comparable_batches, 0) as comparable_batches,
    ls.avg_distinct_categories_per_list,
    ls.avg_category_diversity_ratio,
    coalesce(a.distinct_exposed_session_quests, 0) as distinct_exposed_session_quests,
    coalesce(a.mature_acceptance_opportunities, 0) as mature_acceptance_opportunities,
    coalesce(a.accepted_mature_opportunities, 0) as accepted_mature_opportunities,
    round(100.0 * a.accepted_mature_opportunities /
        nullif(a.mature_acceptance_opportunities, 0), 2) as acceptance_rate_pct,
    coalesce(rc.mature_return_users, 0) as mature_return_users,
    coalesce(rc.observed_return_users_24h, 0) as observed_return_users_24h,
    round(100.0 * rc.observed_return_users_24h /
        nullif(rc.mature_return_users, 0), 2) as return_rate_24h_pct
from arm
left join list_summary ls using (variant)
left join accepted_summary a using (variant)
left join return_cohort rc using (variant)
order by arm.variant;
