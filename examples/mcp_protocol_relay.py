"""Deterministic MCP TEST-CLIENT demonstration, never a Codex/Claude run."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
def op():return 'relay_'+uuid.uuid4().hex

@asynccontextmanager
async def connection(profile):
    async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','loomline_mcp','--profile',str(profile)])) as streams:
        async with ClientSession(*streams,read_timeout_seconds=30) as c:await c.initialize();yield c

async def call(c,name,**args):
    result=await c.call_tool('loomline_'+name,args)
    if result.is_error:raise RuntimeError('MCP relay call failed: '+name)
    return result.structured_content['data']

async def relay(folder):
    setup=json.loads((folder/'setup.json').read_text());task=setup['task_id'];nonce=uuid.uuid4().hex[:8]
    a_profile=folder/'codex.profile.json';b_profile=folder/'claude.profile.json'
    observed=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=ROOT/'examples/mcp_collaboration',capture_output=True,text=True)
    assert observed.returncode==1 and 'failures=3' in observed.stderr
    # Validate a fix in a NEW copy; leave both owner's worktrees untouched.
    copy=ROOT/'artifacts/mcp'/('relay_validation_'+nonce);copy.mkdir(parents=True,exist_ok=False)
    for name in ('cache.py','test_cache.py'):(copy/name).write_text((ROOT/'examples/mcp_collaboration'/name).read_text())
    cache=copy/'cache.py';cache.write_text(cache.read_text().replace('self.clock()+ttl_ms)','self.clock()+ttl_ms/1000)'))
    fixed=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=copy,capture_output=True,text=True);assert fixed.returncode==0 and 'Ran 6 tests' in fixed.stderr
    (copy/'baseline.log').write_text(observed.stderr);(copy/'fixed.log').write_text(fixed.stderr)
    async with connection(a_profile) as a,connection(b_profile) as b:
        ai=await call(a,'whoami');bi=await call(b,'whoami');assert ai['identity']['agent_id']!=bi['identity']['agent_id']
        # Deliberate race through independent MCP clients, then complementary work slots.
        contest='contention_'+nonce
        race=await asyncio.gather(*(c.call_tool('loomline_claim_work',{'operation_id':op(),'work_key':contest,'lease_seconds':30}) for c in (a,b)))
        assert sum(not r.is_error for r in race)==1
        winner=a if not race[0].is_error else b
        receipt=next(r.structured_content['data']['receipt'] for r in race if not r.is_error)
        await call(winner,'release_work',operation_id=op(),work_key=contest,expected_version=receipt['version'])
        ac=await call(a,'claim_work',operation_id=op(),work_key='investigate_'+nonce)
        bc=await call(b,'claim_work',operation_id=op(),work_key='verify_'+nonce)
        evidence=await call(a,'add_evidence',operation_id=op(),source_type='tool',source_ref='examples/mcp_collaboration: python -m unittest -v (test-client harness)',observed_at=datetime.now(timezone.utc).isoformat(),content=observed.stderr[-3500:])
        episode=await call(a,'remember',operation_id=op(),memory_class='episodic',assertion_type='observation',status='active',content='MCP test-client harness actually ran fixture tests: 3 failures in 6 tests.',evidence_ids=[evidence['evidence_id']])
        hypothesis=await call(a,'remember',operation_id=op(),memory_class='semantic',assertion_type='hypothesis',status='proposed',content='Test-client policy proposes clock skew as one possible explanation; not an LLM inference or established fact.',evidence_ids=[evidence['evidence_id']])
        mid=hypothesis['receipt']['memory_id'];ref=f'loom://task/{task}/memory/{mid}'
        assert (await call(b,'resolve',reference=ref))['status']=='proposed'
        contrary=await call(b,'add_evidence',operation_id=op(),source_type='document',source_ref='examples/mcp_collaboration/test_cache.py and cache.py, inspected by test-client harness',observed_at=datetime.now(timezone.utc).isoformat(),content='Fixture injects a monotonic clock starting at 40.0 seconds and ttl_ms=1000; no wall clock is read. Controlled time advances to 41.5. A fresh corrected copy passes all 6 tests after conversion to seconds.')
        await call(b,'challenge',operation_id=op(),memory_id=mid,evidence_id=contrary['evidence_id'],reason='Injected monotonic clock contradicts skew; unit conversion supported by independently executed fixed-copy tests',expected_version=1)
        ctx=await call(b,'get_context',limit=5);procedure=next(m for m in ctx['context']['procedural'] if m['id']==setup['procedure_id'])
        await call(b,'record_turn',operation_id=op(),role='tool',content='MCP test-client applied approved procedure '+procedure['id']+': inspected timing/config evidence and ran the full fixed-copy suite; 6 passed. This is deterministic protocol verification, not a coding-agent run.')
        h=await call(a,'handoff',operation_id=op(),to_agent_id=bi['identity']['agent_id'],description='MCP TEST-CLIENT: review units evidence and fixed-copy result; resume in a fresh process',related_memory_ids=[mid,procedure['id'],episode['receipt']['memory_id']])
        await call(b,'accept_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=1)
        old=bi['session_id']
        await call(a,'release_work',operation_id=op(),work_key='investigate_'+nonce,expected_version=ac['receipt']['version'])
        await call(b,'release_work',operation_id=op(),work_key='verify_'+nonce,expected_version=bc['receipt']['version'])
    async with connection(b_profile) as fresh:
        new=(await call(fresh,'whoami'))['session_id'];assert new!=old
        recovery=await call(fresh,'resume_task',operation_id=op());history=await call(fresh,'get_history',limit=10)
        assert any(procedure['id'] in t['content'] for t in history['items'])
        assert (await call(fresh,'resolve',reference=ref))['status']=='disputed'
        await call(fresh,'complete_handoff',operation_id=op(),handoff_id=h['handoff_id'],expected_version=2)
        trace=await call(fresh,'trace',reference=ref);assert trace['related_handoffs'][0]['id']==h['handoff_id']
    report={'status':'PASS','evidence_type':'independent MCP test-client relay; deterministic harness; REAL FalkorDB','task_id':task,'identities':[ai['identity']['agent_id'],bi['identity']['agent_id']],'episode_id':episode['receipt']['memory_id'],'hypothesis_id':mid,'contrary_evidence_id':contrary['evidence_id'],'hypothesis_status':'disputed','approved_procedure_used':procedure['id'],'handoff_id':h['handoff_id'],'handoff_status':'done','terminated_session_id':old,'fresh_session_id':new,'resumed_session_id':recovery['new_session_id'],'contention':'one winner, one denial; independent task leases released','fixture_actual_results':'baseline 3 failures/6 tests; corrected disposable copy 6 passed','owner_codex_cli':'PENDING_OWNER_VERIFICATION','owner_claude_cli':'PENDING_OWNER_VERIFICATION','real_two_cli_exchange':'PENDING_OWNER_VERIFICATION','ui_url':'http://127.0.0.1:8000/?task='+task}
    destination=ROOT/'artifacts/mcp'/('relay_'+nonce+'.json');destination.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--setup-folder',required=True);a=p.parse_args();asyncio.run(relay(Path(a.setup_folder).resolve()))
if __name__=='__main__':main()
