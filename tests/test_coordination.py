import asyncio
import subprocess
import sys
import pytest
from backend.app.auth import TokenAuthenticator
from backend.app.router import EventRouter
from .conftest import auth,uid,memory

pytestmark=pytest.mark.integration


async def test_SHARE_04_ISO_03_handoff(client,db,tokens):
    h=auth(tokens,'alpha:coordinator');v=auth(tokens,'alpha:verifier')
    m,_=await memory(client)
    request=dict(operation_id=uid(),to_agent_id='verifier',description='Compare synthetic deployment and Payments timing',related_memory_ids=[m['memory_id']])
    created=await client.post('/v1/tasks/incident_42/handoffs',json=request,headers=h)
    assert created.status_code==201,created.text
    hid=created.json()['handoff_id'];path='/v1/tasks/incident_42/handoffs/'+hid
    assert (await client.get(path,headers=v)).json()['related_memory_ids']==[m['memory_id']]
    assert (await client.patch(path,json={'operation_id':uid(),'expected_version':1,'status':'done'},headers=v)).status_code==409
    accepted={'operation_id':uid(),'expected_version':1,'status':'accepted'}
    response=await client.patch(path,json=accepted,headers=v)
    assert response.status_code==201,response.text
    done=await client.patch(path,json={'operation_id':uid(),'expected_version':2,'status':'done'},headers=v)
    assert done.status_code==201
    assert (await client.patch(path,json=accepted,headers=v)).json()==response.json()
    p=TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    before=await db.query(p,'MATCH (n) RETURN count(n) AS n')
    bad=await client.post('/v1/tasks/incident_42/handoffs',json={**request,'operation_id':uid(),'to_agent_id':'beta_verifier'},headers=h)
    assert bad.status_code==404
    assert await db.query(p,'MATCH (n) RETURN count(n) AS n')==before


async def test_SHARE_02_SHARE_03_router_process_recovery(client,db,tokens):
    # Drain older events with the router stopped before creating a new one.
    router=EventRouter(db)
    while (await router.run_once())['events_dispatched']:pass
    for role in ('investigator','verifier','coordinator'):
        r=await client.post('/v1/tasks/incident_42/subscriptions',headers=auth(tokens,'alpha:'+role),json={'operation_id':uid(),'enabled':True})
        assert r.status_code==201
    m,_=await memory(client)
    p=TokenAuthenticator().authenticate(tokens['alpha:verifier'])
    pending=await db.query(p,'MATCH (e:MemoryEvent {id:$id}) RETURN e.dispatch_status AS status',{'id':m['event_id']})
    assert pending[0]['status']=='pending'
    child=await asyncio.create_subprocess_exec(sys.executable,'-m','scripts.router','--once','--crash-after','1',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    out,err=await child.communicate()
    assert child.returncode==86,(out,err)
    assert (await db.query(p,'MATCH (e:MemoryEvent {id:$id}) RETURN e.dispatch_status AS status',{'id':m['event_id']}))[0]['status']=='pending'
    await router.run_once();await router.run_once()
    counts=await db.query(p,'MATCH (i:InboxItem {event_id:$id}) RETURN i.agent_id AS actor,count(i) AS n',{'id':m['event_id']})
    assert len(counts)==3 and all(r['n']==1 for r in counts)
    inbox=[];cursor=''
    while True:
        page=(await client.get('/v1/inbox',params={'after':cursor,'limit':100},headers=auth(tokens,'alpha:verifier'))).json()
        inbox+=page['items']
        if not page['next_cursor']:break
        cursor=page['next_cursor']
    item=next(i for i in inbox if i['event_id']==m['event_id'])
    assert item['event']['target_id']==m['memory_id']
    marked=await client.post('/v1/inbox/'+item['id']+'/read',headers=auth(tokens,'alpha:verifier'),json={'operation_id':uid()})
    assert marked.status_code==201
    assert (await client.post('/v1/inbox/'+item['id']+'/read',json={'operation_id':uid()})).status_code==404
    for role in ('alpha:unassigned','beta:verifier'):
        others=(await client.get('/v1/inbox',headers=auth(tokens,role))).json()['items']
        assert not any(i['event_id']==m['event_id'] for i in others)
