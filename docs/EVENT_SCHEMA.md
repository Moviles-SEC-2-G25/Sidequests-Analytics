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
- `location_independent_mode_selected`
- `location_based_mode_selected`

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

## `recommendation_shown` social level (BQ5)

BQ5 ranks by, among others, the user's preferred level of social
interaction. Clients may let the user override the profile value for the
current session only ("¿Cómo te sientes hoy?" in Flutter); the override is
never written to `user_preferences`.

- `social_level` column (`solo` | `social` | `group`): the social level
  **actually sent** to `recommend_quests` for that list (session override if
  any, else the profile's). Should be set on every `recommendation_shown`
  event; BQ5 already reads it.
- `metadata.social_level_source` (text, `session` | `profile`), optional.
  `session` = the user picked it for this session; `profile` = taken from
  `user_preferences`. **Absent means `profile`**, so clients without the
  override (Kotlin today) need no change. Queries should read it as
  `coalesce(metadata->>'social_level_source', 'profile')`.

## `photo_proof_uploaded` (photo proof, Sidequests-Backend migration 009)

Emitted once a step's photo proof is **registered**: uploaded to the private
`quest-proofs` bucket AND its `quest_photo_proofs` row inserted (the success
rule of `docs/API_CONTRACT.md` in Sidequests-Backend). Never on a failed or
still-pending upload. `quest_id` and `category` columns are set.

Flutter sends this `metadata` (**to be aligned with Kotlin**, which already
emits the event per `docs/PHOTO_PROOF_VALIDATION.md` but whose keys are not
documented here yet):

- `attempt_id` (uuid string) — `user_quests.id`, same as `quest_photo_proofs.attempt_id`.
- `step_order` (integer, zero-based) — same as `quest_photo_proofs.step_order`.
- `was_retry` (boolean) — true when the photo had been kept on the device after a
  failed upload (no connection) and this is a later retry.
- `size_bytes` (integer) — size of the uploaded JPEG.

## `recommendation_accepted` / `quest_started` metadata contract (BQ4)

BQ4 (instant plan adoption) compares the "instant plan" quick-start path
against the standard flow. `analytics_events.metadata` must include, on
whichever of `recommendation_accepted` or `quest_started` marks the quest as
started:

- `start_path` (text, `instant_plan` | `standard`) — which flow the user went
  through to start the quest. Required; events without it are ignored by BQ4.
- `seconds_to_start` (numeric) — elapsed time from the flow's entry point to
  the quest actually starting.
- `interactions_to_start` (integer) — number of taps/screens the user went
  through before the quest started.

Clients should emit exactly one of `recommendation_accepted` /
`quest_started` per quest start, with these three fields set.

## BQ9 category performance events

BQ9 needs no new event or metadata field. It uses the existing
`recommendation_shown`, `recommendation_accepted` and `recommendation_skipped`
events, and reads the category from `public.quests` through `quest_id`, so
events that do not send `category` still count. For an accept or skip to be
linked to its impression, it must carry the same `session_id` and `quest_id`
as the `recommendation_shown` event. Completion and abandonment come from
`public.user_quests`.

## BQ10 location mode events

BQ10 uses two selection events:

- `location_independent_mode_selected` when the user selects **Anywhere**.
- `location_based_mode_selected` when the user selects **Nearby**.

Both events store the selected value in the `location_mode` column and include
`time_of_day` and `weather_condition` in metadata. Weather can be
`unknown` when it is not available.

The query counts each session once. A session is considered
location-independent when it selected the independent mode at least once.
