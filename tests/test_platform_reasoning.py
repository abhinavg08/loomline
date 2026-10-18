import json
import httpx
import pytest
from backend.app.main import app
from backend.app.nvidia import NvidiaInferenceService
from backend.app.config import Settings
from .conftest import uid,source,auth

@pytest.mark.integration
async def test_gateway_planner_validated_fenced_json_replay_and_safe_rejection(client,tokens):
    sid,turn=await source(client)
    hypothesis=await client.post('/v1/tasks/incident_42/memories',json={'operation_id':uid(),'session_id':sid,'source_turn_id':turn,'class':'semantic','assertion_type':'hypothesis','status':'proposed','content':'Deployment might explain errors'})
    mid=hypothesis.json()['memory_id'];headers=auth(tokens,'alpha:verifier')
    evidence=(await client.post('/v1/tasks/incident_42/evidence',headers=headers,json={'operation_id':uid(),'source_type':'synthetic','source_ref':'synthetic:planner','content':'Payments timeouts preceded Checkout errors','observed_at':'2026-10-17T12:00:00Z'})).json()['evidence_id']
    vsid=(await client.post('/v1/tasks/incident_42/sessions',headers=headers,json={'operation_id':uid()})).json()['session_id']
    mode={'invalid':True};calls=[]
    async def provider(request):
        calls.append(True)
        value={'action':'challenge or support' if mode['invalid'] else 'challenge','content':'Payments evidence challenges deployment-only attribution','memory_id':mid,'expected_version':1,'evidence_ids':[evidence]}
        return httpx.Response(200,json={'id':'synthetic-response','object':'chat.completion','created':1,'model':'unit-model','choices':[{'index':0,'message':{'role':'assistant','content':'```json\n'+json.dumps(value)+'\n```'},'finish_reason':'stop'}]})
    service=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='unit-model',nvidia_verifier_api_key='synthetic-private-test-key'),httpx.MockTransport(provider))
    app.state.nvidia=service
    try:
        body={'operation_id':uid(),'task_id':'incident_42','session_id':vsid,'goal':'Assess actual evidence'}
        rejected=await client.post('/v1/reasoning',headers=headers,json=body)
        assert rejected.status_code==503 and rejected.json()['error']['code']=='NIM_INVALID_PROPOSAL'
        assert (await client.get('/v1/tasks/incident_42/memories/'+mid)).json()['status']=='proposed'
        turns=(await client.get('/v1/sessions/'+vsid+'/turns',headers=headers)).json()['items']
        diagnostic=json.loads(turns[-1]['content'])
        assert diagnostic['validation']=='rejected' and diagnostic['diagnostics'][0]['field']=='action'
        mode['invalid']=False;body['operation_id']=uid()
        valid=await client.post('/v1/reasoning',headers=headers,json=body)
        assert valid.status_code==200,valid.text
        assert valid.json()['proposal']['action']=='challenge'
        replay=await client.post('/v1/reasoning',headers=headers,json=body)
        assert replay.json()['replayed'] and len(calls)==2
        conflict=await client.post('/v1/reasoning',headers=headers,json={**body,'goal':'Changed intent'})
        assert conflict.status_code==409
    finally:await service.close()
