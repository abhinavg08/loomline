import asyncio
import pytest
from redis.exceptions import ResponseError
from backend.app.auth import TokenAuthenticator
from backend.app.schema import LABELS
from .conftest import auth, uid, source, memory

pytestmark = pytest.mark.integration


async def test_gate0_schema_aof_auth(client, db, tokens):
    assert (await client.get('/health')).json()['schema_ready']
    assert (await db.redis.config_get('appendonly'))['appendonly'] == 'yes'
    assert (await db.redis.config_get('dir'))['dir'] == '/var/lib/falkordb/data'
    for tenant in ('alpha','beta'):
        p = TokenAuthenticator().authenticate(tokens[tenant+':investigator'])
        rows = await db.query(p,'CALL db.constraints() YIELD status RETURN status')
        assert len(rows) == len(LABELS) and all(r['status']=='OPERATIONAL' for r in rows)
        # The actual unique constraint must reject a collision.
        with pytest.raises(ResponseError):
            await db.query(p,"CREATE (:Task {id:'incident_42'})",write=True)
    assert (await client.get('/v1/tasks/incident_42/sessions',headers={'Authorization':'Bearer invalid'})).status_code == 401
    assert (await client.get('/v1/tasks/incident_42/sessions',headers=auth(tokens,'alpha:unassigned'))).status_code == 404
    alpha = await client.get('/v1/tasks/incident_42/sessions')
    assert alpha.status_code == 200


async def test_MEM_01_SHARE_01_ISO_01_ISO_02(client, db, tokens):
    result,body = await memory(client)
    path = '/v1/tasks/incident_42/memories/'+result['memory_id']
    read = await client.get(path,headers=auth(tokens,'alpha:verifier'))
    m = read.json()
    assert read.status_code == 200 and m['created_by']=='investigator'
    assert m['class']=='episodic' and m['source_turn_id']==body['source_turn_id'] and m['created_at']
    for role in ('alpha:unassigned','beta:investigator'):
        assert (await client.get(path,headers=auth(tokens,role))).status_code==404
        assert (await client.get('/v1/resolve',params={'reference':result['reference']},headers=auth(tokens,role))).status_code==404
    assert (await client.post('/v1/tasks/incident_42/memories',json=body,headers=auth(tokens,'alpha:unassigned'))).status_code==404
    beta,_ = await memory(client, auth(tokens,'beta:investigator'),content='Beta only synthetic observation')
    assert (await client.get('/v1/tasks/incident_42/memories/'+beta['memory_id'])).status_code==404
    p = TokenAuthenticator().authenticate(tokens['alpha:investigator'])
    pending = await db.query(p,'MATCH (ev:MemoryEvent {id:$id}) RETURN ev.dispatch_status AS status',{'id':result['event_id']})
    assert pending[0]['status']=='pending'  # Direct sharing precedes routing.


async def test_CONV_02_atomic_sequence_spike(client):
    sid,_ = await source(client)
    async def append(op, content='visible'):
        return await client.post(f'/v1/sessions/{sid}/turns',json={'operation_id':op,'role':'assistant','content':content})
    unique = await asyncio.gather(*(append(uid()) for _ in range(20)))
    assert all(r.status_code==201 for r in unique), [r.text for r in unique]
    op=uid()
    retries=await asyncio.gather(*(append(op) for _ in range(20)))
    assert all(r.status_code in (200,201) for r in retries),[r.text for r in retries]
    assert len({r.json()['turn_id'] for r in retries})==1
    assert len({r.json()['seq'] for r in retries})==1
    turns=(await client.get(f'/v1/sessions/{sid}/turns')).json()['items']
    assert [t['seq'] for t in turns]==list(range(1,23)), {'turns':turns,'unique':[r.json() for r in unique],'retries':[r.json() for r in retries]}
    assert (await append(op,'changed')).status_code==409
    assert (await append(op)).json()==retries[0].json()


async def test_CONC_03_atomic_outbox_timeout_recovery(client, db, tokens):
    result,body=await memory(client)
    responses=await asyncio.gather(*(client.post('/v1/tasks/incident_42/memories',json=body) for _ in range(20)))
    assert all(r.status_code==200 and r.json()==result for r in responses)
    changed={**body,'content':'changed'}
    assert (await client.post('/v1/tasks/incident_42/memories',json=changed)).status_code==409
    # Simulates a caller discarding its successful response (unknown outcome),
    # then recovers by authorized operation identity and the exact same retry.
    recovered=await client.get('/v1/tasks/incident_42/operations/'+body['operation_id'])
    assert recovered.json()==result
    p=TokenAuthenticator().authenticate(tokens['alpha:investigator'])
    counts=await db.query(p,'MATCH (m:Memory {operation_id:$op}) MATCH (e:MemoryEvent {operation_id:$op,type:\'MEMORY_CREATED\'})-[:RECORDS]->(m) RETURN count(m) AS n',{'op':body['operation_id']})
    assert counts[0]['n']==1


async def test_validation_and_spoofing(client,tokens):
    sid,tid=await source(client)
    base=dict(operation_id=uid(),session_id=sid,source_turn_id=tid,**{'class':'procedural'},assertion_type='procedure',status='active',content='x',steps=['x'])
    assert (await client.post('/v1/tasks/incident_42/memories',json=base)).status_code==400
    base.update(status='proposed')
    assert (await client.post('/v1/tasks/incident_42/memories',json=base)).status_code==403
    base.update({'class':'episodic','assertion_type':'observation','status':'active','steps':None,'graph_name':'loom_t_beta'})
    assert (await client.post('/v1/tasks/incident_42/memories',json=base)).status_code==400
    assert (await client.post(f'/v1/sessions/{sid}/turns',json={'operation_id':uid(),'role':'system','content':'private'})).status_code==400
    assert (await client.post(f'/v1/sessions/{sid}/turns',json={'operation_id':uid(),'role':'tool','content':'x'},headers=auth(tokens,'alpha:verifier'))).status_code==404
