import pytest
from backend.app.auth import TokenAuthenticator
from backend.app.repository import Repository
from .conftest import source,uid,auth,memory

pytestmark=pytest.mark.integration


async def test_memory_event_constraint_failure_rolls_back_all(client,db,tokens):
    p=TokenAuthenticator().authenticate(tokens['alpha:investigator']);r=Repository(db)
    sid,tid=await source(client);intent=uid()
    eid=r.ids(p,intent,'evt');mid=r.ids(p,intent,'mem')
    sequence=await db.query(p,'MATCH (t:Task {id:$task}) RETURN coalesce(t.event_seq,0) AS seq',{'task':'incident_42'})
    # Force the final event CREATE to violate its real unique constraint.
    # The preceding memory/operation/edges must roll back with it.
    await db.query(p,'CREATE (:MemoryEvent {id:$id})',{'id':eid},write=True)
    req=dict(operation_id=intent,session_id=sid,source_turn_id=tid,**{'class':'episodic'},assertion_type='observation',status='active',content='Synthetic atomic rollback spike')
    try:
        response=await client.post('/v1/tasks/incident_42/memories',json=req)
        assert response.status_code==503
        assert await db.query(p,'MATCH (t:Task {id:$task}) RETURN coalesce(t.event_seq,0) AS seq',{'task':'incident_42'})==sequence
        for label,key in [('Memory',mid),('Operation',intent)]:
            rows=await db.query(p,f'MATCH (n:{label} {{id:$id}}) RETURN count(n) AS n',{'id':key})
            assert rows[0]['n']==0
    finally:
        # Remove only this deliberately incomplete test event, never user data.
        await db.query(p,'MATCH (e:MemoryEvent {id:$id}) DELETE e',{'id':eid},write=True)


async def test_turn_intent_changed_session_conflicts(client):
    first,_=await source(client);second,_=await source(client)
    req=dict(operation_id=uid(),role='assistant',content='Same intent, different session is a conflict')
    assert (await client.post(f'/v1/sessions/{first}/turns',json=req)).status_code==201
    assert (await client.post(f'/v1/sessions/{second}/turns',json=req)).status_code==409


async def test_supersession_keeps_original_and_history(client,tokens):
    old,_=await memory(client,**{'class':'semantic'},assertion_type='hypothesis',status='proposed')
    new,_=await memory(client,**{'class':'semantic'},assertion_type='hypothesis',status='proposed',supersedes_id=old['memory_id'])
    status=await client.patch('/v1/tasks/incident_42/memories/'+old['memory_id']+'/status',headers=auth(tokens,'alpha:coordinator'),json=dict(operation_id=uid(),expected_version=1,status='superseded',reason='New evidence produces a replacement hypothesis'))
    assert status.status_code==201,status.text
    assert (await client.get('/v1/tasks/incident_42/memories/'+old['memory_id'])).json()['status']=='superseded'
    assert (await client.get('/v1/tasks/incident_42/memories/'+new['memory_id'])).json()['status']=='proposed'
