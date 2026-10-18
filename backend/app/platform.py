"""Narrow, authorized developer-platform additions. Core wire routes are preserved."""
import base64
import hashlib
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,Query,Request
from fastapi.responses import JSONResponse
from pydantic import Field,field_validator
from .auth import authenticated
from .errors import DomainError,require,parse_memory_reference
from .models import Intent,Strict,ID,TurnRequest,InferenceRequest,ChallengeRequest
from .repository import AUTH,stable,now

router=APIRouter()
def repo(request:Request):return request.app.state.repo
def commit(result):return JSONResponse(result[0],status_code=201 if result[1] else 200)

@router.get('/v1/tasks/{task}/context-pack')
async def context_pack(task:str,goal:str=Query('',max_length=500),max_tokens:int=Query(2048,ge=256,le=8192),p=Depends(authenticated),r=Depends(repo)):
    from loomline.client import pack
    from loomline.errors import ValidationError as SDKValidationError
    try:return dict(pack(await r.context(p,task,limit=20),goal,max_tokens,('episodic','semantic','procedural')))
    except SDKValidationError as exc:raise DomainError(400,exc.code) from None

@router.get('/v1/tasks/{task}/integrity')
async def integrity(task:str,p=Depends(authenticated),r=Depends(repo)):
    rows=await r.read(p,task,"MATCH (t)-[:HAS_MEMORY]->(m:Memory) OPTIONAL MATCH (e:MemoryEvent {type:'MEMORY_CREATED'})-[:RECORDS]->(m) WITH m,count(e) AS events RETURN count(m) AS memories,sum(CASE WHEN events=1 THEN 0 ELSE 1 END) AS creation_event_violations")
    return {'task_id':task,'counts':rows[0] if rows else {'memories':0,'creation_event_violations':0},'source':'read-only authenticated FalkorDB query','consistency':'per-query snapshot'}

@router.get('/v1/verification')
async def verification(p=Depends(authenticated),r=Depends(repo)):
    from .config import ROOT
    result={}
    for name in ('frameworks','reliability'):
        file=ROOT/'artifacts/platform'/(name+'.json')
        if file.exists() and file.stat().st_size<100_000:
            data=json.loads(file.read_text())
            # Reports produced by fixed local CLIs. No arbitrary path/file API.
            if name=='frameworks':
                for entry in data.values():
                    for mode in ('live','offline'):
                        task=entry.get(mode+'_task_id')
                        if task:
                            try:
                                require(entry.get('tenant_id')==p.tenant_id,404,'NOT_FOUND')
                                await r.authorize(p,task)
                            except DomainError:
                                entry.pop(mode+'_task_id',None);entry[mode]='not available in your task scope'
                    entry.pop('tenant_id',None)
            result[name]=data
    file=ROOT/'artifacts/mcp/protocol.json'
    if file.exists() and file.stat().st_size<100_000:
        data=json.loads(file.read_text())
        result['mcp']={k:data[k] for k in ('status','evidence_type','benchmark','checks','owner_codex_cli','owner_claude_cli','owner_antigravity_ide','owner_antigravity_cli','real_two_cli_exchange','real_three_client_exchange','test_suites','antigravity_configuration_checks') if k in data}
    return {'source':'local operator verification artifacts; not a remote attestation','results':result}

@router.get('/v1/model-status')
async def model_status(request:Request,p=Depends(authenticated)):
    service=request.app.state.nvidia
    return {'live_enabled':service.config.nvidia_live_enabled,'model':service.config.nvidia_model,'role_configured':bool(service.key(p.role)),'aggregate_rpm':service.quota.rpm,'max_concurrent':min(3,max(1,service.config.nvidia_max_concurrent_requests)),'quota_scope':'one server gateway instance; role keys do not multiply limits','metrics':[m for m in service.metrics if m['role']==p.role][-20:]}

class TaskRequest(Intent):
    title:str=Field(min_length=1,max_length=200)
    description:str|None=Field(default=None,min_length=1,max_length=1000)
    status:Literal['open','active','completed','archived']='open'
    assigned_agent_ids:list[str]=Field(min_length=1,max_length=20)
    synthetic:bool=False
    template:Literal['blank','checkout']='blank'
    _safe=field_validator('title','description')(lambda value: TurnRequest.redact(value) if value is not None else None)

