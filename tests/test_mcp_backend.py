import asyncio
import json
import pytest
from backend.app.auth import TokenAuthenticator
from .conftest import uid,auth

pytestmark=pytest.mark.integration

async def test_mcp_connection_preflight_is_authorized_read_only_and_not_cli_attestation(client,tokens):
    path='/v1/tasks/incident_42/mcp-preflight?client=antigravity'
    result=await client.get(path);assert result.status_code==200
    data=result.json();assert data['identity']['agent_id']=='investigator' and data['schema_ready']
    assert data['client_verification']['antigravity_ide']=='PENDING_OWNER_VERIFICATION'
    assert data['client_verification']['antigravity_cli']=='PENDING_OWNER_VERIFICATION'
    assert (await client.get(path,headers={'Authorization':'Bearer invalid'})).status_code==401
    assert (await client.get(path,headers=auth(tokens,'alpha:unassigned'))).status_code==404
    task=(await client.post('/v1/tasks',headers=auth(tokens,'alpha:coordinator'),json={'operation_id':uid(),'title':'Alpha-only preflight','assigned_agent_ids':['investigator']})).json()['task_id']
    assert (await client.get(f'/v1/tasks/{task}/mcp-preflight',headers=auth(tokens,'beta:coordinator'))).status_code==404
    assert (await client.get(path.replace('antigravity','unsupported'))).status_code==400

async def test_atomic_work_claim_race_replay_expiry_and_stale_owner(client,db,tokens):
    c=auth(tokens,'alpha:coordinator');v=auth(tokens,'alpha:verifier')
    task=(await client.post('/v1/tasks',headers=c,json={'operation_id':uid(),'title':'Atomic claim test','assigned_agent_ids':['verifier']})).json()['task_id']
    path=f'/v1/tasks/{task}/claims/shared_slot'
    intents=[{'operation_id':uid(),'lease_seconds':30} for _ in range(12)]
    results=await asyncio.gather(*(client.post(path,headers=c if i%2 else v,json=intents[i]) for i in range(12)))
    # Same owner may renew; simultaneous different owners can never own the same current version.
    successful=[r for r in results if r.status_code==201]
    assert successful and len({r.json()['owner_agent_id'] for r in successful})==1
    assert all(r.status_code in (201,409) for r in results)
    winner=successful[0].json()['owner_agent_id'];winner_header=c if winner=='coordinator' else v;other=v if winner=='coordinator' else c
    current=(await client.get(path,headers=c)).json();assert current['active']
    index=next(i for i,r in enumerate(results) if r.status_code==201)
    replay=await client.post(path,headers=c if index%2 else v,json=intents[index]);assert replay.status_code==200 and replay.json()==results[index].json()
    renewed=await client.post(path,headers=winner_header,json={'operation_id':uid(),'lease_seconds':1,'expected_version':current['version']});assert renewed.status_code==201
    current=renewed.json();await asyncio.sleep(1.1)
    acquired=await client.post(path,headers=other,json={'operation_id':uid(),'lease_seconds':30,'expected_version':current['version']});assert acquired.status_code==201,acquired.text
    denied=await client.post(path+'/release',headers=winner_header,json={'operation_id':uid(),'expected_version':current['version']});assert denied.status_code==403
    stale=await client.post(path+'/release',headers=other,json={'operation_id':uid(),'expected_version':current['version']});assert stale.status_code==409
    done=await client.post(path+'/release',headers=other,json={'operation_id':uid(),'expected_version':acquired.json()['version']});assert done.status_code==201
    p=TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    rows=await db.query(p,'MATCH (w:WorkClaim {task_id:$task,key:$key}) RETURN count(w) AS n',{'task':task,'key':'shared_slot'});assert rows[0]['n']==1
    assert (await client.get(path,headers=auth(tokens,'beta:coordinator'))).status_code==404

async def test_task_restricted_principal_cannot_escape_even_if_assigned(client,db,tokens,isolated_test_environment):
    c=auth(tokens,'alpha:coordinator')
    task=(await client.post('/v1/tasks',headers=c,json={'operation_id':uid(),'title':'Restricted principal','assigned_agent_ids':['verifier']})).json()['task_id']
    path=isolated_test_environment/'auth.json';records=json.loads(path.read_text())
    for principal in records.values():
        if principal['tenant_id']=='alpha' and principal['agent_id']=='verifier':principal['allowed_task_ids']=[task]
    path.write_text(json.dumps(records))
    try:
        v=auth(tokens,'alpha:verifier')
        assert (await client.get(f'/v1/tasks/{task}/context',headers=v)).status_code==200
        assert (await client.get('/v1/tasks/incident_42/context',headers=v)).status_code==404
        listing=(await client.get('/v1/tasks',headers=v)).json()['items'];assert [t['id'] for t in listing]==[task]
        sid=(await client.post(f'/v1/tasks/{task}/sessions',headers=v,json={'operation_id':uid()})).json()['session_id']
        audit=await client.post(f'/v1/tasks/{task}/mcp-activity',headers=v,json={'operation_id':uid(),'session_id':sid,'tool_name':'loomline_recall','outcome':'success','duration_ms':1});assert audit.status_code==201,audit.text
        activity=(await client.get(f'/v1/tasks/{task}/mcp-activity',headers=c)).json();assert activity['items'][0]['agent_id']=='verifier'
        assert activity['client_verification']['real_two_cli_exchange']=='PENDING_OWNER_VERIFICATION'
    finally:
        for principal in records.values():principal.pop('allowed_task_ids',None)
        path.write_text(json.dumps(records))

async def test_mcp_principal_cannot_bypass_procedure_approval_using_http(client,tokens,isolated_test_environment):
    from .conftest import memory
    result,_=await memory(client,headers=auth(tokens,'alpha:coordinator'),**{'class':'procedural','assertion_type':'procedure','status':'proposed','steps':['Review separately']})
    path=isolated_test_environment/'auth.json';records=json.loads(path.read_text())
    for principal in records.values():
        if principal['tenant_id']=='alpha' and principal['agent_id']=='coordinator':principal['can_approve_procedures']=False
    path.write_text(json.dumps(records))
    try:
        response=await client.patch('/v1/tasks/incident_42/memories/'+result['memory_id']+'/status',headers=auth(tokens,'alpha:coordinator'),json={'operation_id':uid(),'expected_version':1,'status':'active','reason':'Bypass attempt'})
        assert response.status_code==403 and response.json()['error']['code']=='PROCEDURE_APPROVAL_DISABLED'
    finally:
        for principal in records.values():principal.pop('can_approve_procedures',None)
        path.write_text(json.dumps(records))
