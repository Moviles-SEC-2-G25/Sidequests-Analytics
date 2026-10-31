"""SQL used by the first implemented Sprint 2 analytics jobs.

BQ9 is a Type 3 per-category funnel. Acceptance comes from
`recommendation_shown` / `recommendation_accepted` / `recommendation_skipped`
events (linked by user + session + quest, like BQ8); completion and abandonment
come from `user_quests` attempts. No extra metadata contract is needed.
BQ6 covers abandonment reason, duration, cost and distance, per platform. Reason
codes are normalized to Kotlin's, and distance comes from the `quest_abandoned`
event linked by attempt_id. The two platforms measure distance differently:
Kotlin uses the catalogue distance and Flutter the GPS distance from the user to
the quest (`quest_distance_source`), so a shared band doesn't mean a shared
measurement. Events without a band get `legacy_gps_*` buckets, and abandonments
without a matching event fall in 'unknown'.
BQ3 v2 uses explicit step views/completions/skips and first-recommendation
exposure/acceptance events. The Python aggregation preserves pending outcomes
and excludes legacy events that cannot establish the second half of BQ3.
BQ8 is a Type 3 experiment (control vs diverse arm of `public.recommend_quests`).
It relies on `metadata.variant` / `metadata.batch_id` / `metadata.rank` of
`recommendation_shown` events (docs/EVENT_SCHEMA.md); events without them fall
back to variant 'unassigned' and a session/second batch key.
BQ4 compares the "instant plan" quick-start path against the standard flow.
It relies on `metadata.start_path` / `metadata.seconds_to_start` /
`metadata.interactions_to_start` on `recommendation_accepted` and
`quest_started` events (docs/EVENT_SCHEMA.md); events without `start_path`
are ignored.
BQ1 (Type 1, app telemetry) ranks the app modules that fail most often after the
user returns to the app after >10 minutes in the background with an active Nearby
quest. It relies on the Kotlin events `bq1_resume_after_background` and
`module_failure` (metadata: bq='BQ1', module, fatal, after_long_resume, online,
app_version, resume_at_millis, occurred_at_millis). Events are queued offline on
the phone, so the event time comes from `occurred_at_millis` when present.
"""

# BQ3 v2 reads complete journeys; aggregation and outcome censoring live in bq3.py.
# Do not limit events by time here: that would truncate journeys and misclassify
# returning users. summarize_bq3 selects first-start cohorts within the last 30 days.
BQ3_ONBOARDING_DROPOFF_SQL = """
select id, user_id, session_id, event_type, quest_id, occurred_at, metadata
from public.analytics_events
where metadata->>'bq_key' = 'BQ3'
  and metadata->>'platform' = 'kotlin'
  and cast(metadata->>'schema_version' as text) = '2'
  and user_id is not null
  and session_id is not null
order by occurred_at, id;
"""

