"""Verify real task-bound provisioning/revocation using a newly owned identity."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
from loomline import LoomlineClient,AuthenticationError,AuthorizationError,NotFoundError
from backend.app.config import ROOT
from .provision_agent import provision
from .revoke_agent import revoke

async def main():
    owner_tokens=json.loads((ROOT/'.secrets/agent_tokens.json').read_text());base='http://127.0.0.1:8000'
    with LoomlineClient(base,token=owner_tokens['alpha:coordinator']) as owner:
        task=owner.create_task('Owned MCP provisioning verification',assigned_agent_ids=['coordinator']).task_id
    agent='mcp_operator_check_'+uuid.uuid4().hex[:8]
    await provision(SimpleNamespace(tenant='alpha',agent_id=agent,role='coordinator',task=task,restrict_to_task=True,deny_procedure_approval=True))
    token=(ROOT/'.secrets'/(agent+'.token')).read_text().strip()
    report={'status':'IN_PROGRESS','agent_id':agent,'task_id':task,'checks':[],'original_keys_modified':False,'history_deleted':False}
    try:
        with LoomlineClient(base,token=token) as c:
            assert c.whoami().agent_id==agent;assert [t['id'] for t in c.list_tasks()['items']]==[task];report['checks'].append('private task-bound credential and live directory-bound auth registry')
            with c.session(task) as s:procedure=s.propose_procedure('Owned provisioning test procedure',steps=['Review independently'])
            try:c.approve_procedure(task,procedure.id,expected_version=1,reason='Forbidden self-approval')
            except AuthorizationError:report['checks'].append('procedure approval rejected by backend, including direct SDK bypass')
            else:raise AssertionError('Procedure approval permission bypass')
            try:c.create_task('Forbidden credential scope escape',assigned_agent_ids=[agent])
            except AuthorizationError:report['checks'].append('task creation rejected for scoped coordinator')
            else:raise AssertionError('Task creation scope bypass')
            try:c.get_context('incident_42')
            except NotFoundError:report['checks'].append('exact unassigned task denied')
            else:raise AssertionError('Wrong task access')
        await revoke('alpha',agent)
        with LoomlineClient(base,token=token) as c:
            try:c.whoami()
            except AuthenticationError:report['checks'].append('revocation effective immediately without gateway recreation')
            else:raise AssertionError('Revoked credential accepted')
        with LoomlineClient(base,token=owner_tokens['alpha:coordinator']) as owner:
            assert owner.get_memory(task,procedure.id).status=='proposed';report['checks'].append('revocation preserves source and memory history')
        report['status']='PASS'
    finally:
        path=ROOT/'artifacts/mcp/operator.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':asyncio.run(main())
