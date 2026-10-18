"""Three real authenticated MCP TEST CLIENTS. Never launch a coding application."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from loomline_mcp.client_config import load_stdio_config
from loomline_mcp.config import load_profile
from .mcp_protocol_relay import connection,call,op,ROOT

@asynccontextmanager
async def configured(config):
    async with stdio_client(load_stdio_config(config)) as streams:
        async with ClientSession(*streams,read_timeout_seconds=30) as client:
            await client.initialize();yield client

async def relay(folder,config):
    setup=json.loads((folder/'setup.json').read_text());task=setup['task_id'];nonce=uuid.uuid4().hex[:8]
    profiles={name:folder/(name+'.profile.json') for name in ('codex','claude','antigravity')}
    assert len({load_profile(p)[1] for p in profiles.values()})==3,'Credentials must be distinct'
    proof=ROOT/'artifacts/mcp'/('three_relay_'+nonce);proof.mkdir(parents=True,exist_ok=False)
    fixture=ROOT/'examples/mcp_collaboration'
    baseline=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=fixture,capture_output=True,text=True)
    assert baseline.returncode==1 and 'failures=3' in baseline.stderr
    validation=proof/'validation';validation.mkdir()
    for name in ('cache.py','test_cache.py'):(validation/name).write_text((fixture/name).read_text())
    cache=validation/'cache.py';text=cache.read_text();assert 'self.clock()+ttl_ms)' in text
    cache.write_text(text.replace('self.clock()+ttl_ms)','self.clock()+ttl_ms/1000)'))
    fixed=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=validation,capture_output=True,text=True)
    assert fixed.returncode==0 and 'Ran 6 tests' in fixed.stderr
    (proof/'baseline.log').write_text(baseline.stderr);(proof/'fixed.log').write_text(fixed.stderr)
    async with connection(profiles['codex']) as a,connection(profiles['claude']) as b:
        async with configured(config) as c:
            clients=(a,b,c);names=('codex','claude','antigravity')
            identities=await asyncio.gather(*(call(x,'whoami') for x in clients))
            for name,identity in zip(names,identities):
                assert identity['identity']['agent_id']==setup['identities'][name]['agent_id'] and identity['fixed_task_id']==task
            assert len({i['identity']['agent_id'] for i in identities})==3
            assert len((await c.list_tools()).tools)==27
            await asyncio.gather(*(call(x,'get_context',limit=3) for x in clients))
            key='three_contend_'+nonce
            race=await asyncio.gather(*(x.call_tool('loomline_claim_work',{'operation_id':op(),'work_key':key,'lease_seconds':60}) for x in clients))
            assert sum(not r.is_error for r in race)==1
            winner=next(i for i,r in enumerate(race) if not r.is_error)
            await call(clients[winner],'release_work',operation_id=op(),work_key=key,expected_version=race[winner].structured_content['data']['receipt']['version'])
            work_keys=[name+'_'+nonce for name in ('investigation','implementation','review')]
            leases=await asyncio.gather(*(call(x,'claim_work',operation_id=op(),work_key=key) for x,key in zip(clients,work_keys)))
            assert all(l['confirmed_owned_now'] for l in leases)
            evidence=await call(a,'add_evidence',operation_id=op(),source_type='tool',source_ref='Three MCP test-client harness: python -m unittest -v',observed_at=datetime.now(timezone.utc).isoformat(),content=baseline.stderr[-3500:])
            episode=await call(a,'remember',operation_id=op(),memory_class='episodic',assertion_type='observation',status='active',content='Three-client protocol harness actually reproduced 3 failing tests out of 6 in the synthetic TTL fixture.',evidence_ids=[evidence['evidence_id']])
            hypothesis=await call(b,'remember',operation_id=op(),memory_class='semantic',assertion_type='hypothesis',status='proposed',content='Deterministic TEST-CLIENT policy proposes clock skew as a candidate to challenge; no coding application or LLM inference occurred.',evidence_ids=[evidence['evidence_id']])
            mid=hypothesis['receipt']['memory_id'];ref=f'loom://task/{task}/memory/{mid}'
            assert (await call(c,'resolve',reference=ref))['created_by']==identities[1]['identity']['agent_id']
            assert 'Clock' in (fixture/'test_cache.py').read_text() and 'ttl_ms' in (fixture/'cache.py').read_text()
            contrary=await call(c,'add_evidence',operation_id=op(),source_type='tool',source_ref='Three MCP test-client harness: inspected injected clock and ran validation-copy python -m unittest -v',observed_at=datetime.now(timezone.utc).isoformat(),content='The fixture uses an injected monotonic clock starting at 40.0 seconds and ttl_ms=1000, with no wall-clock source. A separate disposable copy converts ttl_ms/1000 and all six tests actually pass. Test output: '+fixed.stderr[-2000:])
            await call(c,'challenge',operation_id=op(),memory_id=mid,evidence_id=contrary['evidence_id'],expected_version=1,reason='Injected monotonic clock contradicts skew; real validation-copy tests support a units fix')
            proposal=await call(c,'propose_procedure',operation_id=op(),content='Three-agent test-client proposal: independently compare units and test results',steps=['Inspect source evidence','Review the patch','Run all fixture tests'])
            rejection=await c.call_tool('loomline_update_status',{'operation_id':op(),'memory_id':proposal['receipt']['memory_id'],'expected_version':1,'status':'approve_procedure','reason':'Must require separate owner approval'})
            assert rejection.is_error
            context=await call(c,'get_context',limit=5);procedure=next(p for p in context['context']['procedural'] if p['id']==setup['procedure_id'])
            await call(c,'record_turn',operation_id=op(),role='tool',content='THREE MCP TEST CLIENTS: applied approved procedure '+procedure['id']+'; inspected timing evidence, reviewed one-line units conversion and actually ran all 6 tests in a disposable validation copy. No real Antigravity application was launched.')
            handoff=await call(b,'handoff',operation_id=op(),to_agent_id=identities[2]['identity']['agent_id'],description='Three MCP TEST-CLIENT handoff: recover and verify after process closure',related_memory_ids=[mid,episode['receipt']['memory_id'],procedure['id']])
            await call(c,'accept_handoff',operation_id=op(),handoff_id=handoff['handoff_id'],expected_version=1)
            reads=await asyncio.gather(*(call(x,'resolve',reference=ref) for x in clients for _ in range(3)));assert all(m['status']=='disputed' for m in reads)
            original=identities[2]['session_id']
        # A and B remain open while only the Antigravity-configured MCP process is replaced.
        async with configured(config) as fresh:
            new=(await call(fresh,'whoami'))['session_id'];assert new!=original
            resume=await call(fresh,'resume_task',operation_id=op())
            history=await call(fresh,'get_history',limit=10);assert any('THREE MCP TEST CLIENTS' in t['content'] for t in history['items'])
            assert (await call(fresh,'get_handoff',handoff_id=handoff['handoff_id']))['status']=='accepted'
            await call(fresh,'complete_handoff',operation_id=op(),handoff_id=handoff['handoff_id'],expected_version=2)
            final=await call(fresh,'handoff',operation_id=op(),to_agent_id=identities[0]['identity']['agent_id'],description='Three MCP TEST CLIENTS: review completed verified evidence',related_memory_ids=[mid,procedure['id']])
            await call(a,'accept_handoff',operation_id=op(),handoff_id=final['handoff_id'],expected_version=1)
            await call(a,'complete_handoff',operation_id=op(),handoff_id=final['handoff_id'],expected_version=2)
            for client,key,lease in zip((a,b,fresh),work_keys,leases):await call(client,'release_work',operation_id=op(),work_key=key,expected_version=lease['receipt']['version'])
            trace=await call(fresh,'trace',reference=ref);assert {h['id'] for h in trace['related_handoffs']}>={handoff['handoff_id'],final['handoff_id']}
    report={'status':'PASS','evidence_type':'THREE independent MCP TEST CLIENTS; real FalkorDB; deterministic fixture policy; no coding applications','task_id':task,'agent_ids':[i['identity']['agent_id'] for i in identities],'credentials_distinct':True,'configuration':'actual staged Antigravity mcpServers command/args/cwd/env','discovery_tools':27,'episode_id':episode['receipt']['memory_id'],'episode_source_turn_id':episode['source_turn_id'],'hypothesis_id':mid,'hypothesis_status':'disputed','contrary_evidence_id':contrary['evidence_id'],'approved_procedure_used':procedure['id'],'proposed_procedure_id':proposal['receipt']['memory_id'],'proposal_self_approval':'DENIED','handoff_ids':[handoff['handoff_id'],final['handoff_id']],'handoff_statuses':['done','done'],'terminated_session_id':original,'fresh_session_id':new,'resumed_session_id':resume['new_session_id'],'claim_contention':'one winner, two denials','complementary_work':'three distinct exclusive claims, all released','concurrent_memory_reads':9,'fixture_results':'3 failures/6 tests before fix; 6 passed in separate validation copy','owner_codex_cli':'PENDING_OWNER_VERIFICATION','owner_claude_cli':'PENDING_OWNER_VERIFICATION','owner_antigravity_ide':'PENDING_OWNER_VERIFICATION','owner_antigravity_cli':'PENDING_OWNER_VERIFICATION','real_three_client_exchange':'PENDING_OWNER_VERIFICATION','ui_url':'http://127.0.0.1:8000/?task='+task}
    (proof/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--setup-folder',required=True);p.add_argument('--config',required=True);a=p.parse_args();asyncio.run(relay(Path(a.setup_folder).resolve(),Path(a.config).resolve()))

if __name__=='__main__':main()
