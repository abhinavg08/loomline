"""Trusted local operator revocation; never touches coding-agent installations."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from backend.app.config import ROOT,settings
from backend.app.db import Database
from .sync_auth_registry import sync

async def revoke(tenant,agent):
    if tenant not in settings.tenant_graphs:raise SystemExit('Unknown configured tenant')
    private=ROOT/'.secrets';lock=private/'operator-provision.lock'
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        auth=Path(settings.loom_auth_file)
        if not auth.is_absolute():auth=ROOT/auth
        records=json.loads(auth.read_text());removed=[h for h,p in records.items() if p['tenant_id']==tenant and p['agent_id']==agent]
        if not removed:raise SystemExit('No active credential found; nothing changed')
        db=Database()
        try:
            await db.client.select_graph(settings.tenant_graphs[tenant]).query('MATCH (a:Agent {id:$id}) SET a.enabled=false RETURN a.id',{'id':agent})
        finally:await db.close()
        for h in removed:records.pop(h)
        temporary=auth.with_suffix('.pending');temporary.write_text(json.dumps(records,indent=2))
        if os.name!='nt':temporary.chmod(0o600)
        temporary.replace(auth);sync(ROOT)
        print(json.dumps({'status':'REVOKED','agent_id':agent,'tenant_id':tenant,'credentials_removed':len(removed),'history_preserved':True,'client_configuration_modified':False}))
    finally:os.close(descriptor);lock.unlink()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tenant',required=True);parser.add_argument('--agent-id',required=True);a=parser.parse_args();asyncio.run(revoke(a.tenant,a.agent_id))

if __name__=='__main__':main()
