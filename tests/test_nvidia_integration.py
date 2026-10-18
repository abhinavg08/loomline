import json
import httpx
import pytest
from backend.app.config import Settings
from backend.app.main import app
from backend.app.nvidia import NvidiaInferenceService
from .conftest import uid,source,auth
from .test_memory_intelligence import evidence

pytestmark=pytest.mark.integration


async def test_inference_real_graph_validated_turn_and_replay(client,db,tokens):
    eid=await evidence(client)
    sid,tid=await source(client)
    calls=0
    async def provider(request):
        nonlocal calls
        calls+=1
        ctx=json.loads(json.loads(request.content)['messages'][1]['content'])
        assert any(e['id']==eid for e in ctx['evidence'])
        content=json.dumps(dict(action='hypothesis',content='Deployment might explain synthetic errors',entity_ids=['checkout'],evidence_ids=[eid]))
        return httpx.Response(200,json={'id':'external-test','created':1,'model':'test','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':content,'reasoning_content':'PRIVATE_REASONING'},'finish_reason':'stop'}]})
    service=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='test',nvidia_investigator_api_key='test'),httpx.MockTransport(provider))
    app.state.nvidia=service
    try:
        req=dict(operation_id=uid(),session_id=sid,task_id='incident_42')
        response=await client.post('/v1/agent-inference',json=req)
        assert response.status_code==200,response.text
        repeated=await client.post('/v1/agent-inference',json=req)
        assert repeated.status_code==200 and repeated.json()['replayed'] and calls==1
        turns=(await client.get(f'/v1/sessions/{sid}/turns')).json()['items']
        assert len(turns)==2 and 'PRIVATE_REASONING' not in json.dumps(turns)
        assert turns[-1]['id']==response.json()['source_turn_id']
        different,_=await source(client)
        assert (await client.post('/v1/agent-inference',json={**req,'session_id':different})).status_code==409
        assert (await client.post('/v1/agent-inference',json=req,headers=auth(tokens,'alpha:unassigned'))).status_code in (403,404)
        assert (await client.post('/v1/agent-inference',json={**req,'api_key':'spoof'})).status_code==400
        assert calls==1
    finally:await service.close()


async def test_invalid_provider_output_no_guessed_turn(client):
    sid,_=await source(client)
    async def provider(request):
        return httpx.Response(200,json={'id':'external-test','created':1,'model':'test','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':'not JSON'},'finish_reason':'stop'}]})
    service=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='test',nvidia_investigator_api_key='test'),httpx.MockTransport(provider))
    app.state.nvidia=service
    try:
        r=await client.post('/v1/agent-inference',json=dict(operation_id=uid(),session_id=sid,task_id='incident_42'))
        assert r.status_code==503 and r.json()['error']['code']=='NIM_INVALID_PROPOSAL'
        assert len((await client.get(f'/v1/sessions/{sid}/turns')).json()['items'])==1
    finally:await service.close()
