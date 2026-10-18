import asyncio
import base64
import json
import pytest
import httpx
from loomline import AsyncLoomlineClient,LoomlineClient,ConflictError,NotFoundError,AuthorizationError,CommitOutcomeUnknown
from backend.app.main import app
from .conftest import uid


@pytest.mark.integration
async def test_sdk_real_db_continuity_events_trace_and_handoff(client,tokens):
    def sdk(identity):return AsyncLoomlineClient('http://test',token=tokens[identity],transport=httpx.ASGITransport(app=app),max_attempts=1)
    async with sdk('alpha:coordinator') as c,sdk('alpha:investigator') as a,sdk('alpha:verifier') as b:
        task=(await c.create_task('SDK synthetic investigation',assigned_agent_ids=['investigator','verifier'],synthetic=True)).task_id
        assert (await c.capabilities())['discovery']=='server'
        assert any(t['id']==task for t in (await a.list_scopes())['tasks'])
        async with a.session(task) as s:
            episode=await s.observe('Synthetic SDK observation')
            hypothesis=await s.hypothesize('Deployment might explain synthetic errors')
            oid=uid();first=await s.observe('Replay me',operation_id=oid)
            replay=await s.observe('Replay me',operation_id=oid)
            assert first==replay and first.outcome=='CREATED' and replay.outcome=='REPLAYED'
            with pytest.raises(ConflictError):await s.observe('Changed replay',operation_id=oid)
        assert (await b.resolve(episode.reference)).created_by=='investigator'
        ev=await b.record_evidence(task,content='Upstream evidence contradicts deployment-only claim',source_type='synthetic',source_ref='synthetic:sdk',observed_at='2026-10-17T12:00:00Z')
        await b.challenge(task,hypothesis.memory_id,evidence_id=ev.evidence_id,reason='Contrary timing',expected_version=1)
        trace=await b.trace(hypothesis.reference)
        assert trace['memory']['status']=='disputed' and trace['source_turn']['id']==trace['memory']['source_turn_id']
        assert trace['memory']['challenges'][0]['id']==ev.evidence_id
        assert len(trace['events'])==2
        async with c.session(task) as s:
            procedure=await s.propose_procedure('Review upstream timing',steps=['Read evidence','Compare timestamps'])
        with pytest.raises(AuthorizationError):await a.approve_procedure(task,procedure.memory_id,expected_version=1,reason='Not authorized')
        await c.approve_procedure(task,procedure.memory_id,expected_version=1,reason='Reviewed')
        handoff=await c.handoff(task,'verifier','Resume using approved procedure',related_memory_ids=[hypothesis.memory_id,procedure.memory_id])
        resumed=await b.resume_task(task)
        assert resumed['new_session'] and resumed['context']['procedural'] and resumed['history']['items']
        pack=await b.context_pack(task,goal='Resume safely',max_tokens=512)
        assert pack['estimated_tokens']<=512 and pack['untrusted_data']
        assert all(m['status']=='disputed' for m in pack['memories'] if m['assertion_type']=='hypothesis')
        await b.accept_handoff(task,handoff.handoff_id,expected_version=1)
        await b.complete_handoff(task,handoff.handoff_id,expected_version=2)
        with pytest.raises(ConflictError):await b.complete_handoff(task,handoff.handoff_id,expected_version=2)
        seen=[];cursor=None
        while True:
            page=await b.changes_since(task,cursor,limit=2);seen.extend(page['items'])
            if not page['items']:break
            cursor=page['next_cursor']
        assert [x['seq'] for x in seen]==list(range(1,len(seen)+1))
        assert len({e['id'] for e in seen})==len(seen)
        # A failed/abandoned watch batch does not advance any durable cursor.
        stream=b.watch(task,max_polls=1);batch=await anext(stream);await stream.aclose()
        stream=b.watch(task,max_polls=1);same=await anext(stream);assert batch['items']==same['items'];same.ack();await stream.aclose()
        expired=base64.urlsafe_b64encode(json.dumps(['changes-old','alpha',task,0]).encode()).decode()
        with pytest.raises(Exception) as error:await b.changes_since(task,expired)
        assert error.value.code=='CURSOR_EXPIRED'
        async with sdk('beta:verifier') as other:
            with pytest.raises(NotFoundError):await other.resolve(hypothesis.reference)
        async with sdk('alpha:unassigned') as other:
            with pytest.raises(NotFoundError):await other.get_context(task)


