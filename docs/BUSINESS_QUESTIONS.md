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

Which onboarding step has the highest abandonment/drop-off rate?

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

## Rule

A BQ only counts for Sprint 2 when its logic is implemented and demonstrated against real analytics data; documentation alone is not sufficient.