class FrameworkRequest(Intent):
    framework:Literal['custom','langchain','langgraph','crewai','mcp']
    framework_version:str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.+-]+$')

class ReasonRequest(InferenceRequest):
    purpose:Literal['investigate','resume','continuity_trial']='investigate'
    goal:str=Field(min_length=1,max_length=500)
    include_shared_memory:bool=True
    _safe=field_validator('goal')(TurnRequest.redact.__func__)

class Plan(Strict):
    action:Literal['hypothesis','challenge','support','handoff','complete_handoff','request_context']
    content:str=Field(min_length=1,max_length=2000)
    evidence_ids:list[str]=Field(default_factory=list,max_length=10)
    memory_id:str|None=None
    expected_version:int|None=Field(default=None,ge=1)
    entity_ids:list[str]=Field(default_factory=list,max_length=10)
    to_agent_id:str|None=None
    related_memory_ids:list[str]=Field(default_factory=list,max_length=8)
    description:str|None=Field(default=None,max_length=1000)
    procedure_id:str|None=None
    consulted_steps:list[int]=Field(default_factory=list,max_length=20)
    handoff_id:str|None=None


@router.post('/v1/reasoning')
async def reasoning(req:ReasonRequest,request:Request,p=Depends(authenticated),r=Depends(repo)):
    service=request.app.state.nvidia
    require(p.role in ('investigator','verifier','coordinator'),403,'FORBIDDEN')
    await r.authorize(p,req.task_id)
    session=await r.session(p,req.session_id,owner=True);require(session['task_id']==req.task_id)
    require(req.include_shared_memory or req.purpose=='continuity_trial',400,'TRIAL_ONLY_CONTEXT_ABLATION')
    digest=hashlib.sha256(json.dumps(req.model_dump(),sort_keys=True).encode()).hexdigest()
    oid='nim_'+stable(p.tenant_id,p.agent_id,req.operation_id,'platform')
    async with service.intent_locks[p.role]:
        old=await r.operation(p,req.task_id,oid)
        if old:
            rows=await r.read(p,req.task_id,'MATCH (t)-[:HAS_SESSION]->(s:Session {id:$sid})-[:HAS_TURN]->(u:Turn {id:$id}) RETURN u',sid=req.session_id,id=old['turn_id'])
            require(rows,409,'IDEMPOTENCY_CONFLICT')
            saved=json.loads(rows[0]['u'].properties['content']);require(saved.get('request_hash')==digest,409,'IDEMPOTENCY_CONFLICT')
            return {**saved,'source_turn_id':old['turn_id'],'replayed':True}
        context=await r.context(p,req.task_id,limit=10) if req.include_shared_memory else {}
        paths=await r.decision_context(p,req.task_id) if req.include_shared_memory else {'paths':[]}
        schema={'action':'hypothesis' if p.role=='investigator' else 'challenge' if p.role=='verifier' and req.purpose!='resume' else 'complete_handoff' if req.purpose=='resume' else 'handoff','content':'concise visible explanation, exact evidence IDs and uncertainty','evidence_ids':['actual evidence ID']}
        if p.role=='investigator':schema.update(entity_ids=['checkout','deployment-17'])
        if p.role=='verifier' and req.purpose!='resume':schema.update(memory_id='existing hypothesis ID',expected_version=1)
        if p.role=='coordinator':schema.update(to_agent_id='assigned verifier ID',related_memory_ids=['hypothesis ID'],description='evidence-guided next step',procedure_id='active approved procedure ID',consulted_steps=[1,2])
        if req.purpose=='resume':schema.update(handoff_id='open handoff ID assigned to this actor',procedure_id='active approved procedure ID',consulted_steps=[1,2])
        if req.purpose=='continuity_trial':schema={'action':'complete_handoff or request_context','content':'concise explanation of evidence used or missing context','handoff_id':None,'procedure_id':None,'consulted_steps':[],'evidence_ids':[]}
        evidence=await r.read(p,req.task_id,'MATCH (t)-[:HAS_EVIDENCE]->(e:Evidence) RETURN e ORDER BY e.created_at DESC LIMIT 20') if req.include_shared_memory else []
        payload={'goal':req.goal,'purpose':req.purpose,'agent_id':p.agent_id,'context':context,'dependency_paths':paths['paths'],'evidence':[x['e'].properties for x in evidence]}
        request_metrics=[]
        text=await service.completion(p.role,payload,schema=schema,request_metrics=request_metrics)
        normalized=text.strip()
        if normalized.startswith('```') and normalized.endswith('```'):normalized='\n'.join(normalized.splitlines()[1:-1])
        try:plan=Plan.model_validate_json(normalized)
        except Exception as exc:
            details=[]
            if hasattr(exc,'errors'):details=[{'field':'.'.join(str(x) for x in e['loc']),'type':e['type']} for e in exc.errors(include_input=False)][:12]
            # Persist only schema diagnostics, never raw rejected output/reasoning.
            await r.append_turn(p,req.session_id,TurnRequest(operation_id=oid+'_rejected',role='assistant',content=json.dumps({'mode':'live_nvidia','validation':'rejected','diagnostics':details,'fenced':text.strip().startswith('```')})),internal=True)
            raise DomainError(503,'NIM_INVALID_PROPOSAL') from None
        evidence_ids={x['e'].properties['id'] for x in evidence}
        require(set(plan.evidence_ids)<=evidence_ids,400,'INVALID_EVIDENCE')
        allowed={'investigator':{'hypothesis'},'verifier':{'support','challenge'},'coordinator':{'handoff'}}
        if req.purpose=='resume':allowed[p.role]={'complete_handoff'}
        if req.purpose=='continuity_trial':allowed[p.role]={'complete_handoff','request_context'}
        if plan.action not in allowed[p.role]:
            await r.append_turn(p,req.session_id,TurnRequest(operation_id=oid+'_rejected',role='assistant',content=json.dumps({'mode':'live_nvidia','validation':'rejected','reason':'INVALID_ACTION','action':plan.action,'purpose':req.purpose,'role':p.role})),internal=True)
            raise DomainError(400,'INVALID_ACTION')
        if plan.action=='hypothesis':
            require(plan.evidence_ids and any(w in plan.content.lower() for w in ('might','may','could','hypothesis','uncertain')),400,'UNCERTAIN_HYPOTHESIS_REQUIRED')
            for entity in plan.entity_ids:require(await r.read(p,req.task_id,'MATCH (t)-[:HAS_ENTITY]->(e:Entity {id:$id}) RETURN e.id',id=entity))
        if plan.action in ('challenge','support'):
            m=await r.memory(p,req.task_id,plan.memory_id or '')
            require(m['assertion_type']=='hypothesis' and m['version']==plan.expected_version and plan.evidence_ids,409,'VERSION_CONFLICT')
        for mid in plan.related_memory_ids:await r.memory(p,req.task_id,mid)
        if plan.action in ('handoff','complete_handoff'):
            procedure=await r.memory(p,req.task_id,plan.procedure_id or '')
            require(procedure['class']=='procedural' and procedure['status']=='active',400,'APPROVED_PROCEDURE_REQUIRED')
            require(plan.consulted_steps and all(1<=i<=len(procedure['steps']) for i in plan.consulted_steps),400,'INVALID_PROCEDURE_STEPS')
        if plan.action=='handoff':
            require(plan.related_memory_ids and plan.description and plan.evidence_ids,400,'INVALID_HANDOFF_PLAN')
            require(await r.read(p,req.task_id,'MATCH (t)-[:ASSIGNED_TO]->(a2:Agent {id:$id,enabled:true}) RETURN a2.id',id=plan.to_agent_id))
        if plan.action=='complete_handoff':
            h=await r.handoff(p,req.task_id,plan.handoff_id or '')
            require(h['to_agent_id']==p.agent_id and h['status'] in ('open','accepted'),403,'FORBIDDEN')
        saved={'mode':'live_nvidia','model':service.config.nvidia_model,'request_hash':digest,'proposal':plan.model_dump(),'metrics':request_metrics,'shared_memory_included':req.include_shared_memory}
        turn=await r.append_turn(p,req.session_id,TurnRequest(operation_id=oid,role='assistant',content=json.dumps(saved)),internal=True)
        return {**saved,'source_turn_id':turn[0]['turn_id'],'replayed':False}


