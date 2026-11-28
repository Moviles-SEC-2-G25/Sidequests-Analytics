from sqlalchemy import text


BQ11_SQL = """
with mapped_blocks(block_id, commercial_block) as (
    values
        ('usaquen-cra6a-c119', 'Usaquén market · Carrera 6A north of Calle 119'),
        ('paloquemao-market', 'Paloquemao market block · Avenida Calle 19 #25-04')
), candidate_events as (
    select
        uq.id as attempt_id, uq.user_id, b.block_id, b.commercial_block,
        uq.completed_at at time zone 'America/Bogota' as finished_local,
        e.metadata ->> 'weekend_start' as measured_weekend,
        case when jsonb_typeof(e.metadata -> 'observed_ms') = 'number'
            then (e.metadata ->> 'observed_ms')::numeric end as observed_ms
    from public.analytics_events e
    join public.user_quests uq on uq.id::text = e.metadata ->> 'attempt_id'
        and uq.user_id = e.user_id and uq.quest_id = e.quest_id
    join public.quests q on q.id = uq.quest_id and q.location_mode = 'gps'
    join mapped_blocks b on b.block_id = e.metadata ->> 'block_id'
    where e.event_type = 'bq11_commercial_block_completed'
        and e.metadata ->> 'schema_version' = '1'
        and e.metadata ->> 'platform' in ('kotlin', 'flutter')
        and uq.status = 'completed'
        and uq.completed_at >= now() - interval '30 days'
        and uq.completed_at <= now()
        and e.occurred_at >= now() - interval '31 days'
        and abs(extract(epoch from (e.occurred_at - uq.completed_at))) <= 60
), observations as (
    select attempt_id, user_id, block_id, commercial_block, max(observed_ms) as observed_ms
    from candidate_events
    where observed_ms > 1200000 and observed_ms <= 172800000
        and extract(isodow from finished_local) in (6, 7)
        and measured_weekend = to_char(date_trunc('week', finished_local) + interval '5 days', 'YYYY-MM-DD')
    group by attempt_id, user_id, block_id, commercial_block
)
select block_id, commercial_block,
    count(*) as qualifying_attempts,
    count(distinct user_id) as distinct_users,
    round(avg(observed_ms) / 60000, 2)::double precision as mean_observed_minutes
from observations
group by block_id, commercial_block
having count(distinct user_id) >= 5
order by qualifying_attempts desc, block_id
"""


def compute_bq11(engine) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(BQ11_SQL)).mappings()]
