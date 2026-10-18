"""Discover and exercise the entire public surface on owned real FalkorDB graphs."""
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
import pytest
from loomline import LoomlineClient
from .conftest import connect,call,denied

def op():return 'audit_'+uuid.uuid4().hex
def folder():return Path(os.environ['LOOM_MCP_REPORT']).parent
def task(gateway,tokens):
    with LoomlineClient(gateway.url,token=tokens['alpha:coordinator']) as owner:
        return owner.create_task('FINAL AUDIT independent protocol clients',assigned_agent_ids=['verifier','investigator'],synthetic=True).task_id
def episode(content='FINAL AUDIT explicit protocol fixture observation'):
    return dict(operation_id=op(),content=content,memory_class='episodic',assertion_type='observation',status='active')

async def test_every_discovered_tool_has_a_real_success_and_strict_input_validation(profile_factory,gateway,tokens):
    tid=task(gateway,tokens);coverage={}
    async with connect(profile_factory(task=tid)) as a,connect(profile_factory('alpha:verifier',task=tid)) as b:
        discovered=(await a.list_tools()).tools
        inventory=[dict(name=t.name,description=t.description,input_schema=t.input_schema,output_schema=t.output_schema) for t in discovered]
        (folder()/'tool-inventory.json').write_text(json.dumps(inventory,indent=2))
        for tool in discovered:
            assert tool.input_schema['additionalProperties'] is False and tool.output_schema
            assert not {'tenant_id','agent_id','token','graph','path','ctx'} & tool.input_schema.get('properties',{}).keys()
            bad=await a.call_tool(tool.name,{'tenant_id':'beta'})
            assert bad.is_error
            coverage[tool.name]={'success_count':0,'extra_identity_argument_rejected':True}
        async def ok(client,name,**arguments):
            result=await call(client,name,**arguments)
            coverage['loomline_'+name]['success_count']+=1
            (folder()/'tool-coverage.json').write_text(json.dumps(coverage,indent=2))
            return result
        assert (await ok(a,'whoami'))['identity']['agent_id']=='coordinator'
        assert (await ok(b,'subscribe',operation_id=op(),enabled=True))['enabled']
        turn=await ok(a,'record_turn',operation_id=op(),role='tool',content='FINAL AUDIT real typed-memory lifecycle')
        ev=await ok(a,'add_evidence',operation_id=op(),content='Deterministic audit fixture observation, not model reasoning',source_type='synthetic',source_ref='test_final_reliability: explicit fixture',observed_at=datetime.now(timezone.utc).isoformat())
        ep=await ok(a,'remember',**episode(),evidence_ids=[ev['evidence_id']])
        eid=ep['receipt']['memory_id'];ref=f'loom://task/{tid}/memory/{eid}'
        resolved=await ok(b,'resolve',reference=ref);assert resolved['id']==eid and resolved['support'][0]['id']==ev['evidence_id']
        traced=await ok(b,'trace',reference=ref);assert traced['source_turn']['id']==ep['source_turn_id']
        hypothesis=await ok(a,'remember',**{**episode('FINAL AUDIT proposed semantic hypothesis'),'memory_class':'semantic','assertion_type':'hypothesis','status':'proposed'})
        mid=hypothesis['receipt']['memory_id']
        assert (await ok(b,'support',operation_id=op(),memory_id=mid,evidence_id=ev['evidence_id'],expected_version=1,reason='Explicit synthetic support'))['status']=='proposed'
        assert (await ok(b,'challenge',operation_id=op(),memory_id=mid,evidence_id=ev['evidence_id'],expected_version=2,reason='Contrary fixture interpretation remains visible'))['status']=='disputed'
        proposed=await ok(a,'propose_procedure',operation_id=op(),content='FINAL AUDIT separate procedure approval',steps=['Read actual evidence','Verify the actual tool result'])
        pid=proposed['receipt']['memory_id']
        await denied(a,'update_status','PROCEDURE_APPROVAL_DISABLED',operation_id=op(),memory_id=pid,expected_version=1,status='approve_procedure',reason='Self approval denied')
        async with connect(profile_factory(task=tid,approval=True)) as owner:
            assert (await ok(owner,'update_status',operation_id=op(),memory_id=pid,expected_version=1,status='approve_procedure',reason='Separate trusted operator approval'))['status']=='active'
        ctx=await ok(b,'get_context',limit=5)
        assert any(m['id']==pid for m in ctx['context']['procedural'])
        recalled=await ok(b,'recall',limit=5);assert {m['class'] for m in recalled['items']}=={'episodic','semantic','procedural'}
        assert any(t['id']==turn['turn_id'] for t in (await ok(b,'get_history'))['items'])
        assert (await ok(a,'operation_status',operation_id=ep['receipt']['operation_id'] if 'operation_id' in ep['receipt'] else resolved['operation_id']))['memory_id']==eid
        intent=op();resumed=await ok(b,'resume_task',operation_id=intent)
        assert (await ok(b,'resume_task',operation_id=intent))['new_session_id']==resumed['new_session_id']
        assert (await ok(b,'changes_since',limit=10))['next_cursor']
        claim=await ok(a,'claim_work',operation_id=op(),work_key='audit_exclusive',lease_seconds=30)
        assert claim['confirmed_owned_now'] and (await ok(b,'list_claims'))['items'][0]['active']
        await ok(a,'release_work',operation_id=op(),work_key='audit_exclusive',expected_version=claim['receipt']['version'])
        h=await ok(a,'handoff',operation_id=op(),to_agent_id='verifier',description='FINAL AUDIT real handoff lifecycle',related_memory_ids=[eid,mid,pid])
        assert (await ok(b,'get_handoff',handoff_id=h['handoff_id']))['status']=='open'
        assert (await ok(b,'accept_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=1))['status']=='accepted'
        assert (await ok(b,'complete_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=2))['status']=='done'
        cancel=await ok(a,'handoff',operation_id=op(),to_agent_id='verifier',description='FINAL AUDIT explicit cancellation',related_memory_ids=[eid])
        assert (await ok(a,'cancel_handoff',operation_id=op(),handoff_id=cancel['handoff_id'],expected_version=1))['status']=='cancelled'
        for attempt in range(5):
            # Real owned router process; no simulated InboxItem or database mock.
            process=await asyncio.create_subprocess_exec(os.environ['LOOM_TEST_BACKEND_PYTHON'],'-m','scripts.router','--once',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await process.communicate();assert process.returncode==0,'Owned router failed'
            inbox=await ok(b,'inbox',limit=10)
            if inbox['items']:break
        assert inbox['items']
        item=inbox['items'][0]['id']
        await denied(a,'mark_inbox_read','NOT_FOUND',operation_id=op(),inbox_id=item)
        await ok(b,'mark_inbox_read',operation_id=op(),inbox_id=item)
        await denied(a,'update_status','INVALID_TRANSITION',operation_id=op(),memory_id=eid,status='retire',expected_version=1,reason='Episodes are not retired procedures')
        await ok(a,'update_status',operation_id=op(),memory_id=pid,status='retire',expected_version=2,reason='FINAL AUDIT historical procedure resolve remains available')
        assert (await ok(b,'resolve',reference=f'loom://task/{tid}/memory/{pid}'))['status']=='retired'
        replacement=await ok(a,'remember',**{**episode('FINAL AUDIT replacement hypothesis'),'memory_class':'semantic','assertion_type':'hypothesis','status':'proposed'},supersedes_id=mid)
        await ok(a,'update_status',operation_id=op(),memory_id=mid,status='supersede',expected_version=3,reason='Real replacement edge exists')
        history=await ok(b,'trace',reference=f'loom://task/{tid}/memory/{mid}')
        assert history['memory']['status']=='superseded' and history['replacements'][0]==replacement['receipt']['memory_id']
        historical=await ok(b,'recall',memory_class='semantic',status='superseded',limit=5)
        assert any(m['id']==mid for m in historical['items'])
        assert set(coverage)=={t.name for t in discovered}
        assert all(v['success_count']>0 for v in coverage.values()),'Every advertised tool must have an actual successful invocation'

async def test_reference_errors_guidance_and_scope_preserving_not_found(profile_factory):
    async with connect(profile_factory()) as c:
        ep=await call(c,'remember',**episode());mid=ep['receipt']['memory_id']
        ref='loom://task/incident_42/memory/'+mid
        for name in ('resolve','trace'):
            assert not (await c.call_tool('loomline_'+name,{'reference':ref})).is_error
            for invalid in (mid,'loom://task/incident_42/evidence/evidence_known','loom://task/incident_42/session/sess_known','loom://task/incident_42/memory/'+mid+'?query=x'):
                text=await denied(c,name,'INVALID_MEMORY_REFERENCE',reference=invalid)
                assert '400' in text and 'linked evidence' in text and invalid not in text
            for absent in ('loom://task/incident_42/memory/mem_nonexistent','loom://task/task_foreign/memory/'+mid):
                text=await denied(c,name,'NOT_FOUND',reference=absent)
                assert '404' in text and 'absent or inaccessible' in text

async def test_previous_release_evidence_uri_404_reproduces_on_real_storage(profile_factory,tmp_path):
    """Historical artifact is optional for other checkouts; present in this audit."""
    import zipfile
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    archive=Path.cwd()/'artifacts/release/loomline-antigravity-source-0.1.0-verified.zip'
    if not archive.exists():pytest.skip('Historical source archive unavailable; current reference regressions still run')
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=='2d661fcd163317c2544f4e016d55544480ee3362f55b349a74889e6e5f6229a1'
    package=tmp_path/'loomline_mcp';package.mkdir()
    with zipfile.ZipFile(archive) as source:
        prefix='packages/loomline-mcp/src/loomline_mcp/'
        for name in source.namelist():
            if name.startswith(prefix) and name.endswith('.py'):
                relative=name.removeprefix(prefix)
                assert '/' not in relative and '\\' not in relative
                (package/relative).write_bytes(source.read(name))
    profile=profile_factory()
    params=StdioServerParameters(command=sys.executable,args=['-m','loomline_mcp','--profile',str(profile)],cwd=str(tmp_path))
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as legacy:
            await legacy.initialize()
            ev=await call(legacy,'add_evidence',operation_id=op(),content='Real persisted evidence for pre-fix reference reproduction',source_type='synthetic',source_ref='FINAL AUDIT previous verified source package',observed_at=datetime.now(timezone.utc).isoformat())
            ep=await call(legacy,'remember',**episode(),evidence_ids=[ev['evidence_id']])
            memory_ref=ep['receipt']['reference'];evidence_ref='loom://task/incident_42/evidence/'+ev['evidence_id']
            for name in ('resolve','trace'):
                await call(legacy,name,reference=memory_ref)
                assert '404' in await denied(legacy,name,'NOT_FOUND',reference=evidence_ref)
    async with connect(profile) as current:
        for name in ('resolve','trace'):
            await call(current,name,reference=memory_ref)
            assert '400' in await denied(current,name,'INVALID_MEMORY_REFERENCE',reference=evidence_ref)
    (folder()/'legacy-reference-reproduction.json').write_text(json.dumps({'status':'PASS','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'storage':'real isolated FalkorDB','known_existing_evidence_id':ev['evidence_id'],'known_existing_memory_reference':memory_ref,'reproduction_input':{'reference':evidence_ref},'both_tools_previous_release':'404 NOT_FOUND','both_tools_current':'400 INVALID_MEMORY_REFERENCE with guidance','known_memory_resolve_and_trace':'PASS before and after','original_owner_arguments':'UNAVAILABLE; this reproduces a failure class, not an asserted exact original invocation'},indent=2))

async def test_codex_and_antigravity_configuration_shapes_on_disposable_task(profile_factory,gateway,tokens):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    from loomline_mcp.client_config import load_stdio_config
    tid=task(gateway,tokens)
    codex=profile_factory(task=tid);antigravity=profile_factory('alpha:verifier',task=tid)
    config=antigravity.with_suffix('.mcp_config.json')
    config.write_text(json.dumps({'mcpServers':{'loomline':{'command':sys.executable,'args':['-m','loomline_mcp'],'cwd':str(Path.cwd()),'env':{'LOOM_MCP_PROFILE':str(antigravity),'PYTHONUNBUFFERED':'1'}}}}))
    params=StdioServerParameters(command=sys.executable,args=['-m','loomline_mcp','--profile',str(codex)],cwd=str(Path.cwd()))
    async with stdio_client(params) as (r1,w1),stdio_client(load_stdio_config(config)) as (r2,w2):
        async with ClientSession(r1,w1) as c1,ClientSession(r2,w2) as c2:
            await asyncio.gather(c1.initialize(),c2.initialize())
            identities=await asyncio.gather(call(c1,'whoami'),call(c2,'whoami'))
            assert {i['fixed_task_id'] for i in identities}=={tid}
            assert len({i['identity']['agent_id'] for i in identities})==2
            ep=await call(c1,'remember',**episode('FINAL AUDIT disposable Codex-shape to Antigravity-shape exchange'))
            assert (await call(c2,'resolve',reference=ep['receipt']['reference']))['source_turn_id']==ep['source_turn_id']
            (folder()/'coding-client-configurations.json').write_text(json.dumps({'status':'PASS','scope':'independent test clients, isolated credentials/task; no actual application launched','transports':['Codex module --profile','Antigravity mcpServers command/args/cwd/env'],'authorized_task':tid,'distinct_principals':True,'shared_memory_exchange':'PASS'},indent=2))

async def test_revocation_applies_to_already_connected_mcp_client(profile_factory,gateway,tokens):
    tid=task(gateway,tokens)
    async with connect(profile_factory('alpha:investigator',task=tid)) as c,connect(profile_factory(task=tid)) as owner:
        await call(c,'get_context')
        memory=await call(c,'remember',**episode('FINAL AUDIT revocation target'))
        path=Path(os.environ['LOOM_AUTH_FILE']);original=path.read_bytes()
        registry=json.loads(original);registry.pop(hashlib.sha256(tokens['alpha:investigator'].encode()).hexdigest())
        try:
            pending=path.with_suffix('.revoke-pending');pending.write_text(json.dumps(registry));pending.replace(path)
            await denied(c,'get_context','UNAUTHENTICATED')
            rejected=await denied(c,'resolve','UNAUTHENTICATED',reference=memory['receipt']['reference'])
            assert 'absent or inaccessible' not in rejected
            await denied(c,'record_turn','UNAUTHENTICATED',operation_id=op(),role='tool',content='This revoked write must never commit')
            assert (await call(owner,'whoami'))['identity']['agent_id']=='coordinator'
        finally:path.write_bytes(original)

async def test_handoff_races_and_hard_mcp_process_termination(profile_factory,gateway,tokens):
    tid=task(gateway,tokens);a_profile=profile_factory(task=tid);b_profile=profile_factory('alpha:verifier',task=tid)
    async with connect(a_profile) as a:
        h=await call(a,'handoff',operation_id=op(),to_agent_id='verifier',description='FINAL AUDIT kill an accepted assignee process',related_memory_ids=[])
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','loomline_mcp','--profile',str(b_profile),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        counter=0
        async def rpc(method,params):
            nonlocal counter
            counter+=1;seq=counter
            process.stdin.write((json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params})+'\n').encode());await process.stdin.drain()
            while True:
                line=await asyncio.wait_for(process.stdout.readline(),20)
                assert line,'MCP process closed unexpectedly'
                result=json.loads(line)
                if result.get('id')==seq:
                    assert 'error' not in result
                    return result['result']
        async def raw_tool(name,arguments):
            result=await rpc('tools/call',{'name':'loomline_'+name,'arguments':arguments})
            assert not result.get('isError',False)
            return result['structuredContent']['data']
        try:
            await rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'loomline-final-audit-test-client','version':'1'}})
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');await process.stdin.drain()
            old=(await raw_tool('whoami',{}))['session_id']
            ep=await raw_tool('remember',episode('FINAL AUDIT committed before hard MCP termination'))
            await raw_tool('accept_handoff',dict(operation_id=op(),handoff_id=h['handoff_id'],expected_version=1))
            old_pid=process.pid;process.kill();await process.wait()
            assert process.returncode!=0
            assert (await call(a,'get_handoff',handoff_id=h['handoff_id']))['status']=='accepted'
            async with connect(b_profile) as b,connect(b_profile) as peer:
                assert (await call(b,'whoami'))['session_id']!=old
                ref=f"loom://task/{tid}/memory/{ep['receipt']['memory_id']}"
                assert (await call(b,'resolve',reference=ref))['source_turn_id']==ep['source_turn_id']
                assert any('committed before hard MCP termination' in t['content'] for t in (await call(b,'get_history'))['items'])
                await call(b,'resume_task',operation_id=op())
                assert (await call(b,'complete_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=2))['status']=='done'
                raced=await call(a,'handoff',operation_id=op(),to_agent_id='verifier',description='FINAL AUDIT concurrent acceptance and completion/cancel',related_memory_ids=[])
                accepts=await asyncio.gather(*(c.call_tool('loomline_accept_handoff',dict(operation_id=op(),handoff_id=raced['handoff_id'],expected_version=1)) for c in (b,peer)))
                assert sum(not x.is_error for x in accepts)==1
                transitions=await asyncio.gather(b.call_tool('loomline_complete_handoff',dict(operation_id=op(),handoff_id=raced['handoff_id'],expected_version=2)),a.call_tool('loomline_cancel_handoff',dict(operation_id=op(),handoff_id=raced['handoff_id'],expected_version=2)))
                assert sum(not x.is_error for x in transitions)==1
                final=await call(a,'get_handoff',handoff_id=raced['handoff_id'])
                assert final['version']==3 and final['status'] in ('done','cancelled')
                report={'status':'PASS','hard_killed_mcp_pid':old_pid,'old_session':old,'committed_memory_recovered':True,'accepted_handoff_recovered_and_done':True,'peer_mcp_remained_available':True,'race_calls':4,'successful_transitions':2,'expected_conflicts':2,'unexpected_errors':0,'final_version':final['version']}
                (folder()/'termination-and-handoff-races.json').write_text(json.dumps(report,indent=2))
        finally:
            if process.returncode is None:process.kill();await process.wait()
