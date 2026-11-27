# Sprint 2 Business Questions

## BQ1 — Module Failures After a Long Resume (Sprint 3, Kotlin)
**Type 1 (app telemetry)**

At what specific software module does the app most frequently crash when a user brings the app back to the foreground after tracking a location-based quest in the background for more than 10 minutes?

- **Denominator:** `bq1_resume_after_background` events — resumes after >10 min in the background with an active Nearby quest (the app does not use background GPS, so "tracking" means an accepted, unfinished Nearby quest).
- **Numerator:** `module_failure` events with `after_long_resume = true` (within 5 minutes of the resume), fatal or non-fatal, per module.
- **Rate:** `failure_rate_pct` = resumes with at least one failure of the module while online ÷ long resumes, per app version. Failures while offline are reported separately (`failures_offline`) and excluded from the rate, because they are expected rather than bugs.
- **Decision supported:** which module the team fixes first to make the resume after a Nearby quest reliable, and whether a release reduced that module's rate.

Computed by `BQ1_MODULE_FAILURES_AFTER_RESUME_SQL` (last 30 days) and stored as `BQ1` in `analytics.bq_results`. Event contract: `docs/EVENT_SCHEMA.md`.

## BQ3 — Onboarding Drop-off
**Type 2**

At which step of the initial preference setup do users most frequently abandon
the process, and how does completing each step relate to acceptance of their
first recommended Side-Quest?

Sprint 3 Kotlin v2 measures all four steps, distinguishes explicit Skip from
inferred inactivity, and compares first-recommendation acceptance between step
completers and non-completers. The normal observation horizon is 24 hours;
recent exposures remain pending. See [BQ3_V2.md](BQ3_V2.md) for the event contract,
denominators and live demonstration status. These are observational associations,
not causal effects of completing a step.

## BQ4 — Instant Plan Adoption
**Type 2**

Does the "instant plan" quick-start path get users into a quest faster, and with fewer interactions, than the standard flow?

Computed from `metadata.start_path` (`instant_plan` | `standard`) on `recommendation_accepted`/`quest_started` events. BQ4 reports, per path: number of starts, average and median `seconds_to_start`, average `interactions_to_start`, and the percentage reduction of both versus the `standard` path. See `docs/EVENT_SCHEMA.md` for the event contract.

## BQ5 — Personalized Quest Recommendation
**Type 2**

Given the user's available time, preferred level of social interaction, interests, and previous quest interactions, which three available Sidequests have the highest relevance for the current session?

Runtime ranking is provided by the shared authenticated `public.recommend_quests` RPC. The analytics pipeline implements BQ5 evidence through `BQ5_PERSONALIZED_RECOMMENDATION_SQL`, which reads real `recommendation_shown` events and stores the latest top-three recommendation list per user/session in `analytics.bq_results`. This keeps the low-latency ranking in the backend while making BQ5 explicitly reproducible inside the analytics system.

## BQ6 — Quest Abandonment Reasons
**Type 2**

Which quest/context characteristics are most associated with users abandoning a quest?

Reports abandoned attempts by reason, duration, cost, distance band and platform. Both clients share the reason codes and the bands, but Kotlin's distance comes from the catalogue and Flutter's from GPS. See `docs/EVENT_SCHEMA.md` for the event contract.

## BQ7 — Group vs Individual Quest Performance
**Type 3**

How do adoption and completion compare between quests marked as group quests and individual quests?

Computed over the last 30 days from accepted attempts in `public.user_quests`,
classified through `public.quests.is_group`. Reports adopting users, accepted
attempts, completed, abandoned and open attempts, adoption share among users
with any accepted quest, completion and abandonment rates, median completion
time, average rating, and the overlap between users who accepted both types.

The current schema records a quest's group classification but does not record
group membership or participant sessions. Therefore, BQ7 measures engagement
with quests labelled as group quests, not verified participation in a shared
group. This limitation must remain explicit in Sprint 3 evidence.

## BQ8 — Recommendation Diversity
**Type 3**

How diverse are the recommendations shown to users over time?

Implemented as an experiment: `public.recommend_quests` assigns each user a
stable arm (`control` = BQ5 ranking, `diverse` = novelty + category-repeat
penalties). BQ8 reports, per variant and week: distinct categories per list,
normalised category entropy, catalogue coverage, repeat-exposure rate, and the
acceptance rate as a guardrail. See `docs/EVENT_SCHEMA.md` for the event contract.