@pytest.mark.integration
async def test_sdk_concurrent_changes_and_support_keep_claim_status(client,tokens):
    async with AsyncLoomlineClient('http://test',token=tokens['alpha:coordinator'],transport=httpx.ASGITransport(app=app),max_attempts=1) as c:
        task=(await c.create_task('Concurrent events',assigned_agent_ids=['verifier'],synthetic=True)).task_id
        async with c.session(task) as s:
            await asyncio.gather(*(s.observe('Concurrent synthetic '+str(i)) for i in range(15)))
            hypothesis=await s.hypothesize('Deployment may be involved')
        events=await c.changes_since(task,limit=100)
        assert [e['seq'] for e in events['items']]==list(range(1,17))
        ev=await c.record_evidence(task,content='Supporting deployment regression',source_type='synthetic',source_ref='synthetic:support',observed_at='2026-10-17T12:00:00Z')
        await c.support(task,hypothesis.memory_id,evidence_id=ev.evidence_id,reason='Support preserves uncertainty',expected_version=1)
        memory=await c.get_memory(task,hypothesis.memory_id)
        assert memory.status=='proposed' and memory.version==2 and memory.support
        assert (await c.changes_since(task,events['next_cursor']))['items'][0]['seq']==17


@pytest.mark.integration
async def test_sdk_paginated_history_sessions_inbox_and_cursor_scope(client,db,tokens):
    from backend.app.router import EventRouter
    async with AsyncLoomlineClient('http://test',token=tokens['alpha:coordinator'],transport=httpx.ASGITransport(app=app),max_attempts=1) as c:
        task=(await c.create_task('Paginated public SDK continuity',assigned_agent_ids=['verifier'])).task_id
        await c.subscribe(task)
        ids=[]
        for i in range(3):
            async with c.session(task) as s:ids.append((await s.observe('Pagination observation '+str(i))).id)
        history=[u async for u in c.iter_history(task,limit=1)];sessions=[s async for s in c.iter_sessions(task,limit=1)]
        assert len(history)==len({u['id'] for u in history})==3
        assert len(sessions)==len({s['id'] for s in sessions})==3
        router=EventRouter(db)
        for _ in range(10):
            if not (await router.run_once())['events_dispatched']:break
        inbox=[i async for i in c.iter_inbox(task_id=task,limit=1)]
        assert len(inbox)==len({i['id'] for i in inbox})==3 and {i['event']['target_id'] for i in inbox}==set(ids)
        oid=uid();first=await c.mark_inbox_read(inbox[0]['id'],oid);assert await c.mark_inbox_read(inbox[0]['id'],oid)==first
        assert next(i for i in (await c.get_inbox(task_id=task))['items'] if i['id']==inbox[0]['id'])['status']=='read'
        for scope,seq,code in [('different_task',0,'INVALID_CURSOR'),(task,99999,'CURSOR_AHEAD')]:
            cursor=base64.urlsafe_b64encode(json.dumps(['changes-v1','alpha',scope,seq]).encode()).decode()
            with pytest.raises(Exception) as error:await c.changes_since(task,cursor)
            assert error.value.code==code


def test_sync_transport_timeout_recovers_original_operation_without_second_write():
    sent=[]
    def transport(request):
        sent.append((request.method,request.url.path,request.content))
        if request.method=='POST':raise httpx.ReadTimeout('Synthetic network loss')
        return httpx.Response(200,json={'memory_id':'mem_original','event_id':'evt_original'})
    with LoomlineClient('http://test',token='synthetic-private-token',transport=httpx.MockTransport(transport)) as c:
        result=c.observe('task', 'Synthetic transport edge',session_id='session',source_turn_id='turn',operation_id='same_intent')
        assert result.memory_id=='mem_original' and len(sent)==2
        assert sent[1][1]=='/v1/tasks/task/operations/same_intent'
        assert 'synthetic-private-token' not in repr(c)


async def test_async_transport_retries_same_payload_and_safe_errors():
    sent=[]
    async def transport(request):
        sent.append(request.content)
        if len(sent)==1:return httpx.Response(429,json={'error':{'code':'OVERLOADED'}},headers={'Retry-After':'0'})
        return httpx.Response(201,json={'memory_id':'mem','event_id':'event'})
    async with AsyncLoomlineClient('http://test',token='synthetic',transport=httpx.MockTransport(transport)) as c:
        result=await c.observe('task','Same payload',session_id='session',source_turn_id='turn',operation_id='retry_intent')
        assert result.outcome=='CREATED' and sent[0]==sent[1]
