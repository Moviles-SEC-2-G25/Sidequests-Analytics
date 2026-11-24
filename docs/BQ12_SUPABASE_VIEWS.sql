-- BQ12 chart-ready views for the Supabase dashboard (docs/BQ12_SUPABASE_DASHBOARD.md).
--
-- Run once in the Supabase SQL Editor, after Sidequests-Backend migration 010 is
-- applied and the `bq12` pipeline job has stored at least one BQ12 / BQ12_WEEKLY
-- result. Safe to run again (create or replace).
--
-- The views only reshape the latest stored result in analytics.bq_results:
-- aggregated counts and rates, no user ids, no events, no interests per person.
-- They run with the caller's privileges (security_invoker) and anon/authenticated
-- get nothing; the `analytics` schema is not exposed through the Data API.
--
-- Supabase charts take one X column and up to three Y columns, with no
-- "series" column, so comparisons come pivoted: one column per sponsor type.

-- Base: every row of the latest BQ12 result, typed.
create or replace view analytics.bq12_latest
with (security_invoker = true) as
select
    latest.computed_at,
    r.*
from (
    select computed_at, payload
    from analytics.bq_results
    where bq_key = 'BQ12'
    order by computed_at desc, id desc
    limit 1
) latest
cross join lateral jsonb_to_recordset(latest.payload -> 'rows') as r(
    segment_level text,
    sponsor_type text,
    business_category text,
    quest_category text,
    interest text,
    interest_match text,
    impressions integer,
    accepted_impressions integer,
    exposed_users integer,
    acceptance_rate_pct numeric,
    accepted_attempts integer,
    completed_attempts integer,
    abandoned_attempts integer,
    open_attempts integer,
    attempting_users integer,
    completion_rate_pct numeric,
    resolved_completion_rate_pct numeric,
    abandonment_rate_pct numeric,
    acceptance_sample_ok boolean,
    completion_sample_ok boolean,
    acceptance_rate_vs_non_sponsored_pp numeric,
    completion_rate_vs_non_sponsored_pp numeric,
    window_days integer,
    min_impressions integer,
    min_attempts integer
);

-- Base: every row of the latest BQ12_WEEKLY result, typed.
create or replace view analytics.bq12_weekly_latest
with (security_invoker = true) as
select
    latest.computed_at,
    r.*
from (
    select computed_at, payload
    from analytics.bq_results
    where bq_key = 'BQ12_WEEKLY'
    order by computed_at desc, id desc
    limit 1
) latest
cross join lateral jsonb_to_recordset(latest.payload -> 'rows') as r(
    week_start date,
    sponsor_type text,
    impressions integer,
    accepted_impressions integer,
    exposed_users integer,
    acceptance_rate_pct numeric,
    accepted_attempts integer,
    completed_attempts integer,
    abandoned_attempts integer,
    open_attempts integer,
    attempting_users integer,
    completion_rate_pct numeric,
    resolved_completion_rate_pct numeric,
    abandonment_rate_pct numeric,
    acceptance_sample_ok boolean,
    completion_sample_ok boolean,
    trend_weeks integer,
    min_impressions integer,
    min_attempts integer
);

-- (a) Sponsored vs non-sponsored, global. Chart: bars, X = sponsor_type,
--     Y = acceptance_rate_pct, completion_rate_pct.
create or replace view analytics.bq12_overall
with (security_invoker = true) as
select
    sponsor_type,
    acceptance_rate_pct,
    completion_rate_pct,
    resolved_completion_rate_pct,
    abandonment_rate_pct,
    acceptance_rate_vs_non_sponsored_pp,
    completion_rate_vs_non_sponsored_pp,
    impressions,
    accepted_impressions,
    exposed_users,
    accepted_attempts,
    completed_attempts,
    attempting_users,
    acceptance_sample_ok,
    completion_sample_ok,
    computed_at
from analytics.bq12_latest
where segment_level = 'overall'
order by case sponsor_type when 'sponsored' then 1 else 2 end;

-- (b) By sponsor business category; `none` is the non-sponsored baseline and
--     `unspecified` a sponsored quest without a category. Chart: bars,
--     X = business_category, Y = acceptance_rate_pct, completion_rate_pct.
create or replace view analytics.bq12_by_business_category
with (security_invoker = true) as
select
    business_category,
    sponsor_type,
    acceptance_rate_pct,
    completion_rate_pct,
    acceptance_rate_vs_non_sponsored_pp,
    completion_rate_vs_non_sponsored_pp,
    impressions,
    accepted_impressions,
    exposed_users,
    accepted_attempts,
    completed_attempts,
    attempting_users,
    acceptance_sample_ok,
    completion_sample_ok,
    computed_at
from analytics.bq12_latest
where segment_level = 'business_category'
order by case business_category when 'none' then 1 else 0 end, business_category;

