"""Antigravity CONFIGURATION compatibility, not execution of the application."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import uuid
import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from loomline import LoomlineClient
from loomline_mcp.client_config import load_stdio_config
from .conftest import connect,call,denied

def op():return 'agy_'+uuid.uuid4().hex
def config_file(profile):
    path=profile.with_suffix('.mcp_config.json')
    data={'mcpServers':{'loomline':{'command':sys.executable,'args':['-m','loomline_mcp'],'cwd':str(profile.parent),'env':{'LOOM_MCP_PROFILE':str(profile),'PYTHONUNBUFFERED':'1'}}}}
    path.write_text(json.dumps(data));return path

@asynccontextmanager
async def configured(path):
    async with stdio_client(load_stdio_config(path)) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=15) as client:
            await client.initialize();yield client

def test_antigravity_launcher_validation_cannot_execute_other_programs(profile_factory):
    file=config_file(profile_factory());data=json.loads(file.read_text())
    params=load_stdio_config(file);assert params.args==['-m','loomline_mcp'] and params.cwd==str(file.parent)
    for key,value in [('command','cmd.exe'),('args',['-c','print(1)']),('env',{'LOOM_AGENT_TOKEN':'not-a-real-token'}),('serverUrl','http://localhost')]:
        edited=json.loads(json.dumps(data));edited['mcpServers']['loomline'][key]=value;file.write_text(json.dumps(edited))
        with pytest.raises(ValueError):load_stdio_config(file)
    file.write_text(json.dumps(data))

async def test_three_independent_configured_clients_memory_coordination_and_restart(profile_factory,gateway,tokens):
    with LoomlineClient(gateway.url,token=tokens['alpha:coordinator']) as owner:
        task=owner.create_task('Three-client protocol configuration test',assigned_agent_ids=['investigator','verifier']).task_id
    a_profile=profile_factory(task=task);b_profile=profile_factory('alpha:verifier',task=task);c_config=config_file(profile_factory('alpha:investigator',task=task))
    async with connect(a_profile) as a,connect(b_profile) as b,configured(c_config) as c:
        identities=await asyncio.gather(*(call(x,'whoami') for x in (a,b,c)))
        assert len({i['identity']['agent_id'] for i in identities})==3
        assert {i['fixed_task_id'] for i in identities}=={task}
        assert len((await c.list_tools()).tools)==27
        key=op();race=await asyncio.gather(*(x.call_tool('loomline_claim_work',{'operation_id':op(),'work_key':key,'lease_seconds':30}) for x in (a,b,c)))
        assert sum(not r.is_error for r in race)==1
        index=next(i for i,r in enumerate(race) if not r.is_error);winner=(a,b,c)[index];version=race[index].structured_content['data']['receipt']['version']
        await call(winner,'release_work',operation_id=op(),work_key=key,expected_version=version)
        leases=await asyncio.gather(*(call(x,'claim_work',operation_id=op(),work_key=op()) for x in (a,b,c)))
        assert all(l['confirmed_owned_now'] for l in leases)
        episode=await call(c,'remember',operation_id=op(),memory_class='episodic',assertion_type='observation',status='active',content='Independent Antigravity-compatible CONFIG test client observed the synthetic clock fixture')
        hypothesis=await call(c,'remember',operation_id=op(),memory_class='semantic',assertion_type='hypothesis',status='proposed',content='Protocol fixture hypothesis: clock skew may explain the expiry failure')
        mid=hypothesis['receipt']['memory_id'];ref=f'loom://task/{task}/memory/{mid}'
        assert (await call(b,'resolve',reference=ref))['created_by']=='investigator'
        ev=await call(b,'add_evidence',operation_id=op(),content='Synthetic test fixture uses an injected monotonic clock, no wall-clock access.',source_type='synthetic',source_ref='test_antigravity: deterministic fixture',observed_at=datetime.now(timezone.utc).isoformat())
        await call(b,'challenge',operation_id=op(),memory_id=mid,evidence_id=ev['evidence_id'],expected_version=1,reason='Monotonic injected clock contradicts skew')
        trace=await call(c,'trace',reference=ref);assert trace['source_turn']['id']==hypothesis['source_turn_id'] and trace['memory']['status']=='disputed'
        ep=await call(a,'resolve',reference=f"loom://task/{task}/memory/{episode['receipt']['memory_id']}");assert ep['source_turn_id']==episode['source_turn_id']
        proposal=await call(a,'propose_procedure',operation_id=op(),content='Three-client independent verification',steps=['Read real source evidence','Verify actual tests in your own checkout'])
        pid=proposal['receipt']['memory_id']
        await denied(c,'update_status','PROCEDURE_APPROVAL_DISABLED',operation_id=op(),memory_id=pid,expected_version=1,status='approve_procedure',reason='No agent self-approval')
        with LoomlineClient(gateway.url,token=tokens['alpha:coordinator']) as operator:operator.approve_procedure(task,pid,expected_version=1,reason='Separate trusted fixture operator approval')
        context=await call(c,'get_context',limit=5);assert any(p['id']==pid for p in context['context']['procedural'])
        await call(c,'record_turn',operation_id=op(),role='tool',content='Explicit configuration test turn retained after restart; reviewed procedure '+pid)
        h=await call(a,'handoff',operation_id=op(),to_agent_id='investigator',description='Resume configuration test after complete MCP process closure',related_memory_ids=[mid,pid])
        await call(c,'accept_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=1)
        old=identities[2]['session_id']
        reads=await asyncio.gather(*(call(x,'resolve',reference=ref) for x in (a,b,c) for _ in range(3)));assert all(m['status']=='disputed' for m in reads)
    async with configured(c_config) as fresh:
        assert (await call(fresh,'whoami'))['session_id']!=old
        history=await call(fresh,'get_history');assert any('retained after restart' in t['content'] for t in history['items'])
        resumed=await call(fresh,'resume_task',operation_id=op());assert resumed['new_session_id']!=old
        assert (await call(fresh,'complete_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=2))['status']=='done'
        recovered_trace=await call(fresh,'trace',reference=ref)
        assert any(row['id']==h['handoff_id'] for row in recovered_trace['related_handoffs'])
    beta=config_file(profile_factory('beta:coordinator'))
    async with configured(beta) as other:
        for name in ('resolve','trace'):await denied(other,name,'NOT_FOUND',reference=ref)
        await denied(other,'challenge','NOT_FOUND',operation_id=op(),memory_id=mid,evidence_id=ev['evidence_id'],expected_version=2,reason='Foreign ID guess')
        await denied(other,'subscribe',operation_id=op(),task_id=task)
        assert all(t['id']!=task for t in (await call(other,'whoami'))['tasks']['items'])
    with pytest.raises(Exception):
        async with configured(config_file(profile_factory('beta:coordinator',task=task))):pass