BQ9_CATEGORY_PERFORMANCE_SQL = """
with shown as (
    -- one impression per user/session/quest: list reloads (filter changes,
    -- "Not for me") must not inflate the acceptance denominator
    select
        ae.user_id,
        ae.session_id,
        ae.quest_id,
        q.category,
        min(ae.occurred_at) as first_shown_at
    from public.analytics_events ae
    join public.quests q on q.id = ae.quest_id
    where ae.event_type = 'recommendation_shown'
      and ae.occurred_at >= now() - interval '30 days'
    group by ae.user_id, ae.session_id, ae.quest_id, q.category
),
shown_outcomes as (
    -- linked like BQ8: same user + session + quest
    select
        s.category,
        exists (
            select 1
            from public.analytics_events a
            where a.event_type = 'recommendation_accepted'
              and a.user_id = s.user_id
              and a.session_id is not distinct from s.session_id
              and a.quest_id = s.quest_id
              and a.occurred_at >= s.first_shown_at
              and a.occurred_at < s.first_shown_at + interval '1 day'
        ) as was_accepted,
        exists (
            select 1
            from public.analytics_events k
            where k.event_type = 'recommendation_skipped'
              and k.user_id = s.user_id
              and k.session_id is not distinct from s.session_id
              and k.quest_id = s.quest_id
              and k.occurred_at >= s.first_shown_at
              and k.occurred_at < s.first_shown_at + interval '1 day'
        ) as was_skipped
    from shown s
),
recommendation_funnel as (
    select
        category,
        count(*) as recommendations_shown,
        count(*) filter (where was_accepted) as recommendations_accepted,
        count(*) filter (where was_skipped) as recommendations_skipped
    from shown_outcomes
    group by category
),
attempts as (
    -- every accept inserts a new user_quests row, so one row = one attempt,
    -- whether it came from a recommendation or from the catalogue
    select
        q.category,
        uq.status,
        uq.rating,
        uq.accepted_at,
        uq.completed_at
    from public.user_quests uq
    join public.quests q on q.id = uq.quest_id
    where uq.accepted_at >= now() - interval '30 days'
      and uq.status <> 'skipped'
),
attempt_funnel as (
    select
        category,
        count(*) as accepted_count,
        count(*) filter (where status = 'completed') as completed_count,
        count(*) filter (where status = 'abandoned') as abandoned_count,
        count(*) filter (where status in ('accepted', 'in_progress')) as open_count,
        round(
            (
                percentile_cont(0.5) within group (
                    order by extract(epoch from (completed_at - accepted_at)) / 60
                ) filter (where status = 'completed' and completed_at is not null)
            )::numeric,
            1
        ) as median_minutes_to_complete,
        round(avg(rating) filter (where status = 'completed'), 2) as avg_rating
    from attempts
    group by category
),
per_category as (
    select
        category,
        coalesce(rf.recommendations_shown, 0) as recommendations_shown,
        coalesce(rf.recommendations_accepted, 0) as recommendations_accepted,
        coalesce(rf.recommendations_skipped, 0) as recommendations_skipped,
        coalesce(af.accepted_count, 0) as accepted_count,
        coalesce(af.completed_count, 0) as completed_count,
        coalesce(af.abandoned_count, 0) as abandoned_count,
        coalesce(af.open_count, 0) as open_count,
        af.median_minutes_to_complete,
        af.avg_rating,
        100.0 * rf.recommendations_accepted
            / nullif(rf.recommendations_shown, 0) as acceptance_rate,
        100.0 * rf.recommendations_skipped
            / nullif(rf.recommendations_shown, 0) as skip_rate,
        100.0 * af.completed_count / nullif(af.accepted_count, 0) as completion_rate,
        100.0 * af.completed_count
            / nullif(af.completed_count + af.abandoned_count, 0) as resolved_completion_rate,
        100.0 * af.abandoned_count / nullif(af.accepted_count, 0) as abandonment_rate
    from recommendation_funnel rf
    full outer join attempt_funnel af using (category)
),
overall as (
    -- baseline every category is compared against
    select
        (
            select 100.0 * count(*) filter (where was_accepted) / nullif(count(*), 0)
            from shown_outcomes
        ) as overall_acceptance_rate,
        (
            select 100.0 * count(*) filter (where status = 'completed') / nullif(count(*), 0)
            from attempts
        ) as overall_completion_rate
)
select
    pc.category,
    pc.recommendations_shown,
    pc.recommendations_accepted,
    pc.recommendations_skipped,
    round(pc.acceptance_rate, 2) as recommendation_acceptance_rate_pct,
    round(pc.skip_rate, 2) as recommendation_skip_rate_pct,
    pc.accepted_count,
    pc.completed_count,
    pc.abandoned_count,
    pc.open_count,
    round(pc.completion_rate, 2) as completion_rate_pct,
    round(pc.resolved_completion_rate, 2) as resolved_completion_rate_pct,
    round(pc.abandonment_rate, 2) as abandonment_rate_pct,
    pc.median_minutes_to_complete,
    pc.avg_rating,
    round(pc.acceptance_rate - o.overall_acceptance_rate, 2) as acceptance_rate_vs_overall_pp,
    round(pc.completion_rate - o.overall_completion_rate, 2) as completion_rate_vs_overall_pp
from per_category pc
cross join overall o
order by
    completion_rate_pct desc nulls last,
    recommendation_acceptance_rate_pct desc nulls last,
    pc.category;
"""

BQ5_PERSONALIZED_RECOMMENDATION_SQL = """
with shown as (
    select
        ae.user_id,
        ae.session_id,
        ae.quest_id,
        ae.available_minutes,
        ae.social_level,
        ae.location_mode,
        ae.occurred_at,
        coalesce((ae.metadata->>'rank')::int, 999) as rank_position,
        coalesce(
            ae.metadata->>'batch_id',
            ae.session_id::text || '|' || date_trunc('second', ae.occurred_at)::text
        ) as batch_id,
        q.title,
        q.category,
        q.duration_minutes
    from public.analytics_events ae
    join public.quests q on q.id = ae.quest_id
    where ae.event_type = 'recommendation_shown'
      and ae.quest_id is not null
),
latest_batch as (
    select distinct on (user_id, session_id)
        user_id,
        session_id,
        batch_id,
        max(occurred_at) over (partition by user_id, session_id, batch_id) as batch_time
    from shown
    order by user_id, session_id, batch_time desc
)
select
    s.user_id,
    s.session_id,
    s.batch_id,
    s.rank_position,
    s.quest_id,
    s.title,
    s.category,
    s.duration_minutes,
    s.available_minutes,
    s.social_level,
    s.location_mode,
    s.occurred_at
from shown s
join latest_batch lb
  on lb.user_id = s.user_id
 and lb.session_id is not distinct from s.session_id
 and lb.batch_id = s.batch_id
where s.rank_position <= 3
order by s.user_id, s.session_id, s.rank_position;
"""