## BQ9 — Quest Category Performance
**Type 3**

How do quest categories compare in acceptance/completion performance?

Computed per category over the last 30 days, as a two-stage funnel:

- **Acceptance** (from `analytics_events`): unique recommendation impressions
  (one per user + session + quest, so list reloads do not inflate it), how many
  were accepted and how many were skipped ("Not for me"). Accepts/skips are
  linked to the impression by `user_id` + `session_id` + `quest_id`, as in BQ8.
- **Completion** (from `user_quests`): every accepted attempt, whether it came
  from a recommendation or the catalogue, split into completed, abandoned and
  still open. Reports completion rate over all attempts, completion rate over
  resolved attempts only (completed / (completed + abandoned)), abandonment
  rate, median minutes from accept to complete, and average rating.

Each category also gets `acceptance_rate_vs_overall_pp` and
`completion_rate_vs_overall_pp`: the gap, in percentage points, against the
average of all categories. Rows are ordered best to worst by completion rate,
then acceptance rate. No extra event fields are required.

## BQ10 — Location-Independent Mode Usage
**Type 3**

How is location-independent mode used across sessions/context conditions?

## BQ12 — Sponsored Quest Performance (Sprint 4)
**Type 4 (benefits from data)**

What is the acceptance and completion rate of sponsored Side-Quests compared with
non-sponsored ones, segmented by business category and by the user's declared
interests?

Sidequests earns money from Sponsored Side-Quests: local businesses, organizations
and events pay for their activities to appear as quests, always labelled as
sponsored and only when they fit the user's context. BQ12 is the evidence sold to
sponsors ("quests like yours are accepted X % of the time by students interested in
Y") and the guardrail that sponsored content doesn't make the experience worse than
ordinary content.

Same two-stage funnel and 30-day window as BQ9:

- **Acceptance rate** = accepted unique impressions / unique impressions. An
  impression is one `recommendation_shown` per user + session + quest (list reloads
  and Kotlin card re-renders count once). It is accepted when a
  `recommendation_accepted` of the same user, session and quest follows within 24
  hours. Both clients only send `recommendation_accepted` once Supabase saved the
  attempt.
- **Completion rate** = completed attempts / accepted attempts in `user_quests`
  (skips excluded, whether the attempt came from a recommendation or the catalogue).
  Also reported: resolved completion rate (completed / (completed + abandoned)) and
  abandonment rate.
- **Sponsorship** comes from the catalogue: `quests.is_sponsored` and
  `quests.sponsor_business_category` (Backend migration 010), through `quest_id`.
  No event field is needed, so both clients' history counts. A campaign ends with
  `is_active = false`; flipping `is_sponsored` would reclassify its history.
- **Business category:** the sponsor's (`food_and_beverage`, `retail`...), not the
  activity's. Non-sponsored quests go under the explicit `none`, the baseline every
  category is compared with; a sponsored quest without one goes under
  `unspecified`. Using the activity category for non-sponsored quests would mix two
  vocabularies and invent sponsor segments. The activity category is still reported
  (`quest_category` level) to compare like with like, e.g. sponsored Movement vs
  non-sponsored Movement.
- **Declared interests** come from `user_preferences.interests`, lowercased and
  deduplicated (Kotlin saves `Outdoors`, Flutter `outdoors`). A user with several
  interests counts once in each of them, so interest rows don't add up to the
  total; users without interests are `none_declared`. They are the interests the
  user has now, not at the moment of the impression.
- **Interest match:** an impression or attempt is `matched` when the quest's
  category or one of its tags equals one of the user's interests (the rule of
  `recommend_quests`), `not_matched` otherwise, `none_declared` without interests.
- **Sample threshold:** a rate is null when its denominator is below 10 impressions
  (acceptance) or 5 accepted attempts (completion), and always null without any
  exposure, never 0 %. Counts and distinct users are always reported, with
  `acceptance_sample_ok` / `completion_sample_ok`. Both thresholds are job
  parameters.
- **Gap:** `acceptance_rate_vs_non_sponsored_pp` / `completion_rate_vs_non_sponsored_pp`,
  in percentage points, against the non-sponsored quests of the same segment (same
  interest, same activity category, same match; for a business category, all
  non-sponsored quests).

