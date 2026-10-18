"""Local operator-only onboarding. Credentials go to a private file, never stdout."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from backend.app.config import ROOT,settings
from backend.app.db import Database

async def provision(args):
    if args.tenant not in settings.tenant_graphs:raise SystemExit('Unknown configured tenant')
    if getattr(args,'restrict_to_task',False) and not args.task:raise SystemExit('Restricted credential requires a task')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',args.agent_id):raise SystemExit('Invalid agent ID')
    private=ROOT/'.secrets';private.mkdir(exist_ok=True)
    target=(private/(args.agent_id+'.token')).resolve()
    if target.parent!=private.resolve() or target.exists():raise SystemExit('Refusing existing credential output')
    auth=Path(settings.loom_auth_file)
    if not auth.is_absolute():auth=ROOT/auth
    lock=private/'operator-provision.lock'
    try:descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise SystemExit('Another local provisioning operation is active')
    try:
        records=json.loads(auth.read_text())
        if any(p['tenant_id']==args.tenant and p['agent_id']==args.agent_id for p in records.values()):raise SystemExit('Identity already exists; no credential overwritten')
        db=Database()
        try:
            graph=db.client.select_graph(settings.tenant_graphs[args.tenant])
            if (await graph.ro_query('MATCH (a:Agent {id:$id}) RETURN a.id',{'id':args.agent_id})).result_set:raise SystemExit('Graph identity already exists')
            if args.task and not (await graph.ro_query('MATCH (t:Task {id:$task}) RETURN t.id',{'task':args.task})).result_set:raise SystemExit('Task not found')
            query='CREATE (a:Agent {id:$id,role:$role,enabled:true,created_at:$now}) '
            if args.task:query+='WITH a MATCH (t:Task {id:$task}) CREATE (t)-[:ASSIGNED_TO]->(a) '
            await graph.query(query+'RETURN a.id',{'id':args.agent_id,'role':args.role,'task':args.task,'now':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
        finally:await db.close()
        token=secrets.token_urlsafe(32)
        records[hashlib.sha256(token.encode()).hexdigest()]={'tenant_id':args.tenant,'agent_id':args.agent_id,'role':args.role}
        if getattr(args,'restrict_to_task',False):
            records[hashlib.sha256(token.encode()).hexdigest()]['allowed_task_ids']=[args.task]
        if args.role=='viewer' or getattr(args,'deny_procedure_approval',False):
            records[hashlib.sha256(token.encode()).hexdigest()]['can_approve_procedures']=False
        with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as output:output.write(token)
        temporary=auth.with_suffix('.pending')
        temporary.write_text(json.dumps(records,indent=2));temporary.replace(auth)
        from .sync_auth_registry import sync
        sync(ROOT)
        if os.name!='nt':target.chmod(0o600);auth.chmod(0o600)
        print(json.dumps({'status':'CREATED','agent_id':args.agent_id,'role':args.role,'tenant_id':args.tenant,'credential_file':str(target),'secret_printed':False}))
    finally:os.close(descriptor);lock.unlink()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tenant',required=True);parser.add_argument('--agent-id',required=True);parser.add_argument('--role',choices=['investigator','verifier','coordinator','viewer'],required=True);parser.add_argument('--task');parser.add_argument('--restrict-to-task',action='store_true');parser.add_argument('--deny-procedure-approval',action='store_true');asyncio.run(provision(parser.parse_args()))

if __name__=='__main__':main()
