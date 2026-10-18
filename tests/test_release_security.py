import json
from types import SimpleNamespace
import httpx
import pytest
from pydantic import ValidationError
from backend.app.config import Settings
from backend.app.errors import DomainError
from backend.app.lease import InstanceLease
from backend.app.nvidia import NvidiaInferenceService
from backend.app.auth import TokenAuthenticator
from .conftest import uid,auth,source


async def test_disabled_live_and_missing_single_instance_guard_do_not_call_provider():
    seen=[]
    async def provider(request):seen.append(True);return httpx.Response(500)
    service=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=False),httpx.MockTransport(provider))
    with pytest.raises(DomainError) as error:await service.completion('investigator',{})
    assert error.value.code=='NIM_LIVE_DISABLED' and not seen
    guarded=NvidiaInferenceService(Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='test',nvidia_investigator_api_key='synthetic'))
    with pytest.raises(DomainError) as error:await guarded.completion('investigator',{})
    assert error.value.code=='SINGLE_INSTANCE_REQUIRED' and not guarded.clients


def test_configuration_repr_hides_secrets_and_rejects_graph_names():
    config=Settings(_env_file=None,falkordb_password='synthetic-password',nvidia_api_key='synthetic-provider-secret')
    assert 'synthetic-password' not in repr(config) and 'synthetic-provider-secret' not in repr(config)
    with pytest.raises(ValidationError):Settings(_env_file=None,loom_graph_namespace='loom_t_alpha')


@pytest.mark.integration
async def test_real_single_instance_lease_and_repository_registry(db):
    first=InstanceLease(db,'release-test');second=InstanceLease(db,'release-test')
    try:
        await first.acquire()
        with pytest.raises(DomainError) as error:await second.acquire()
        assert error.value.code=='SINGLE_INSTANCE_REQUIRED'
        await second.close()
        assert first.valid() and await db.redis.exists(first.key)
        with pytest.raises(DomainError):db.graph(SimpleNamespace(tenant_id='alpha'))
    finally:await first.close();await second.close()


@pytest.mark.integration
async def test_tool_metadata_redacted_and_reserved_inference_intents_rejected(client):
    sid,_=await source(client)
    sensitive='nvapi-'+('z'*35)  # Synthetic, never an active key.
    response=await client.post(f'/v1/sessions/{sid}/turns',json=dict(operation_id=uid(),role='tool',content='safe synthetic observation',tool_name=sensitive,tool_call_id='Bearer synthetic-secret'))
    assert response.status_code==201
    turns=(await client.get(f'/v1/sessions/{sid}/turns')).json()['items']
    assert sensitive not in json.dumps(turns) and 'synthetic-secret' not in json.dumps(turns)
    for intent in (sensitive,'nim_'+('a'*40)):
        rejected=await client.post(f'/v1/sessions/{sid}/turns',json=dict(operation_id=intent,role='assistant',content='{"mode":"live_nvidia","proposal":{}}'))
        assert rejected.status_code==400


@pytest.mark.integration
async def test_repeated_demo_runs_have_clean_scoped_context(client,tokens):
    h=auth(tokens,'alpha:coordinator');req={'operation_id':uid()}
    first=await client.post('/v1/demo-runs',json=req,headers=h)
    assert first.status_code==201,first.text
    assert (await client.post('/v1/demo-runs',json=req,headers=h)).json()==first.json()
    second=await client.post('/v1/demo-runs',json={'operation_id':uid()},headers=h)
    t1=first.json()['task_id'];t2=second.json()['task_id'];assert t1!=t2
    s=await client.post(f'/v1/tasks/{t1}/sessions',headers=h,json={'operation_id':uid()})
    sid=s.json()['session_id']
    turn=await client.post(f'/v1/sessions/{sid}/turns',headers=h,json=dict(operation_id=uid(),role='tool',content='Only this run'))
    memory=await client.post(f'/v1/tasks/{t1}/memories',headers=h,json=dict(operation_id=uid(),session_id=sid,source_turn_id=turn.json()['turn_id'],**{'class':'episodic'},assertion_type='observation',status='active',content='Only this run'))
    assert memory.status_code==201,memory.text
    context=(await client.get(f'/v1/tasks/{t2}/context',headers=h)).json()
    assert context['episodic']==[] and context['semantic']==[] and context['timeline']==[]
    assert (await client.get(f'/v1/tasks/{t2}/memories/'+memory.json()['memory_id'],headers=h)).status_code==404
    assert (await client.get('/v1/inbox',params={'task_id':t2},headers=h)).json()['items']==[]
    assert (await client.post('/v1/demo-runs',json={'operation_id':uid()})).status_code==403


@pytest.mark.integration
async def test_inaccessible_operation_does_not_disclose_existence(client,db,tokens):
    p=TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    hidden='hidden_'+uid();intent=uid()
    await db.query(p,'MATCH (a:Agent {id:\'coordinator\'}) CREATE (t:Task {id:$id}) CREATE (t)-[:ASSIGNED_TO]->(a)',{'id':hidden},write=True)
    result=await client.post(f'/v1/tasks/{hidden}/sessions',headers=auth(tokens,'alpha:coordinator'),json={'operation_id':intent})
    assert result.status_code==201
    assert (await client.get('/v1/tasks/incident_42/operations/'+intent)).status_code==404
