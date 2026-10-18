"""The provider is deterministic here; authorization/storage are real FalkorDB."""
import json
import httpx
import pytest
from backend.app.main import app
from backend.app.nvidia import NvidiaInferenceService
from backend.app.config import Settings
from .conftest import uid,source,auth

@pytest.mark.integration
async def test_history_ablation_withholds_actual_records_and_replay_binds_mode(client,tokens):
    sid,turn=await source(client)
    created=await client.post('/v1/tasks/incident_42/memories',json={'operation_id':uid(),'session_id':sid,'source_turn_id':turn,'class':'episodic','assertion_type':'observation','status':'active','content':'Private synthetic continuity observation'})
    assert created.status_code==201
    captured=[]
    async def provider(request):
        captured.append(json.loads(json.loads(request.content)['messages'][1]['content']))
        return httpx.Response(200,json={'id':'test-only','object':'chat.completion','created':1,'model':'unit-model','choices':[{'index':0,'message':{'role':'assistant','content':json.dumps({'action':'request_context','content':'Need assigned handoff, evidence and approved procedure'})},'finish_reason':'stop'}]})
    service=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='unit-model',nvidia_verifier_api_key='synthetic-test-only'),httpx.MockTransport(provider));original=app.state.nvidia;app.state.nvidia=service
    headers=auth(tokens,'alpha:verifier');vsid=(await client.post('/v1/tasks/incident_42/sessions',headers=headers,json={'operation_id':uid()})).json()['session_id']
    body={'operation_id':uid(),'task_id':'incident_42','session_id':vsid,'goal':'Resume grounded work','purpose':'continuity_trial','include_shared_memory':False}
    try:
        result=await client.post('/v1/reasoning',headers=headers,json=body)
        assert result.status_code==200 and result.json()['proposal']['action']=='request_context'
        assert captured[0]['context']=={} and captured[0]['dependency_paths']==[] and captured[0]['evidence']==[]
        assert len(result.json()['metrics'])==1
        replay=await client.post('/v1/reasoning',headers=headers,json=body);assert replay.json()['replayed'] and len(captured)==1
        assert (await client.post('/v1/reasoning',headers=headers,json={**body,'include_shared_memory':True})).status_code==409
        allowed=await client.post('/v1/reasoning',headers=headers,json={**body,'operation_id':uid(),'include_shared_memory':True})
        assert allowed.status_code==200 and 'Private synthetic continuity observation' in json.dumps(captured[1])
        blocked=await client.post('/v1/reasoning',headers=headers,json={**body,'operation_id':uid(),'purpose':'resume'})
        assert blocked.status_code==400 and len(captured)==2
        denied=await client.post('/v1/reasoning',headers=auth(tokens,'alpha:unassigned'),json={**body,'operation_id':uid()});assert denied.status_code==403
    finally:app.state.nvidia=original;await service.close()
