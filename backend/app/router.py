"""One worker per graph. Frozen recipients; separate idempotent fanout/dispatch queries.

These queries are NOT claimed to be one transaction. A crash after any pointer
write leaves a pending event; retry reuses the same SHA-256 pointer identity.
"""
import hashlib
from .repository import now


class RouterCrash(Exception):pass


class EventRouter:
    def __init__(self,db):self.db=db

    async def run_once(self,crash_after=None):
        inserted=0;processed=0
        for graphname in self.db.tenants.values():
            g=self.db.client.select_graph(graphname)
            pending=await g.ro_query("MATCH (e:MemoryEvent {dispatch_status:'pending'}) RETURN e ORDER BY e.created_at LIMIT 100")
            for row in pending.result_set:
                event=row[0].properties
                params={'event':event['id'],'task':event['task_id']}
                if 'recipient_ids' not in event:
                    recipients=await g.ro_query('MATCH (s:Subscription {enabled:true})-[:COVERS_TASK]->(t:Task {id:$task})-[:ASSIGNED_TO]->(a:Agent {enabled:true}) MATCH (a)-[:HAS_SUBSCRIPTION]->(s) RETURN DISTINCT a.id',params)
                    params['recipients']=sorted(r[0] for r in recipients.result_set)
                    await g.query("MATCH (e:MemoryEvent {id:$event,dispatch_status:'pending'}) WHERE e.recipient_ids IS NULL SET e.recipient_ids=$recipients",params)
                frozen=await g.ro_query('MATCH (e:MemoryEvent {id:$event}) RETURN e.recipient_ids',params)
                for actor in frozen.result_set[0][0]:
                    params.update(actor=actor,id=hashlib.sha256((event['id']+':'+actor).encode()).hexdigest(),now=now())
                    await g.query("MATCH (e:MemoryEvent {id:$event,dispatch_status:'pending'}) MATCH (t:Task {id:$task})-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) MERGE (i:InboxItem {id:$id}) ON CREATE SET i.agent_id=$actor,i.event_id=$event,i.task_id=$task,i.status='unread',i.created_at=$now MERGE (i)-[:FOR_AGENT]->(a) MERGE (i)-[:POINTS_TO]->(e)",params)
                    inserted+=1
                    if crash_after is not None and inserted>=crash_after:
                        raise RouterCrash('Controlled interruption after durable pointer write')
                await g.query("MATCH (e:MemoryEvent {id:$event,dispatch_status:'pending'}) SET e.dispatch_status='dispatched',e.dispatched_at=$now",{'event':event['id'],'now':now()})
                processed+=1
        return {'events_dispatched':processed,'pointer_attempts':inserted}
