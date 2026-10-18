"""Recreate only this project's DB container, retaining the named volume."""
import asyncio
import json
from pathlib import Path
import subprocess
import hashlib
from agents.shared_client import AgentClient,op
from backend.app.auth import TokenAuthenticator
from backend.app.config import ROOT,settings
from backend.app.db import Database


async def snapshot(db,p,ids):
    query='MATCH (t:Task {id:\'incident_42\'})-[:HAS_SESSION]->(s:Session {id:$sid})-[:HAS_TURN]->(u:Turn {id:$tid}) MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$mid})-[:DERIVED_FROM]->(u) MATCH (ev:MemoryEvent {id:$eid})-[:RECORDS]->(m) MATCH (t)-[:HAS_HANDOFF]->(h:Handoff {id:$hid})-[:REFERS_TO]->(m) RETURN s.id AS session,u.id AS turn,u.seq AS seq,m.id AS memory,m.content AS content,ev.id AS event,ev.dispatch_status AS dispatch_status,h.id AS handoff,h.status AS handoff_status'
    result=await db.query(p,query,ids)
    assert len(result)==1,result
    return result[0]


async def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);args=parser.parse_args()
    namespace=settings.loom_graph_namespace
    if not namespace.startswith('release_') or args.project!='loomline-release-'+namespace.removeprefix('release_'):
        raise SystemExit('Refusing recreation outside an isolated release namespace/project')
    compose=['docker','compose','--project-name',args.project,'--profile','app']
    c=AgentClient('investigator')
    assert c.request('GET','/health')['namespace_id']==hashlib.sha256(namespace.encode()).hexdigest()[:16], 'HTTP namespace mismatch'
    # The router's dispatch mutation is not part of the persistence comparison.
    # Pause only this strictly matched disposable release project's worker.
    subprocess.run(compose+['stop','router'],check=True)
    try:
        await verify(c,compose,args.project)
    finally:
        subprocess.run(compose+['up','-d','router','--wait'],check=True)


async def verify(c,compose,project):
    sid=c.session();tid=c.turn(sid,'Synthetic container recreation observation','tool')
    memory,_=c.remember(sid,tid,'Synthetic durable proof '+op())
    coord=AgentClient('coordinator')
    handoff=coord.request('POST','/v1/tasks/incident_42/handoffs',json=dict(operation_id=op(),to_agent_id='verifier',description='Synthetic durable container recovery handoff',related_memory_ids=[memory['memory_id']]))
    ids={'sid':sid,'tid':tid,'mid':memory['memory_id'],'eid':memory['event_id'],'hid':handoff['handoff_id']}
    tokens=json.loads((ROOT/'.secrets/agent_tokens.json').read_text());p=TokenAuthenticator().authenticate(tokens['alpha:investigator'])
    db=Database()
    try:
        config=await db.redis.config_get('appendonly','appendfsync','dir')
        assert config=={'appendonly':'yes','appendfsync':'always','dir':'/var/lib/falkordb/data'}
        before=await snapshot(db,p,ids)
    finally:await db.close()
    old=subprocess.check_output(compose+['ps','-q','falkordb'],text=True).strip()
    mounts=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Mounts}}',old],text=True))
    assert any(m['Type']=='volume' and m['Name']==project+'_graph_data' and m['Destination']=='/var/lib/falkordb/data' for m in mounts), 'Unexpected data mount; recreation refused'
    subprocess.run(compose+['up','-d','--force-recreate','--no-deps','falkordb','--wait'],check=True)
    new=subprocess.check_output(compose+['ps','-q','falkordb'],text=True).strip()
    assert old!=new
    db=Database()
    try:
        after=await snapshot(db,p,ids)
        assert before==after
    finally:await db.close()
    # The gateway reconnects too, proving API resolution after DB replacement.
    assert c.request('GET','/v1/tasks/incident_42/memories/'+memory['memory_id'])['source_turn_id']==tid
    report={'status':'PASS','container_changed':True,'volume':project+'_graph_data','effective_persistence':config,'before':before,'after':after}
    Path('artifacts/persistence.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(main())