@router.get('/v1/capabilities')
async def capabilities(p=Depends(authenticated)):
    return {'contract_version':'0.1','sdk_version':'0.1.0','discovery':'server','features':['sessions','typed_memory','evidence','trace','task_creation','changes_v1','handoffs','context_pack_sdk','shared_nim_planner'],'single_gateway_required':True,'recall':'bounded graph/task substring filter','deletion_workflow':False,'cross_task_promotion':False}


@router.get('/v1/tasks')
async def tasks(after:str='',limit:int=Query(50,ge=1,le=100),p=Depends(authenticated),r=Depends(repo)):
    rows=await r.db.query(p,'MATCH (t:Task)-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) WHERE t.id>$after AND ($unrestricted OR t.id IN $allowed) RETURN t ORDER BY t.id LIMIT $limit',{'actor':p.agent_id,'after':after,'limit':limit,'unrestricted':p.allowed_task_ids is None,'allowed':list(p.allowed_task_ids or [])})
    items=[x['t'].properties for x in rows]
    return {'items':items,'next_cursor':items[-1]['id'] if len(items)==limit else None}


@router.get('/v1/scopes')
async def scopes(p=Depends(authenticated),r=Depends(repo)):
    page=await tasks('',100,p,r)
    return {'tenant_id':p.tenant_id,'agent_id':p.agent_id,'enforcement':'server tenant graph + enabled task membership','tasks':page['items'],'next_cursor':page['next_cursor'],'private_memory_scopes':False,'deletion_workflow':False}