BQ6_ABANDONMENT_BASE_SQL = """
with attempts as (
    select
        -- Old Flutter codes count as Kotlin's. A null reason stays apart: it's
        -- unknown data, not a user who chose "other".
        case uq.abandon_reason
            when 'place_closed' then 'place_unavailable'
            when 'too_hard' then 'too_difficult'
            when 'bad_weather' then 'weather_or_mood_changed'
            when 'lost_interest' then 'other'
            when 'not_specified' then 'other'
            else coalesce(uq.abandon_reason, 'Unspecified')
        end as abandon_reason,
        q.duration_minutes,
        q.estimated_cost,
        ev.distance_meters,
        ev.metadata
    from public.user_quests uq
    join public.quests q on q.id = uq.quest_id
    left join lateral (
        -- This attempt's quest_abandoned event, by attempt_id. Old events don't
        -- have one and fall back to the closest in time, but an event naming
        -- another attempt is never this attempt's.
        select ae.distance_meters, ae.metadata
        from public.analytics_events ae
        where ae.event_type = 'quest_abandoned'
          and ae.user_id = uq.user_id
          and ae.quest_id = uq.quest_id
          and (
              ae.metadata->>'attempt_id' is null
              or ae.metadata->>'attempt_id' = cast(uq.id as text)
          )
        order by
            (ae.metadata->>'attempt_id') is not null desc,
            -- user_quests keeps the first abandoned_at if an attempt is resumed
            -- and abandoned again: for its own events, the latest one counts.
            case when ae.metadata->>'attempt_id' is not null then ae.occurred_at end desc nulls last,
            abs(extract(epoch from (ae.occurred_at - uq.abandoned_at))) nulls last,
            ae.id desc
        limit 1
    ) ev on true
    where uq.status = 'abandoned'
),
classified as (
    select
        abandon_reason,
        duration_minutes,
        estimated_cost,
        -- Kotlin measures the catalogue distance and Flutter the GPS distance
        -- from the user to the quest (see distance_source). Events without a band
        -- are older and only had distance_meters: GPS for Flutter, so they stay
        -- in their own legacy_gps_* buckets instead of mixing with the bands.
        coalesce(
            nullif(metadata->>'quest_distance_band', ''),
            case
                when distance_meters is null then 'unknown'
                when distance_meters < 500 then 'legacy_gps_under_500_m'
                when distance_meters < 2000 then 'legacy_gps_500_m_to_2_km'
                when distance_meters < 10000 then 'legacy_gps_2_km_to_10_km'
                else 'legacy_gps_over_10_km'
            end
        ) as distance_bucket,
        -- Flutter says so. Kotlin doesn't send it, but only its contract has
        -- schema_version; 'step' only exists on old Flutter events.
        coalesce(
            metadata->>'platform',
            case
                when metadata ? 'schema_version' then 'kotlin'
                when metadata ? 'step' then 'flutter'
                else 'unknown'
            end
        ) as platform,
        metadata->>'quest_distance_source' as distance_source
    from attempts
)
select
    abandon_reason,
    duration_minutes,
    estimated_cost,
    distance_bucket,
    platform,
    coalesce(
        distance_source,
        case platform when 'kotlin' then 'catalogue' when 'flutter' then 'gps' else 'unknown' end
    ) as distance_source,
    count(*) as abandoned_count
from classified
group by 1, 2, 3, 4, 5, 6
order by abandoned_count desc, abandon_reason, distance_bucket, platform;
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

BQ4_INSTANT_PLAN_SQL = """
with starts as (
    select
        ae.metadata->>'start_path' as start_path,
        (ae.metadata->>'seconds_to_start')::numeric as seconds_to_start,
        (ae.metadata->>'interactions_to_start')::numeric as interactions_to_start
    from public.analytics_events ae
    where ae.event_type in ('recommendation_accepted', 'quest_started')
      and ae.metadata ? 'start_path'
),
per_path as (
    select
        start_path,
        count(*) as starts_count,
        round(avg(seconds_to_start), 2) as avg_seconds_to_start,
        round(
            (percentile_cont(0.5) within group (order by seconds_to_start))::numeric,
            2
        ) as median_seconds_to_start,
        round(avg(interactions_to_start), 2) as avg_interactions_to_start
    from starts
    group by start_path
),
baseline as (
    select
        avg_seconds_to_start as standard_avg_seconds,
        avg_interactions_to_start as standard_avg_interactions
    from per_path
    where start_path = 'standard'
)
select
    pp.start_path,
    pp.starts_count,
    pp.avg_seconds_to_start,
    pp.median_seconds_to_start,
    pp.avg_interactions_to_start,
    round(
        100.0 * (b.standard_avg_seconds - pp.avg_seconds_to_start)
        / nullif(b.standard_avg_seconds, 0),
        2
    ) as seconds_reduction_pct_vs_standard,
    round(
        100.0 * (b.standard_avg_interactions - pp.avg_interactions_to_start)
        / nullif(b.standard_avg_interactions, 0),
        2
    ) as interactions_reduction_pct_vs_standard