`BQ12_SPONSORED_PERFORMANCE_SQL` stores one row per segment as `BQ12`, with
`segment_level` = `overall`, `business_category`, `quest_category`,
`interest_match`, `interest` or `business_category_x_interest`. Both sponsor types
of `overall` and every business category of the active catalogue always appear,
exposed or not. `BQ12_WEEKLY_TREND_SQL` stores the last 12 ISO weeks (current one
included) per sponsor type as `BQ12_WEEKLY`; recent weeks still have open attempts,
so their completion rate is provisional.

Limitations: impressions are not measured the same way on both clients (Kotlin logs
a card when it enters the viewport, Flutter logs the whole list when it loads),
which shifts each platform's absolute acceptance but not the sponsored vs
non-sponsored comparison inside it. The comparison is observational: sponsored and
non-sponsored quests differ in more than sponsorship (place, cost, novelty), so a
gap is not a causal effect.

Charts: the Streamlit dashboard, and the Supabase views in
[BQ12_SUPABASE_DASHBOARD.md](BQ12_SUPABASE_DASHBOARD.md).

## Rule

A BQ only counts for Sprint 2 when its logic is implemented and demonstrated against real analytics data; documentation alone is not sufficient.

## Sprint 4 Kotlin — BQ8 experienced-user analysis (separate from existing weekly BQ8)

**Original research focus:** Does a diversity-aware ranking correlate with higher
recommendation acceptance and observable app return among users who have
already completed multiple Side-Quests?

Existing `BQ8` weekly output describes all users, including legacy
`unassigned` events; it remains unchanged. A new `BQ8_EXPERIENCED`
result addresses the experienced cohort explicitly:

- **Eligibility:** at least **two completed attempts with `completed_at`
  strictly earlier than the exposure**. Counting today's completions against
  historic exposures would leak future information.
- **Comparison:** server-assigned `control` versus `diverse`. Legacy
  `unassigned` events do not enter the comparison.
- **Diversity:** number and fraction of unique categories in distinct
  recommendation lists. A list with only one visible card is excluded from
  the category-diversity average.
- **Acceptance:** a unique user/session/quest exposure can be accepted within
  the following 24 hours. Recent opportunities without a complete observation
  window are withheld from the rate denominator.
- **Observed return:** a **different instrumented session** within 30 minutes
  to 24 hours of the first eligible exposure. Only cohorts with at least
  24 hours of follow-up enter the denominator. Not all app opens are
  instrumented; this is a proxy, not true retention.
- **Sample and conclusions:** counts are user-level for the return metric;
  many lists from one user do not imply a large sample. No statistically
  defensible treatment claim is possible with only a few eligible people.
- **Execution:** `scripts/run-bq8-local.ps1` is read-only by default;
  `-Publish` explicitly stores aggregate `BQ8` and
  `BQ8_EXPERIENCED` results. No changes to raw analytics events or user
  quest attempts are performed by this runner.

See [BQ8 Sprint 4 evaluation and command](BQ8_SPRINT4.md).

## BQ14 — Social Comfort Personalization (Sprint 4, Kotlin)

**Owner:** Carlos Poveda · **Type 5** (combined: app feature + analytics) · Sprint 1 list 6.5

> For users with low willingness to participate in socially demanding activities, does
> adapting Side-Quest recommendations to their preferred social exposure level increase
> completion and return rates compared with showing non-personalized social challenges?

- **Population:** users whose comfort level was `low` or `medium` in a BQ14 event of the
  last 30 days (first such event = first exposure).
- **Comparisons:** `as_treated` (adaptation active in the user's latest event: what they
  actually saw) and `intent_to_treat` (hash-assigned `adapt_default` / `control` arm,
  which only sets the default of the "Adapt my Smart Picks" switch).
- **Completion:** completed / accepted `user_quests` attempts since the first exposure,
  skips excluded (BQ9 definition).
- **7-day return:** any `analytics_events` row on a later calendar day within 7 days of
  the first exposure. Only users exposed 7+ days ago enter the denominator.
- **Safety:** events whose `metadata.account_user_id` differs from `user_id` (queued
  offline, uploaded under another account) are ignored. Cohorts under 10 users are
  flagged with `small_sample`; the dashboard warns that the result is exploratory.
- **Run:** `python -m sidequests_analytics.pipeline --job bq14` stores `BQ14` in
  `analytics.bq_results`.
