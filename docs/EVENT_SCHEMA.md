# Shared Analytics Event Contract

Both Kotlin and Flutter must emit the same event names and compatible dimensions.

## Initial event types

- `onboarding_step_completed`
- `recommendation_shown`
- `recommendation_accepted`
- `recommendation_skipped`
- `quest_started`
- `quest_abandoned`
- `quest_completed`
- `location_mode_selected`

## Stored dimensions

The shared `analytics_events` table currently supports:
- user_id
- session_id
- event_type
- quest_id
- category
- occurred_at
- available_minutes
- social_level
- latitude / longitude
- weather_code
- time_of_day
- location_mode
- quest_duration_minutes
- quest_difficulty
- estimated_cost
- distance_meters
- metadata (JSON)

The clients should only send data required by the Business Questions and product behavior.

## `onboarding_step_completed` metadata contract (BQ3)

No onboarding step taxonomy exists in the backend today, so BQ3 (onboarding
drop-off) defines this contract here. `analytics_events.metadata` must include:

- `step_order` (integer, 1-based) — the step's position in the canonical
  onboarding sequence. Required; events without it are ignored by BQ3.
- `step_name` (text) — a human-readable label for the step (e.g. `"welcome"`,
  `"permissions"`, `"interests"`). Used only for display.

`session_id` is also required on these events: BQ3 measures drop-off per
onboarding attempt (session), not per user account, so a session without an
id cannot be placed in the funnel. Clients should emit one
`onboarding_step_completed` event per completed step, in order, without
skipping `step_order` values.

## `recommendation_shown` metadata contract (BQ8)

BQ8 (recommendation diversity) is an A/B experiment. The variant is assigned
**server-side** by `public.recommend_quests` (stable hash of `auth.uid()`;
`control` = BQ5 ranking, `diverse` = novelty + category-repeat penalties). The
RPC returns `variant` and `rank_position` per row. Clients must copy them into
each `recommendation_shown` event's `metadata`:

- `variant` (text, `control` | `diverse`) — copied from the RPC row.
- `rank` (integer, 1-based) — the RPC's `rank_position`.
- `batch_id` (uuid string) — generated once per RPC call and shared by every
  event of that list, so BQ8 can measure diversity *within* a list.

Events without these fields still count, under variant `unassigned`, with a
`session_id` + second-level timestamp as the batch key.
`recommendation_accepted` needs no extra fields; BQ8 links it to the shown
event by `user_id` + `session_id` + `quest_id`.