from per_path pp
cross join baseline b
order by pp.starts_count desc, pp.start_path;
"""

BQ10_LOCATION_INDEPENDENT_USAGE_SQL = """
with mode_events as (
    select
        session_id,
        lower(location_mode) as location_mode,
        event_type,
        lower(coalesce(metadata->>'time_of_day', 'unknown')) as time_of_day,
        lower(coalesce(metadata->>'weather_condition', 'unknown')) as weather_condition,
        occurred_at
    from public.analytics_events
    where event_type in (
        'location_independent_mode_selected',
        'location_based_mode_selected'
    )
      and session_id is not null
      and occurred_at >= now() - interval '30 days'
      and location_mode in ('gps', 'anywhere')
),
session_modes as (
    select
        session_id,
        bool_or(
            event_type = 'location_independent_mode_selected'
            or location_mode = 'anywhere'
        ) as used_location_independent
    from mode_events
    group by session_id
),
overall as (
    select
        'overall' as time_of_day,
        'overall' as weather_condition,
        count(*) as sessions_with_location_mode,
        count(*) filter (where used_location_independent) as location_independent_sessions
    from session_modes
),
context_sessions as (
    select
        session_id,
        time_of_day,
        weather_condition,
        bool_or(
            event_type = 'location_independent_mode_selected'
            or location_mode = 'anywhere'
        ) as used_location_independent
    from mode_events
    group by session_id, time_of_day, weather_condition
),
by_context as (
    select
        time_of_day,
        weather_condition,
        count(*) as sessions_with_location_mode,
        count(*) filter (where used_location_independent) as location_independent_sessions
    from context_sessions
    group by time_of_day, weather_condition
),
results as (
    select
        time_of_day,
        weather_condition,
        sessions_with_location_mode,
        location_independent_sessions,
        round(
            100.0 * location_independent_sessions
            / nullif(sessions_with_location_mode, 0),
            2
        ) as location_independent_usage_pct
    from overall

    union all

    select
        time_of_day,
        weather_condition,
        sessions_with_location_mode,
        location_independent_sessions,
        round(
            100.0 * location_independent_sessions
            / nullif(sessions_with_location_mode, 0),
            2
        ) as location_independent_usage_pct
    from by_context
)
select
    time_of_day,
    weather_condition,
    sessions_with_location_mode,
    location_independent_sessions,
    location_independent_usage_pct
from results
order by
    case when time_of_day = 'overall' then 0 else 1 end,
    time_of_day,
    weather_condition;
