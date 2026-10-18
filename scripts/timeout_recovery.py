"""Real HTTP read timeout after sending a write; recover the committed operation."""
import asyncio
import json
from pathlib import Path
import time
import httpx
from agents.shared_client import AgentClient,op
from backend.app.auth import TokenAuthenticator
from backend.app.db import Database


async def counts(intent):
    tokens=json.loads(Path('.secrets/agent_tokens.json').read_text())
    p=TokenAuthenticator().authenticate(tokens['alpha:investigator']);db=Database()
    try:return await db.query(p,"MATCH (m:Memory {operation_id:$op}) MATCH (e:MemoryEvent {operation_id:$op,type:'MEMORY_CREATED'})-[:RECORDS]->(m) RETURN count(m) AS n",{'op':intent})
    finally:await db.close()


def main():
    c=AgentClient('investigator');sid=c.session();tid=c.turn(sid,'Synthetic timeout recovery source','tool')
    body=dict(operation_id=op(),session_id=sid,source_turn_id=tid,**{'class':'episodic'},assertion_type='observation',status='active',content='Synthetic network timeout recovery proof')
    timed_out=False
    try:c.http.post('/v1/tasks/incident_42/memories',json=body,timeout=httpx.Timeout(connect=5,write=5,pool=5,read=.000001))
    except httpx.ReadTimeout:timed_out=True
    assert timed_out,'Expected a real HTTP read timeout'
    recovered=None
    for _ in range(50):
        response=c.http.get('/v1/tasks/incident_42/operations/'+body['operation_id'])
        if response.status_code==200:recovered=response.json();break
        time.sleep(.02)
    assert recovered,'Initial timed-out write did not commit; cannot claim outcome recovery'
    replay=c.request('POST','/v1/tasks/incident_42/memories',json=body)
    assert replay==recovered
    assert asyncio.run(counts(body['operation_id']))[0]['n']==1
    report={'status':'PASS','actual_http_read_timeout':True,'operation_recovered_before_retry':True,'single_memory_and_creation_event':True,'operation_id':body['operation_id']}
    Path('artifacts/timeout_recovery.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