@router.post('/v1/tasks')
async def create_task(req:TaskRequest,p=Depends(authenticated),r=Depends(repo)):
    require(p.role=='coordinator',403,'FORBIDDEN')
    require(p.allowed_task_ids is None,403,'TASK_SCOPED_PRINCIPAL')
    require(not req.operation_id.startswith('nim_'),400,'RESERVED_OPERATION_ID')
    import re
    ids=sorted(set([p.agent_id,*req.assigned_agent_ids]))
    require(all(re.fullmatch(ID,x) for x in ids),400,'INVALID_INPUT')
    for agent in ids:
        require(await r.db.query(p,'MATCH (a:Agent {id:$id,enabled:true}) RETURN a.id',{'id':agent}))
    task='task_'+stable(p.tenant_id,req.operation_id,'task')[:24]
    require(req.template=='blank' or req.synthetic,400,'SYNTHETIC_TEMPLATE_REQUIRED')
    payload=[p.agent_id,p.tenant_id,req.title,ids,req.synthetic,req.template]
    # Preserve receipts created before project presentation metadata existed.
    if req.description is not None or req.status!='open':
        payload.append({'description':req.description,'status':req.status})
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    old=await r.db.query(p,'MATCH (op:Operation {id:$op}) RETURN op',{'op':req.operation_id})
    if old:
        node=old[0]['op'].properties
        await r.authorize(p,node['task_id'])
        require(node['actor_id']==p.agent_id and node['payload_hash']==digest,409,'IDEMPOTENCY_CONFLICT')
        return commit((json.loads(node['result_json']),False))
    result={'task_id':task,'synthetic':req.synthetic}
    params={'actor':p.agent_id,'ids':ids,'op':req.operation_id,'digest':digest,'task':task,'title':req.title,'description':req.description or '', 'status':req.status,'synthetic':req.synthetic,'now':now(),'result':json.dumps(result)}
    query="MATCH (a:Agent {id:$actor,role:'coordinator',enabled:true}) OPTIONAL MATCH (existing:Operation {id:$op}) WITH a,existing WHERE existing IS NULL CREATE (t:Task {id:$task,title:$title,description:$description,synthetic:$synthetic,status:$status,version:1,event_seq:0,created_at:$now,updated_at:$now}) CREATE (op:Operation {id:$op,kind:'task_create',task_id:$task,actor_id:$actor,payload_hash:$digest,result_json:$result,created_at:$now}) "
    if req.template=='checkout':query+="MERGE (checkout:Entity {id:'checkout'}) ON CREATE SET checkout.name='Checkout',checkout.entity_type='service' MERGE (payments:Entity {id:'payments'}) ON CREATE SET payments.name='Payments',payments.entity_type='service' MERGE (deploy:Entity {id:'deployment-17'}) ON CREATE SET deploy.name='Deployment-17',deploy.entity_type='deployment' CREATE (t)-[:HAS_ENTITY]->(checkout) CREATE (t)-[:HAS_ENTITY]->(payments) CREATE (t)-[:HAS_ENTITY]->(deploy) MERGE (checkout)-[:DEPENDS_ON]->(payments) "
    query+="WITH t UNWIND $ids AS id MATCH (agent:Agent {id:id,enabled:true}) CREATE (t)-[:ASSIGNED_TO]->(agent) RETURN t.id"
    rows=await r.db.query(p,query,params,write=True)
    if not rows:return commit((await r.operation(p,task,req.operation_id,digest),False))
    return commit((result,True))