-- (c) By declared interest, sponsored and non-sponsored side by side. A user
--     with several interests counts in each one: rows don't add up.
--     Charts: bars, X = interest, Y = sponsored_acceptance_rate_pct,
--     non_sponsored_acceptance_rate_pct (same for completion).
create or replace view analytics.bq12_by_interest
with (security_invoker = true) as
select
    interest,
    max(acceptance_rate_pct) filter (where sponsor_type = 'sponsored') as sponsored_acceptance_rate_pct,
    max(acceptance_rate_pct) filter (where sponsor_type = 'non_sponsored') as non_sponsored_acceptance_rate_pct,
    max(completion_rate_pct) filter (where sponsor_type = 'sponsored') as sponsored_completion_rate_pct,
    max(completion_rate_pct) filter (where sponsor_type = 'non_sponsored') as non_sponsored_completion_rate_pct,
    max(acceptance_rate_vs_non_sponsored_pp) filter (where sponsor_type = 'sponsored') as acceptance_rate_vs_non_sponsored_pp,
    max(completion_rate_vs_non_sponsored_pp) filter (where sponsor_type = 'sponsored') as completion_rate_vs_non_sponsored_pp,
    coalesce(max(impressions) filter (where sponsor_type = 'sponsored'), 0) as sponsored_impressions,
    coalesce(max(impressions) filter (where sponsor_type = 'non_sponsored'), 0) as non_sponsored_impressions,
    coalesce(max(accepted_attempts) filter (where sponsor_type = 'sponsored'), 0) as sponsored_attempts,
    coalesce(max(accepted_attempts) filter (where sponsor_type = 'non_sponsored'), 0) as non_sponsored_attempts,
    max(computed_at) as computed_at
from analytics.bq12_latest
where segment_level = 'interest'
group by interest
order by interest;

-- (d) Business category x declared interest. `none` rows are the non-sponsored
--     baseline of each interest. Supabase has no heatmap: chart the sponsored
--     rows as bars, X = segment_label, Y = acceptance_rate_vs_non_sponsored_pp
--     (and completion), or read it as a table. The heatmap is in Streamlit.
create or replace view analytics.bq12_by_category_interest
with (security_invoker = true) as
select
    business_category,
    interest,
    business_category || ' · ' || interest as segment_label,
    sponsor_type,
    acceptance_rate_pct,
    completion_rate_pct,
    acceptance_rate_vs_non_sponsored_pp,
    completion_rate_vs_non_sponsored_pp,
    impressions,
    accepted_impressions,
    accepted_attempts,
    completed_attempts,
    acceptance_sample_ok,
    completion_sample_ok,
    computed_at
from analytics.bq12_latest
where segment_level = 'business_category_x_interest'
order by case business_category when 'none' then 1 else 0 end, business_category, interest;

-- (e) Weekly trend. A week without exposure has null rates (a gap in the line).
--     Recent weeks still have open attempts: their completion is provisional.
--     Chart: line, X = week_start, Y = sponsored_acceptance_rate_pct,
--     non_sponsored_acceptance_rate_pct (same for completion).
create or replace view analytics.bq12_weekly_trend
with (security_invoker = true) as
select
    week_start,
    max(acceptance_rate_pct) filter (where sponsor_type = 'sponsored') as sponsored_acceptance_rate_pct,
    max(acceptance_rate_pct) filter (where sponsor_type = 'non_sponsored') as non_sponsored_acceptance_rate_pct,
    max(completion_rate_pct) filter (where sponsor_type = 'sponsored') as sponsored_completion_rate_pct,
    max(completion_rate_pct) filter (where sponsor_type = 'non_sponsored') as non_sponsored_completion_rate_pct,
    coalesce(max(impressions) filter (where sponsor_type = 'sponsored'), 0) as sponsored_impressions,
    coalesce(max(impressions) filter (where sponsor_type = 'non_sponsored'), 0) as non_sponsored_impressions,
    coalesce(max(accepted_attempts) filter (where sponsor_type = 'sponsored'), 0) as sponsored_attempts,
    coalesce(max(accepted_attempts) filter (where sponsor_type = 'non_sponsored'), 0) as non_sponsored_attempts,
    max(computed_at) as computed_at
from analytics.bq12_weekly_latest
group by week_start
order by week_start;

-- Nobody but the database owner (the SQL Editor's role) reads them. Grant
-- select explicitly to a dedicated read-only role if an external tool connects.
revoke all on
    analytics.bq12_latest,
    analytics.bq12_weekly_latest,
    analytics.bq12_overall,
    analytics.bq12_by_business_category,
    analytics.bq12_by_interest,
    analytics.bq12_by_category_interest,
    analytics.bq12_weekly_trend
from public, anon, authenticated;
