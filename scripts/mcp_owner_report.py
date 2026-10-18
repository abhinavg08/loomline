"""Read real graph evidence through the public SDK; never attest client software."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from loomline import LoomlineClient

def collect(profile,output):
    # Import MCP config only in the standalone MCP environment; no DB/provider dependency.
    from loomline_mcp.config import load_profile
    p,token=load_profile(profile)
    with LoomlineClient(p.base_url,token=token) as c:
        identity=dict(c.whoami());context=dict(c.get_context(p.task_id,limit=20));agents=dict(c.agents(p.task_id));calls=[];after=0
        for _ in range(100):
            batch=c.mcp_activity(p.task_id,after=after,limit=100);calls.extend(batch['items'])
            if len(batch['items'])<100:break
            after=batch['next_cursor']
        else:raise RuntimeError('Activity report exceeds 10000 calls; narrow task or extend explicit bound')
        memories=[m for k in ('episodic','semantic','procedural','proposed_procedures') for m in context[k]]
        traces=[dict(c.trace(m['reference'])) for m in memories]
        history=[];before=None
        for _ in range(100):
            batch=c.get_history(p.task_id,before=before,limit=100);history.extend(batch['items']);before=batch['next_cursor']
            if not before:break
        report={'captured_at':datetime.now(timezone.utc).isoformat(),'task_id':p.task_id,'identity':identity,'source':'authenticated gateway reads of real FalkorDB; task text untrusted','client_software_attestation':'NOT PROVIDED: identity alias/framework metadata do not prove a coding CLI','owner_codex_tool_invocation':'PENDING_OWNER_VERIFICATION','owner_claude_tool_invocation':'PENDING_OWNER_VERIFICATION','owner_two_cli_exchange':'PENDING_OWNER_VERIFICATION','owner_cross_cli_recovery':'PENDING_OWNER_VERIFICATION','graph_evidence':{'agents':agents,'calls':calls,'claims':dict(c.claims(p.task_id,limit=100)),'traces':traces,'history':history,'handoffs':context['handoffs']},'bounds':{'memory_per_class':20,'max_calls':10000,'max_turns':10000,'claim_limit':100},'checklist':'TWO_AGENT_DEMO.md; attach redacted actual CLI tool output and independent test logs before owner sign-off'}
    from .release_safety import sensitive,configured_secrets
    report.update(owner_antigravity_ide_tool_invocation='PENDING_OWNER_VERIFICATION',owner_antigravity_cli_tool_invocation='PENDING_OWNER_VERIFICATION',owner_three_client_exchange='PENDING_OWNER_VERIFICATION')
    report['checklist']='THREE_AGENT_DEMO.md (or TWO_AGENT_DEMO.md for the original pair); actual redacted application tool output remains required'
    payload=json.dumps(report,indent=2)
    if sensitive(payload.encode(),configured_secrets()):raise RuntimeError('Evidence export refused: credential detected; no report written')
    target=Path(output).resolve();root=Path(__file__).resolve().parents[1]
    if not target.is_relative_to(root/'artifacts/mcp'):raise RuntimeError('Report destination must be under artifacts/mcp')
    if target.exists():raise RuntimeError('Refusing existing evidence output')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(payload);print(json.dumps({'status':'COLLECTED_GRAPH_EVIDENCE','path':str(target),'calls':len(calls),'traces':len(traces),'owner_cli_verification':'PENDING_OWNER_VERIFICATION','secrets_printed':False}))

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',required=True);a=p.parse_args();collect(a.profile,a.output)

if __name__=='__main__':main()