@router.get('/v1/tasks/{task}/agents')
async def agents(task:str,p=Depends(authenticated),r=Depends(repo)):
    rows=await r.read(p,task,'MATCH (t)-[:ASSIGNED_TO]->(agent:Agent {enabled:true}) OPTIONAL MATCH (t)-[:HAS_SESSION]->(s:Session {agent_id:agent.id}) RETURN agent.id AS id,agent.role AS role,max(s.started_at) AS last_session_at,count(s) AS session_count ORDER BY agent.id LIMIT 50')
    for row in rows:
        sessions=await r.read(p,task,'MATCH (t)-[:HAS_SESSION]->(s:Session {agent_id:$agent}) RETURN s ORDER BY s.started_at DESC LIMIT 5',agent=row['id'])
        row['recent_sessions']=[s['s'].properties for s in sessions]
        row['presence']='historical activity; not a live connection assertion'
    return {'items':rows,'framework_metadata':'self-declared by the session owner; execution verified separately in lab evidence'}


@router.post('/v1/sessions/{sid}/framework')
async def framework(sid:str,req:FrameworkRequest,p=Depends(authenticated),r=Depends(repo)):
    session=await r.session(p,sid,owner=True)
    return commit(await r.commit(p,session['task_id'],'framework:'+sid,req,'MATCH (a)-[:HAS_SESSION]->(s:Session {id:$sid}) ',"SET s.framework=$framework,s.framework_version=$framework_version",result={'session_id':sid,'framework':req.framework,'framework_version':req.framework_version,'verification':'self_declared'},extra={'sid':sid},variables='t,a,s'))


def cursor_encode(p,task,seq):return base64.urlsafe_b64encode(json.dumps(['changes-v1',p.tenant_id,task,seq],separators=(',',':')).encode()).decode()
def cursor_decode(p,task,value):
    if not value:return 0
    try:
        version,tenant,scope,seq=json.loads(base64.urlsafe_b64decode(value.encode()).decode())
        require(version=='changes-v1',410,'CURSOR_EXPIRED')
        require(tenant==p.tenant_id and scope==task and type(seq) is int and seq>=0,400,'INVALID_CURSOR')
        return seq
    except DomainError:raise
    except (ValueError,TypeError,UnicodeError):raise DomainError(400,'INVALID_CURSOR') from None


