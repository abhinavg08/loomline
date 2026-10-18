"""Local owner provisioning only. No coding-client executable/config is accessed."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid
from loomline import LoomlineClient
from backend.app.config import ROOT
from .provision_agent import provision

async def setup(name,base,add_client=None):
    if not re.fullmatch(r'[a-z0-9_-]{1,40}',name):raise SystemExit('Name must be 1-40 lowercase letters/digits/underscore/hyphen')
    folder=ROOT/'.secrets/mcp'/name
    if add_client:
        if add_client!='antigravity' or not (folder/'setup.json').is_file():raise SystemExit('Existing setup required for add-client antigravity')
        result=json.loads((folder/'setup.json').read_text());identities=result['identities'];task=result['task_id']
        if add_client in identities or (folder/(add_client+'.profile.json')).exists():raise SystemExit('Client already exists; no profile or credential overwritten')
        base=json.loads((folder/'codex.profile.json').read_text())['base_url']
    elif folder.exists():raise SystemExit('Setup name already exists; no credential/profile overwritten')
    tokens=json.loads((ROOT/'.secrets/agent_tokens.json').read_text())
    with LoomlineClient(base,token=tokens['alpha:coordinator']) as owner:
        if add_client:owner.get_context(task,limit=1)
        else:
            task=owner.create_task('MCP coding collaboration · '+name,assigned_agent_ids=['coordinator'],synthetic=True).task_id
            folder.mkdir(parents=True,mode=0o700);identities={}
        for slot in (add_client,) if add_client else ('codex','claude','antigravity'):
            agent='mcp_'+name+'_'+slot
            await provision(SimpleNamespace(tenant='alpha',agent_id=agent,role='coordinator',task=task,restrict_to_task=True,deny_procedure_approval=True))
            token_file=ROOT/'.secrets'/(agent+'.token')
            profile={'base_url':base,'task_id':task,'token_file':str(token_file),'allow_procedure_approval':False,'timeout_seconds':30}
            target=folder/(slot+'.profile.json');target.write_text(json.dumps(profile,indent=2))
            if os.name!='nt':target.chmod(0o600)
            identities[slot]={'agent_id':agent,'profile':str(target),'permissions':'typed memory/evidence/challenge/support/claims/handoffs, ONLY this task; task creation denied; MCP procedure approval disabled'}
        if not add_client:
            with owner.session(task) as session:
                session.observe('Owner prepared a synthetic software collaboration fixture. Codex/Claude/Antigravity aliases identify credentials, not observed client software.')
                procedure=session.propose_procedure('Review before integrating a code change',steps=['Reproduce the failing test in your own worktree and record the exact command/result','Compare hypotheses with fixture timing/config evidence; challenge contradicted claims','Review the proposed diff, run the full fixture tests, and cite source/evidence IDs before completing handoff'])
            owner.approve_procedure(task,procedure.id,expected_version=1,reason='Local owner setup approved the fixture verification procedure')
            result={'task_id':task,'synthetic':True,'procedure_id':procedure.id,'ui_url':base+'/?task='+task,'private_folder':str(folder)}
        result.update(identities=identities,owner_cli_verification='PENDING_OWNER_VERIFICATION',owner_antigravity_ide='PENDING_OWNER_VERIFICATION',owner_antigravity_cli='PENDING_OWNER_VERIFICATION',installations_or_configs_touched=False)
        pending=folder/'setup.pending';pending.write_text(json.dumps(result,indent=2))
        if os.name!='nt':pending.chmod(0o600)
        pending.replace(folder/'setup.json')
        print(json.dumps(result,indent=2))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='collab_'+uuid.uuid4().hex[:8]);parser.add_argument('--url',default=os.environ.get('LOOM_URL','http://127.0.0.1:8000'));parser.add_argument('--add-client',choices=['antigravity']);a=parser.parse_args();asyncio.run(setup(a.name,a.url,a.add_client))

if __name__=='__main__':main()
