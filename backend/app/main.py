import asyncio
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError, ResponseError
from .auth import authenticated, TenantContext
from .db import Database
from .errors import DomainError, parse_memory_reference, MEMORY_REFERENCE_GUIDANCE
from .models import SessionRequest, TurnRequest, MemoryRequest, EvidenceRequest, ChallengeRequest, StatusRequest, HandoffRequest, HandoffStatusRequest, SubscriptionRequest, Intent, InferenceRequest
from .repository import Repository
from .schema import bootstrap
from .lease import InstanceLease


@asynccontextmanager
async def lifespan(app):
    import multiprocessing
    if multiprocessing.parent_process() is not None:
        raise RuntimeError('Loomline NIM manager requires a standalone single-worker gateway')
    app.state.db = Database()
    app.state.lease=InstanceLease(app.state.db,'gateway')
    try:
        await app.state.lease.acquire()
        await bootstrap(app.state.db)
        app.state.repo = Repository(app.state.db)
        from .nvidia import NvidiaInferenceService
        app.state.nvidia=NvidiaInferenceService(lease=app.state.lease)
        try:yield
        finally:await app.state.nvidia.close()
    finally:
        await app.state.lease.close()
        await app.state.db.close()


app = FastAPI(title='Loomline', version='0.1.0', lifespan=lifespan)
request_slots=asyncio.Semaphore(128)


@app.middleware('http')
async def bounded_requests(request,call_next):
    try:await asyncio.wait_for(request_slots.acquire(),timeout=.5)
    except TimeoutError:return JSONResponse({'error':{'code':'OVERLOADED'}},status_code=429)
    try:return await call_next(request)
    finally:request_slots.release()


