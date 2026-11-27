# BQ11 · Weekend commercial-block activity

**Type 4 (Benefits from Data).** Which commercial blocks in Bogotá have users spending more than 20 minutes completing physical Side-Quests on weekends? The result can help identify candidates for sponsored checkpoint quests.

## Measurement and scope

- The Android pilot covers the flea-market section of Carrera 6A near Calle 119 in Usaquén and the Paloquemao market block. These are pilot geometries, not official property boundaries or citywide coverage. See [Usaquén's market address](https://www.mercadopulgasusaquen.com/contactanos/), [Carrera 6A geometry](https://www.openstreetmap.org/way/88958128), [Paloquemao's market address](https://visitbogota.co/es/que-hacer-en-bogota/gastronomia/plaza-de-mercado-paloquemao) and [Paloquemao geometry](https://www.openstreetmap.org/way/713156703). Map data © OpenStreetMap contributors.
- A participant opts in separately for a physical individual quest. Measurement runs while the active quest screen is in the foreground on a Saturday or Sunday in `America/Bogota`. A measurement only credits intervals between fresh, sufficiently accurate fixes in the same mapped block and weekend. Gaps longer than 35 seconds, leaving the screen, backgrounding the app and invalid or out-of-area fixes break an interval.
- The app maps coordinates on the device without storing or sending raw coordinates. Stopping sharing before completion discards the measurement. Unfinished measurement lives in memory and does not survive process death. A qualifying block summary is durably queued with the quest's final progress operation and released after the backend confirms the operation. It uses the original completion time when synced later.
- The event `bq11_commercial_block_completed` has the standard account, quest and timestamp fields, with `schema_version=1`, `platform=kotlin`, `attempt_id`, `event_id`, `block_id`, `weekend_start` and `observed_ms` in metadata.

## Aggregation

The query verifies the event's owner, quest, and attempt against a completed GPS quest in the last 30 days. Time must be strictly greater than 1,200,000 ms in one block and in the same Bogotá weekend as completion. A deduplicated attempt counts once per block. The result contains the number of qualifying attempts, number of distinct participants, and mean observed minutes per block. Blocks with fewer than five qualifying participants are suppressed. The published result contains block summaries only.

This is foreground sampled time among participating users. Stops without reliable fixes, other commercial blocks, Flutter activity and background activity are outside the pilot. A block omitted from the output has no reportable result for that period. The measurement does not estimate overall pedestrian traffic or guarantee sponsorship outcomes.

## Run it

With the Analytics server environment configured to use the existing shared PostgreSQL database:

```sh
python -m sidequests_analytics.pipeline --job bq11
```

The job stores the aggregate in `analytics.bq_results`. Alternatively, use **Sprint 4 · BQ11 — Weekend commercial blocks → Load / refresh BQ11** in Streamlit to run a read-only query. Existing tables and policies are sufficient.

## Validate it

`tests/test_bq11.py` computes the aggregate against temporary PostgreSQL with synthetic data, including the strict threshold, local weekend, duplicate deliveries, owner mismatch, nonphysical and abandoned quests, unmapped blocks and small cohorts. It also exercises the saved and live dashboard paths. Synthetic fixtures are separate from Shared Supabase and must not be included in any real report.

For physical validation, use a test account and a physical quest on a Bogotá weekend in one of the two mapped areas. Enable sharing, keep the quest screen foreground for more than 20 observed minutes with a reliable location fix, and complete it. Verify the event after the completion is synced, using a read-only check. A single test device verifies ingestion, but the block will only appear in the aggregate after five distinct users qualify.
