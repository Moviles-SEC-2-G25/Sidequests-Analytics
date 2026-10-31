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
- `quest_alternative_shown`
- `quest_alternative_selected`

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

## BQ3 v2: initial onboarding and first recommendation

Sprint 3 Kotlin implements the versioned contract in [BQ3_V2.md](BQ3_V2.md).
It includes explicit step views, completions, skips, completion, and an exactly
linked first-recommendation exposure and acceptance. Legacy completions alone
cannot establish either first-step exits or recommendation acceptance and are
excluded from the v2 result. They remain stored; no historical rows are changed.

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

## BQ7 group and individual quest comparison

BQ7 requires no additional analytics event. It classifies accepted attempts
from `public.user_quests` by the related `public.quests.is_group` value:

- `true`: group-labelled quest.
- `false`: individual quest.

The current schema does not store group membership, participant identifiers,
or group-session lifecycle events. The metric must not be described as verified
group participation until those records exist.

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

## BQ6 abandonment contract (`quest_abandoned`)

Abandonment means the user chose to leave the attempt for good. Saving progress
to come back later is not abandonment and sends no `quest_abandoned`.

`user_quests.abandon_reason` and `metadata.reason_code` hold one of these stable
codes. Labels may change or be translated without affecting BQ6:

- `ran_out_of_time`
- `too_far`
- `too_expensive`
- `place_unavailable`
- `too_difficult`
- `weather_or_mood_changed`
- `other` — also the value when the user picks no reason

Older Flutter data used other codes. BQ6 counts `place_closed` as
`place_unavailable`, `too_hard` as `too_difficult`, `bad_weather` as
`weather_or_mood_changed`, and `lost_interest` and `not_specified` as `other`.
A null `abandon_reason` stays `Unspecified`: it's unknown data, not a choice.

`metadata` includes:

- `schema_version` (integer, currently `1`)
- `reason` and `reason_code` (the code above), `reason_label` (display text)
- `attempt_id` (uuid string) — `user_quests.id`; BQ6 links the event by it
- `quest_duration_minutes` and `estimated_cost`
- `quest_distance_label` (display text), optional `quest_distance_meters` and
  `quest_distance_band`
- `current_step_index`, `completed_step_count`, `total_step_count`,
  `progress_percent`
- `had_photo_proof` (boolean) and `uploaded_photo_proof_count`
- Flutter only: `platform` (`flutter`) and `quest_distance_source` (`gps`)

### Distance is measured differently on each platform

| | Kotlin | Flutter |
| --- | --- | --- |
| `quest_distance_meters` | Normalized catalogue label | GPS distance from the user to the quest at the moment of abandoning |
| `quest_distance_source` | Absent, read as `catalogue` | `gps` |
| `distance_meters` column | Same catalogue distance | Same GPS distance |

Both use the same bands: `location_independent`, `under_500_m` (below 500 m),
`500_m_to_1_5_km` (below 1,500 m), `over_1_5_km` and `unknown`. Kotlin also has
`on_campus`. A shared band therefore means the same range, not the same
measurement, so compare platforms with `distance_source` in view.

Events from before this contract have no band. BQ6 places them in
`legacy_gps_under_500_m`, `legacy_gps_500_m_to_2_km`, `legacy_gps_2_km_to_10_km`
or `legacy_gps_over_10_km`, kept apart from the bands above. Old Kotlin events
without a band would land there too, since nothing tells them apart.

### Platform

Kotlin doesn't send `platform` on these events. BQ6 reads it from
`metadata.platform`, then takes `schema_version` without it as `kotlin` and the
old `step` key as `flutter`; anything else, or no event at all, is `unknown`.

## Alternatives after abandoning (`quest_alternative_shown` / `quest_alternative_selected`)

After an abandonment both apps can offer alternatives. `shown` is one event per
suggestion displayed; `selected` means opening the quest's details, never
accepting it. The `quest_id` column is the suggested quest. `metadata` includes:

- `algorithm_version` (`lex_alternatives_v1`)
- `source_quest_id`, `source_attempt_id` and `reason_code`
- `rank` (1-based), `score`, `applied_rules` (comma-separated rule codes)
- `time_of_day`, `weather_condition` (`unknown` when not available)
- `context_source` (`device`, or `simulated_debug` in Kotlin debug scenarios)
- Flutter only: `platform` (`flutter`)

These events carry no coordinates. `docs/BQ6_ALTERNATIVES_VALIDATION.sql` checks
them against the source attempt on both platforms.

## BQ1 resume and module failure events (Kotlin, Sprint 3)

BQ1 uses two events sent by the Kotlin app. Both are written first to a local
SQLite queue on the phone and uploaded by WorkManager when there is a
connection, so `occurred_at` (server time) can be later than the real event:
use `metadata.occurred_at_millis` (device time) when present.

`bq1_resume_after_background` — the app came back to the foreground after more
than 10 minutes in the background while an accepted, unfinished Nearby (GPS)
quest was active. Metadata:

- `bq` = `BQ1`
- `app_version` (text), `online` (boolean)
- `background_minutes` (integer), `quest_id` (text)
- `resume_at_millis` (integer) — identifies the resume
- `occurred_at_millis` (integer)

`module_failure` — a fatal crash (uncaught exception, uploaded on the next start)
or a non-fatal failure reported by a module. Metadata:

- `bq` = `BQ1`
- `module`: `auth`, `catalog`, `recommendations`, `context`, `geocoding`,
  `quest_progress`, `photo_proof`, `sensors`, `analytics`, `ui` or `unknown`
- `fatal` (boolean), `exception` (class name), `message` (max 200 chars)
- `after_long_resume` (boolean) — true when it happened within 5 minutes of a
  `bq1_resume_after_background`; then also `resume_at_millis`,
  `background_minutes`, `seconds_since_resume` and `quest_id`
- `online` (boolean) — validated internet at the moment of the failure, so
  expected offline failures can be separated from real bugs
- `app_version` (text), `occurred_at_millis` (integer)