@app.exception_handler(DomainError)
async def domain_error(request, exc):
    error={'code':exc.code}
    if exc.code=='INVALID_MEMORY_REFERENCE':error['guidance']=MEMORY_REFERENCE_GUIDANCE
    return JSONResponse({'error':error}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Deliberately omit the rejected payload: it might contain credentials.
    return JSONResponse({'error': {'code':'INVALID_INPUT'}}, status_code=400)


@app.exception_handler(RedisTimeoutError)
async def timeout_error(request, exc):
    return JSONResponse({'error': {'code':'COMMIT_OUTCOME_UNKNOWN' if request.method != 'GET' else 'DATABASE_UNAVAILABLE'}}, status_code=504 if request.method != 'GET' else 503)


@app.exception_handler(RedisConnectionError)
async def unavailable(request, exc):
    return JSONResponse({'error': {'code':'DATABASE_UNAVAILABLE'}}, status_code=503)


@app.exception_handler(ResponseError)
async def database_error(request, exc):
    if str(exc).strip().lower()=='max pending queries exceeded':
        return JSONResponse({'error': {'code':'OVERLOADED'}}, status_code=429)
    return JSONResponse({'error': {'code':'DATABASE_UNAVAILABLE'}}, status_code=503)


def repo(request: Request):
    return request.app.state.repo


def committed(result):
    body, created = result
    return JSONResponse(body, status_code=201 if created else 200)


@app.get('/health')
async def health(request: Request):
    await request.app.state.db.redis.ping()
    if hasattr(request.app.state,'lease') and not request.app.state.lease.valid():
        raise DomainError(503,'SINGLE_INSTANCE_REQUIRED')
    import hashlib
    return {'status':'ok','schema_ready':request.app.state.db.ready,'workers':1,'namespace_id':hashlib.sha256(request.app.state.db.config.loom_graph_namespace.encode()).hexdigest()[:16]}


@app.post('/v1/tasks/{task}/sessions')
async def create_session(task: str, req: SessionRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.create_session(p, task, req))


@app.post('/v1/demo-runs')
async def demo_run(req: Intent,p=Depends(authenticated),r=Depends(repo)):
    return committed(await r.create_demo_run(p,req))


@app.get('/v1/tasks/{task}/sessions')
async def sessions(task: str, after: str='', limit: int=Query(100,ge=1,le=100), p=Depends(authenticated), r=Depends(repo)):
    items=await r.sessions(p,task,after,limit)
    return {'items':items,'next_cursor':items[-1]['id'] if len(items)==limit else None}


@app.get('/v1/tasks/{task}/turns')
async def task_history(task: str, before: str=Query('',max_length=512), limit: int=Query(20,ge=1,le=100), p=Depends(authenticated), r=Depends(repo)):
    return await r.history(p,task,before,limit)


@app.post('/v1/sessions/{sid}/turns')
async def append_turn(sid: str, req: TurnRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.append_turn(p, sid, req))


@app.get('/v1/sessions/{sid}/turns')
async def turns(sid: str, after_seq: int=Query(0,ge=0), limit: int=Query(100,ge=1,le=100), p=Depends(authenticated), r=Depends(repo)):
    return await r.turns(p, sid, after_seq, limit)


@app.post('/v1/tasks/{task}/memories')
async def memory_write(task: str, req: MemoryRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.create_memory(p, task, req))


@app.get('/v1/tasks/{task}/memories/{mid}')
async def memory_read(task: str, mid: str, p=Depends(authenticated), r=Depends(repo)):
    return await r.memory(p, task, mid)


@app.get('/v1/resolve')
async def resolve(reference: str=Query(max_length=400), p=Depends(authenticated), r=Depends(repo)):
    return await r.memory(p, *parse_memory_reference(reference))


@app.get('/v1/tasks/{task}/operations/{oid}')
async def operation(task: str, oid: str, p=Depends(authenticated), r=Depends(repo)):
    result = await r.operation(p, task, oid)
    if result is None:
        raise DomainError(404,'NOT_FOUND')
    return result


@app.post('/v1/tasks/{task}/evidence')
async def evidence(task: str, req: EvidenceRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.evidence(p,task,req))


@app.post('/v1/tasks/{task}/memories/{mid}/challenges')
async def challenge(task: str, mid: str, req: ChallengeRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.challenge(p,task,mid,req))


@app.patch('/v1/tasks/{task}/memories/{mid}/status')
async def status(task: str, mid: str, req: StatusRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.memory_status(p,task,mid,req))


@app.get('/v1/tasks/{task}/context')
async def context(task: str, limit: int=Query(10,ge=1,le=20), query: str|None=Query(None,max_length=100), entity_id: str|None=Query(None,max_length=128), p=Depends(authenticated), r=Depends(repo)):
    return await r.context(p,task,limit,query,entity_id)


@app.get('/v1/tasks/{task}/decision-context')
async def decision_context(task: str, entity_id: str='checkout', p=Depends(authenticated), r=Depends(repo)):
    return await r.decision_context(p,task,entity_id)


@app.post('/v1/tasks/{task}/handoffs')
async def handoff_create(task: str, req: HandoffRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.create_handoff(p,task,req))


@app.get('/v1/tasks/{task}/handoffs/{hid}')
async def handoff_get(task: str, hid: str, p=Depends(authenticated), r=Depends(repo)):
    return await r.handoff(p,task,hid)


@app.patch('/v1/tasks/{task}/handoffs/{hid}')
async def handoff_status(task: str, hid: str, req: HandoffStatusRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.handoff_status(p,task,hid,req))


@app.post('/v1/tasks/{task}/subscriptions')
async def subscription(task: str, req: SubscriptionRequest, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.subscription(p,task,req))


@app.get('/v1/inbox')
async def inbox(after: str='', limit: int=Query(100,ge=1,le=100), task_id: str|None=Query(None,max_length=128), p=Depends(authenticated), r=Depends(repo)):
    return await r.inbox(p,after,limit,task_id)


@app.post('/v1/inbox/{iid}/read')
async def inbox_read(iid: str, req: Intent, p=Depends(authenticated), r=Depends(repo)):
    return committed(await r.inbox_read(p,iid,req))


@app.post('/v1/agent-inference')
async def inference(req: InferenceRequest, request: Request, p=Depends(authenticated), r=Depends(repo)):
    return await request.app.state.nvidia.infer(p,req,r)


@app.get('/v1/inference-status')
async def inference_status(request: Request, p=Depends(authenticated), r=Depends(repo)):
    await r.authorize(p,'incident_42')
    service=request.app.state.nvidia
    metrics=[m for m in service.metrics if m['role']==p.role]
    return {'model':service.config.nvidia_model,'configured':bool(service.key(p.role)),'live_enabled':service.config.nvidia_live_enabled,'shared_key_fallback':not bool(getattr(service.config,'nvidia_'+p.role+'_api_key','')),'metrics':metrics,'aggregate_limit_rpm':service.quota.rpm,'maximum_inflight':3,'single_worker_required':True}


@app.get('/v1/me')
async def me(p=Depends(authenticated)):
    return {'tenant_id':p.tenant_id,'agent_id':p.agent_id,'role':p.role,
            'read_only':p.role=='viewer',
            'task_scope_restricted':p.allowed_task_ids is not None,
            'can_create_projects':p.role=='coordinator' and p.allowed_task_ids is None}


@app.post('/v1/agent-inference/probe')
async def inference_probe(req: InferenceRequest, request: Request, p=Depends(authenticated), r=Depends(repo)):
    return await request.app.state.nvidia.probe(p,req,r)


from pathlib import Path
from fastapi.staticfiles import StaticFiles


@app.get('/help/{document}', include_in_schema=False)
async def public_help(document: str):
    """Explicit public manuals only; never expose arbitrary workspace files."""
    from fastapi.responses import Response
    from .config import ROOT
    documents = {'README': 'README.md', 'START_HERE': 'docs/getting-started.md',
                 'AGENT_SETUP': 'docs/connect-agents.md', 'STUDIO_AUTH': 'docs/security.md',
                 'GRAPH_MODEL': 'docs/graph-model.md', 'MEMORY_GRAPH_GUIDE': 'docs/memory-graph.md'}
    name = document[:-3] if document.lower().endswith('.md') else document
    relative = documents.get(name.upper())
    if relative is None:
        return JSONResponse({'error': {'code': 'NOT_FOUND'}}, status_code=404)
    path = ROOT / relative
    if not path.is_file():
        return JSONResponse({'error': {'code': 'NOT_FOUND'}}, status_code=404)
    return Response(path.read_text(encoding='utf-8'), media_type='text/markdown; charset=utf-8',
                    headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'public, max-age=300'})


from .platform import router as platform_router
app.include_router(platform_router)
from .coordination import router as coordination_router
app.include_router(coordination_router)
from .graph_view import router as graph_view_router
app.include_router(graph_view_router)
frontend=Path(__file__).resolve().parents[2]/'frontend'/'dist'
if frontend.exists():
    app.mount('/',StaticFiles(directory=frontend,html=True),name='demo-ui')
