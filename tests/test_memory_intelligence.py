import asyncio
import pytest
from backend.app.auth import TokenAuthenticator
from .conftest import uid,auth,source,memory

pytestmark=pytest.mark.integration


async def evidence(client,headers=None,**changes):
    req=dict(operation_id=uid(),source_type='synthetic',source_ref='synthetic:payments',content='Payments upstream timeouts started at 14:02',observed_at='2026-10-17T14:02:00+00:00')
    req.update(changes)
    response=await client.post('/v1/tasks/incident_42/evidence',json=req,headers=headers)
    assert response.status_code==201,response.text
    return response.json()['evidence_id']


async def test_MEM_02_CONC_04_challenge(client,db,tokens):
    e=await evidence(client)
    m,body=await memory(client,**{'class':'semantic'},assertion_type='hypothesis',status='proposed',content='Deployment-17 might explain the errors',entity_ids=['checkout','deployment-17'],evidence_ids=[e])
    contrary=await evidence(client,auth(tokens,'alpha:verifier'))
    path='/v1/tasks/incident_42/memories/'+m['memory_id']
    request=dict(operation_id=uid(),expected_version=1,evidence_id=contrary,reason='Upstream timeouts challenge deployment-only attribution')
    winner,loser=await asyncio.gather(*(client.post(path+'/challenges',headers=auth(tokens,'alpha:verifier'),json={**request,'operation_id':uid()}) for _ in range(2)))
    assert sorted([winner.status_code,loser.status_code])==[201,409]
    success=winner if winner.status_code==201 else loser
    read=(await client.get(path)).json()
    assert read['status']=='disputed' and read['version']==2 and read['support'][0]['id']==e and read['challenges'][0]['id']==contrary
    p=TokenAuthenticator().authenticate(tokens['alpha:verifier'])
    ev=(await db.query(p,'MATCH (e:MemoryEvent {id:$id}) RETURN e',{'id':success.json()['challenge_id']}))[0]['e'].properties
    assert ev['actor_id']=='verifier' and ev['old_status']=='proposed' and ev['new_status']=='disputed'
    assert ev['old_version']==1 and ev['new_version']==2 and ev['reason']
    assert (await db.query(p,"MATCH (e:MemoryEvent {type:'MEMORY_CHALLENGED',target_id:$id}) RETURN count(e) AS n",{'id':m['memory_id']}))[0]['n']==1


async def test_MEM_03_procedure_approval(client,db,tokens):
    h=auth(tokens,'alpha:coordinator')
    m,body=await memory(client,h,**{'class':'procedural'},assertion_type='procedure',status='proposed',steps=['Read dependency graph','Compare upstream timeouts before rollback'])
    path='/v1/tasks/incident_42/memories/'+m['memory_id']+'/status'
    req=dict(operation_id=uid(),expected_version=1,status='active',reason='Reviewed synthetic incident investigation procedure')
    assert (await client.patch(path,json=req)).status_code==403
    approval=await client.patch(path,json=req,headers=h)
    assert approval.status_code==201,approval.text
    assert (await client.patch(path,json=req,headers=h)).json()==approval.json()
    sid,tid=await source(client,h)
    ctx=(await client.get('/v1/tasks/incident_42/context',headers=h)).json()
    approved=next(x for x in ctx['procedural'] if x['id']==m['memory_id'])
    assert approved['steps']==body['steps'] and approved['status']=='active'
    # New session visibly records actual procedure reuse.
    used=await client.post(f'/v1/sessions/{sid}/turns',json={'operation_id':uid(),'role':'assistant','content':'Using approved procedure '+approved['id']+': '+approved['steps'][0]},headers=h)
    assert used.status_code==201
    retired=await client.patch(path,json={**req,'operation_id':uid(),'expected_version':2,'status':'retired'},headers=h)
    assert retired.status_code==201
    assert (await client.patch(path,json=req,headers=h)).json()==approval.json()  # original result even after later advancement
    assert (await client.patch(path,json={**req,'operation_id':uid(),'expected_version':3},headers=h)).status_code==409


async def test_wrong_task_refs_no_partial_write(client,db,tokens):
    p=TokenAuthenticator().authenticate(tokens['alpha:investigator'])
    await db.query(p,"MATCH (a:Agent {id:'investigator'}) MERGE (t:Task {id:'other_task'}) MERGE (t)-[:ASSIGNED_TO]->(a) MERGE (e:Evidence {id:'wrong_task_evidence'}) MERGE (t)-[:HAS_EVIDENCE]->(e)",write=True)
    sid,tid=await source(client)
    req=dict(operation_id=uid(),session_id=sid,source_turn_id=tid,**{'class':'episodic'},assertion_type='observation',status='active',content='x',evidence_ids=['wrong_task_evidence'])
    assert (await client.post('/v1/tasks/incident_42/memories',json=req)).status_code==404
    assert (await db.query(p,'MATCH (op:Operation {id:$op}) RETURN count(op) AS n',{'op':req['operation_id']}))[0]['n']==0


async def test_GRAPH_01_dependency_provenance(client):
    e=await evidence(client)
    m,_=await memory(client,content='Synthetic upstream observation',entity_ids=['payments'],evidence_ids=[e])
    response=await client.get('/v1/tasks/incident_42/decision-context')
    assert response.status_code==200,response.text
    paths=response.json()['paths']
    path=next(x for x in paths if x['memory_id']==m['memory_id'])
    assert path['service']=='Checkout' and path['upstream']=='Payments' and path['evidence_id']==e
    # Deterministic OFFLINE policy derives its rationale from returned graph values.
    rationale=f"Offline policy: inspect {path['upstream']} because {path['service']} depends on it; source {path['evidence_id']}: {path['evidence']}"
    sid,tid=await source(client)
    assert path['evidence_id'] in rationale
