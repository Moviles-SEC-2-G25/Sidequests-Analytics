-- BQ2: observed membership and server-received create/join/progress requests.
-- Every request is idempotent; transport failures that never reach the RPC
-- are not observable. Counts of members include the creator.
with operation_names as (
    select unnest(array['create','join','progress']) as operation
), operations as (
    select operation, count(*)::integer as attempts,
           count(*) filter(where succeeded)::integer as successes,
           count(*) filter(where not succeeded)::integer as failures
    from sidequests_group_private.operations
    where occurred_at >= now() - interval '30 days'
    group by operation
), group_counts as (
    select c.id, q.title, c.expires_at > now() as active,
           count(m.user_id)::integer as participants,
           count(m.user_id) filter(where m.progress=c.total_steps)::integer as completed_participants
    from sidequests_group_private.challenges c
    join public.quests q on q.id=c.quest_id
    left join sidequests_group_private.members m on m.challenge_id=c.id
    where c.created_at >= now()-interval '30 days'
    group by c.id,q.title
)
select 'operation'::text as row_type, n.operation, null::text as challenge_id,
       null::text as quest_title, null::boolean as active,
       coalesce(o.attempts,0) as attempts, coalesce(o.successes,0) as successes,
       coalesce(o.failures,0) as failures,
       round(100.0*o.failures/nullif(o.attempts,0),2) as failure_rate_pct,
       null::integer as participants, null::integer as completed_participants
from operation_names n left join operations o using(operation)
union all
select 'challenge',null,id::text,title,active,null,null,null,null,participants,completed_participants
from group_counts
order by row_type,operation,challenge_id;