@router.get('/v1/tasks/{task}/changes')
async def changes(task:str,cursor:str=Query('',max_length=1024),limit:int=Query(50,ge=1,le=100),p=Depends(authenticated),r=Depends(repo)):
    tasknode=await r.authorize(p,task);after=cursor_decode(p,task,cursor)
    require(after<=tasknode.get('event_seq',0),409,'CURSOR_AHEAD')
    rows=await r.read(p,task,'MATCH (e:MemoryEvent {task_id:$task}) WHERE e.seq>$after RETURN e ORDER BY e.seq LIMIT $limit',after=after,limit=limit)
    items=[x['e'].properties for x in rows]
    return {'items':items,'next_cursor':cursor_encode(p,task,items[-1]['seq'] if items else after),'ordering':'atomic task event sequence','retention':'no automated deletion; valid v1 cursors do not expire','legacy_events':'pre-0.1 unsequenced events remain in history/trace but are outside this feed','delivery':'poll/ack at least once; independent of router'}


@router.get('/v1/trace')
async def trace(reference:str=Query(max_length=400),p=Depends(authenticated),r=Depends(repo)):
    task,mid=parse_memory_reference(reference)
    memory=await r.memory(p,task,mid)
    rows=await r.read(p,task,'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$mid})-[:DERIVED_FROM]->(u:Turn)<-[:HAS_TURN]-(s:Session) RETURN u,s',mid=mid)
    events=await r.read(p,task,'MATCH (e:MemoryEvent {task_id:$task,target_id:$mid}) RETURN e ORDER BY e.created_at,e.id LIMIT 100',mid=mid)
    supersedes=await r.read(p,task,'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$mid})-[:SUPERSEDES]->(old:Memory)<-[:HAS_MEMORY]-(t) RETURN old.id AS id LIMIT 20',mid=mid)
    replacements=await r.read(p,task,'MATCH (t)-[:HAS_MEMORY]->(new:Memory)-[:SUPERSEDES]->(m:Memory {id:$mid})<-[:HAS_MEMORY]-(t) RETURN new.id AS id LIMIT 20',mid=mid)
    handoffs=await r.read(p,task,'MATCH (t)-[:HAS_HANDOFF]->(h:Handoff)-[:REFERS_TO]->(m:Memory {id:$mid}) RETURN h ORDER BY h.created_at DESC LIMIT 20',mid=mid)
    return {'memory':memory,'source_turn':rows[0]['u'].properties if rows else None,'session':rows[0]['s'].properties if rows else None,'events':[x['e'].properties for x in events],'supersedes':[x['id'] for x in supersedes],'replacements':[x['id'] for x in replacements],'related_handoffs':[x['h'].properties for x in handoffs],'bounded':True,'event_limit':100}


@router.post('/v1/tasks/{task}/memories/{mid}/support')
async def support(task:str,mid:str,req:ChallengeRequest,p=Depends(authenticated),r=Depends(repo)):
    require(p.role in ('verifier','coordinator'),403,'FORBIDDEN')
    await r.authorize(p,task)
    replay=await r.replay(p,task,'support:'+mid,req)
    if replay:return commit(replay)
    m=await r.memory(p,task,mid)
    require(m['assertion_type']=='hypothesis' and m['status'] in ('active','proposed','disputed'),409,'INVALID_TRANSITION')
    require(m['version']==req.expected_version,409,'VERSION_CONFLICT')
    require(await r.read(p,task,'MATCH (t)-[:HAS_EVIDENCE]->(e:Evidence {id:$id}) RETURN e.id',id=req.evidence_id))
    eid=r.ids(p,req.operation_id,'evt')
    body='SET m.version=$new_version,m.updated_at=$now MERGE (m)-[:SUPPORTED_BY]->(e) '
    body+=r.event('MEMORY_SUPPORTED','memory','m','RECORDS','old_status:$old_status,new_status:$old_status,old_version:$expected_version,new_version:$new_version,reason:$reason,evidence_id:$evidence_id,')
    return commit(await r.commit(p,task,'support:'+mid,req,'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$id}) MATCH (t)-[:HAS_EVIDENCE]->(e:Evidence {id:$evidence_id}) ',body,result={'memory_id':mid,'event_id':eid,'status':m['status'],'version':m['version']+1},extra={'id':mid,'eid':eid,'old_status':m['status'],'new_version':m['version']+1},variables='t,a,m,e',condition='m.version=$expected_version'))
