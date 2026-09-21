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