"""



BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL = """
with quest_types(quest_type, is_group) as (
    values
        ('group', true),
        ('individual', false)
),
attempts as (
    select
        uq.id,
        uq.user_id,
        case when q.is_group then 'group' else 'individual' end as quest_type,
        uq.status,
        uq.accepted_at,
        uq.completed_at,
        uq.rating
    from public.user_quests uq
    join public.quests q on q.id = uq.quest_id
    where uq.accepted_at >= now() - interval '30 days'
      and uq.status <> 'skipped'
),
type_metrics as (
    select
        quest_type,
        count(*) as accepted_attempts,
        count(distinct user_id) as adopting_users,
        count(*) filter (where status = 'completed') as completed_attempts,
        count(*) filter (where status = 'abandoned') as abandoned_attempts,
        count(*) filter (where status in ('accepted', 'in_progress')) as open_attempts,
        round(
            (
                percentile_cont(0.5) within group (
                    order by extract(epoch from (completed_at - accepted_at)) / 60
                ) filter (where status = 'completed' and completed_at is not null)
            )::numeric,
            1
        ) as median_minutes_to_complete,
        round(avg(rating) filter (where status = 'completed'), 2) as average_rating
    from attempts
    group by quest_type
),
user_adoption as (
    select
        user_id,
        bool_or(quest_type = 'group') as has_group_quest,
        bool_or(quest_type = 'individual') as has_individual_quest
    from (
        select distinct user_id, quest_type
        from attempts
    ) user_quest_types
    group by user_id
),
adoption_summary as (
    select
        count(*) as users_with_any_quest,
        count(*) filter (where has_group_quest and has_individual_quest) as users_with_both_types,
        count(*) filter (where has_group_quest and not has_individual_quest) as group_only_users,
        count(*) filter (where has_individual_quest and not has_group_quest) as individual_only_users
    from user_adoption
)
select
    qt.quest_type,
    coalesce(tm.adopting_users, 0) as adopting_users,
    coalesce(tm.accepted_attempts, 0) as accepted_attempts,
    coalesce(tm.completed_attempts, 0) as completed_attempts,
    coalesce(tm.abandoned_attempts, 0) as abandoned_attempts,
    coalesce(tm.open_attempts, 0) as open_attempts,
    round(
        100.0 * coalesce(tm.adopting_users, 0)
        / nullif(ads.users_with_any_quest, 0),
        2
    ) as adoption_share_pct,
    round(
        100.0 * coalesce(tm.completed_attempts, 0)
        / nullif(tm.accepted_attempts, 0),
        2
    ) as completion_rate_pct,
    round(
        100.0 * coalesce(tm.completed_attempts, 0)
        / nullif(tm.completed_attempts + tm.abandoned_attempts, 0),
        2
    ) as resolved_completion_rate_pct,
    round(
        100.0 * coalesce(tm.abandoned_attempts, 0)
        / nullif(tm.accepted_attempts, 0),
        2
    ) as abandonment_rate_pct,
    tm.median_minutes_to_complete,
    tm.average_rating,
    ads.users_with_any_quest,
    ads.users_with_both_types,
    ads.group_only_users,
    ads.individual_only_users
from quest_types qt
left join type_metrics tm using (quest_type)
cross join adoption_summary ads
order by case qt.quest_type when 'group' then 1 else 2 end;
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


BQ1_MODULE_FAILURES_AFTER_RESUME_SQL = """
with bq1_events as (
    select
        event_type,
        session_id,
        coalesce(metadata->>'app_version', 'unknown') as app_version,
        coalesce(metadata->>'module', 'unknown') as module,
        coalesce((metadata->>'fatal')::boolean, false) as fatal,
        coalesce((metadata->>'after_long_resume')::boolean, false) as after_long_resume,
        (metadata->>'online')::boolean as online,
        metadata->>'resume_at_millis' as resume_at_millis,
        coalesce(
            to_timestamp((metadata->>'occurred_at_millis')::bigint / 1000.0),
            occurred_at
        ) as event_time
    from public.analytics_events
    where event_type in ('bq1_resume_after_background', 'module_failure')
      and metadata->>'bq' = 'BQ1'
),
recent as (
    select * from bq1_events
    where event_time >= now() - interval '30 days'
),
resumes as (
    -- denominator: qualifying resumes (>10 min in background, active Nearby quest)
    select app_version, count(distinct session_id || ':' || coalesce(resume_at_millis, '')) as long_resumes
    from recent
    where event_type = 'bq1_resume_after_background'
    group by app_version
),
failures as (
    -- numerator: failures within 5 minutes of such a resume, per module
    select
        app_version,
        module,
        count(*) as failures_after_resume,
        count(*) filter (where fatal) as fatal_failures,
        count(*) filter (where not fatal) as non_fatal_failures,
        count(*) filter (where online is true) as failures_online,
        count(*) filter (where online is false) as failures_offline,
        count(distinct session_id || ':' || coalesce(resume_at_millis, ''))
            filter (where online is not false) as resumes_with_real_failure
    from recent
    where event_type = 'module_failure'
      and after_long_resume
    group by app_version, module
)
select
    f.app_version,
    f.module,
    coalesce(r.long_resumes, 0) as long_resumes,
    f.failures_after_resume,
    f.fatal_failures,
    f.non_fatal_failures,
    f.failures_online,
    f.failures_offline,
    f.resumes_with_real_failure,
    round(100.0 * f.resumes_with_real_failure / nullif(r.long_resumes, 0), 2) as failure_rate_pct,
    rank() over (
        partition by f.app_version
        order by f.resumes_with_real_failure desc, f.fatal_failures desc
    ) as module_rank
from failures f
left join resumes r using (app_version)
order by f.app_version desc, module_rank, f.module;
"""
