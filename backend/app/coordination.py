"""Task-scoped leases and auditable adapter activity. No MCP/DB shortcut."""
import time
from fastapi import APIRouter,Depends,Query
from pydantic import Field
from typing import Literal
from .auth import authenticated
from .errors import DomainError,require
from .models import Intent,ID
from .platform import repo,commit
from .repository import stable

router=APIRouter()

@router.get('/v1/tasks/{task}/mcp-preflight')
async def connection_preflight(task:str,client:Literal['codex','claude','antigravity']='antigravity',p=Depends(authenticated),r=Depends(repo)):
    await r.authorize(p,task)
    rows=await r.read(p,task,'MATCH (t)-[:ASSIGNED_TO]->(agent:Agent {enabled:true}) RETURN agent.id AS id,agent.role AS role ORDER BY agent.id LIMIT 50')
    return {'status':'PASS','layer':'authenticated gateway/task access; not stdio or application verification','selected_configuration':client,'task_id':task,'identity':{'tenant_id':p.tenant_id,'agent_id':p.agent_id,'role':p.role},'schema_ready':r.db.ready,'transport':'local stdio via independently launched Loomline MCP process','assigned_identities':rows,'procedure_approval_allowed':p.role=='coordinator' and p.can_approve_procedures,'next_step':'Run loomline_mcp.preflight --config with the configured Python; owner then verifies actual client tools.','client_verification':{'codex':'PENDING_OWNER_VERIFICATION','claude':'PENDING_OWNER_VERIFICATION','antigravity_ide':'PENDING_OWNER_VERIFICATION','antigravity_cli':'PENDING_OWNER_VERIFICATION','three_client_exchange':'PENDING_OWNER_VERIFICATION'}}

class ClaimRequest(Intent):
    lease_seconds:int=Field(default=300,ge=1,le=3600)
    expected_version:int|None=Field(default=None,ge=0)

class ReleaseRequest(Intent):
    expected_version:int=Field(ge=1)

@router.get('/v1/tasks/{task}/claims')
async def claims(task:str,after:str='',limit:int=Query(50,ge=1,le=100),p=Depends(authenticated),r=Depends(repo)):
    rows=await r.read(p,task,'MATCH (t)-[:HAS_CLAIM]->(w:WorkClaim) WHERE w.key>$after RETURN w ORDER BY w.key LIMIT $limit',after=after,limit=limit)
    clock=time.time_ns()//1_000_000;items=[{**x['w'].properties,'active':x['w'].properties['state']=='claimed' and x['w'].properties['lease_until_ms']>clock} for x in rows]
    return {'items':items,'next_cursor':items[-1]['key'] if len(items)==limit else None,'server_time_ms':clock,'ownership':'exclusive until server-clock lease expiry; versions fence stale owners'}

@router.post('/v1/tasks/{task}/claims/{work_key}')
async def claim(task:str,work_key:str,req:ClaimRequest,p=Depends(authenticated),r=Depends(repo)):
    import re
    require(re.fullmatch(ID,work_key),400,'INVALID_WORK_KEY')
    kind='work_claim:'+work_key
    old=await r.replay(p,task,kind,req)
    if old:return commit(old)
    wid='claim_'+stable(p.tenant_id,task,work_key)
    rows=await r.read(p,task,'MATCH (t)-[:HAS_CLAIM]->(w:WorkClaim {id:$id}) RETURN w',id=wid)
    current=rows[0]['w'].properties if rows else {'version':0,'state':'released','lease_until_ms':0}
    clock=time.time_ns()//1_000_000
    require(req.expected_version is None or req.expected_version==current['version'],409,'VERSION_CONFLICT')
    require(current['state']=='released' or current['lease_until_ms']<=clock or current.get('owner_agent_id')==p.agent_id,409,'WORK_CLAIM_CONFLICT')
    version=current['version']+1;until=clock+req.lease_seconds*1000;eid=r.ids(p,req.operation_id,'evt')
    matches='OPTIONAL MATCH (w:WorkClaim {id:$id}) '
    variable='w' if rows else 'created'
    condition="w.task_id=$task AND w.version=$prior AND (w.state='released' OR w.lease_until_ms<=$clock OR w.owner_agent_id=$actor)" if rows else 'w IS NULL'
    body='' if rows else 'CREATE (created:WorkClaim {id:$id,task_id:$task,key:$work}) '
    body+=f"SET {variable}.owner_agent_id=$actor,{variable}.state='claimed',{variable}.version=$version,{variable}.lease_until_ms=$until,{variable}.updated_at=$now MERGE (t)-[:HAS_CLAIM]->({variable}) "
    body+=r.event('WORK_CLAIMED','work_claim',variable,'RECORDS','owner_agent_id:$actor,new_version:$version,lease_until_ms:$until,')
    try:
        return commit(await r.commit(p,task,kind,req,matches,body,result={'claim_id':wid,'work_key':work_key,'owner_agent_id':p.agent_id,'state':'claimed','version':version,'lease_until_ms':until,'event_id':eid},extra={'id':wid,'work':work_key,'prior':current['version'],'version':version,'until':until,'clock':clock,'eid':eid},variables='t,a,w',condition=condition))
    except DomainError as exc:
        if exc.status==409 and exc.code=='VERSION_CONFLICT':raise DomainError(409,'WORK_CLAIM_CONFLICT') from None
        raise

@router.get('/v1/tasks/{task}/claims/{work_key}')
async def get_claim(task:str,work_key:str,p=Depends(authenticated),r=Depends(repo)):
    wid='claim_'+stable(p.tenant_id,task,work_key)
    rows=await r.read(p,task,'MATCH (t)-[:HAS_CLAIM]->(w:WorkClaim {id:$id}) RETURN w',id=wid);require(rows)
    w=rows[0]['w'].properties;clock=time.time_ns()//1_000_000
    return {**w,'active':w['state']=='claimed' and w['lease_until_ms']>clock,'server_time_ms':clock}

@router.post('/v1/tasks/{task}/claims/{work_key}/release')
async def release(task:str,work_key:str,req:ReleaseRequest,p=Depends(authenticated),r=Depends(repo)):
    wid='claim_'+stable(p.tenant_id,task,work_key);eid=r.ids(p,req.operation_id,'evt')
    replay=await r.replay(p,task,'work_release:'+work_key,req)
    if replay:return commit(replay)
    rows=await r.read(p,task,'MATCH (t)-[:HAS_CLAIM]->(w:WorkClaim {id:$id}) RETURN w',id=wid);require(rows)
    w=rows[0]['w'].properties
    require(w.get('owner_agent_id')==p.agent_id,403,'NOT_CLAIM_OWNER')
    body="SET w.state='released',w.version=$version,w.lease_until_ms=0,w.updated_at=$now "+r.event('WORK_RELEASED','work_claim','w','RECORDS','owner_agent_id:$actor,new_version:$version,')
    return commit(await r.commit(p,task,'work_release:'+work_key,req,'MATCH (t)-[:HAS_CLAIM]->(w:WorkClaim {id:$id}) ',body,result={'claim_id':wid,'work_key':work_key,'state':'released','version':req.expected_version+1,'event_id':eid},extra={'id':wid,'version':req.expected_version+1,'eid':eid},variables='t,a,w',condition="w.owner_agent_id=$actor AND w.version=$expected_version AND w.state='claimed'"))

class ActivityRequest(Intent):
    session_id:str=Field(pattern=ID)
    tool_name:str=Field(pattern=r'^loomline_[a-z_]{1,64}$')
    outcome:str=Field(pattern=r'^(success|error)$')
    error_code:str=Field(default='NONE',pattern=r'^[A-Z][A-Z0-9_]{0,79}$')
    duration_ms:int=Field(ge=0,le=3600000)

@router.post('/v1/tasks/{task}/mcp-activity')
async def activity(task:str,req:ActivityRequest,p=Depends(authenticated),r=Depends(repo)):
    session=await r.session(p,req.session_id,owner=True);require(session['task_id']==task)
    cid=r.ids(p,req.operation_id,'call')
    return commit(await r.commit(p,task,'mcp_activity',req,'MATCH (a)-[:HAS_SESSION]->(s:Session {id:$session_id}) ',"SET t.mcp_seq=coalesce(t.mcp_seq,0)+1 CREATE (c:MCPCall {id:$id,seq:t.mcp_seq,task_id:$task,session_id:$session_id,agent_id:$actor,tool_name:$tool_name,outcome:$outcome,error_code:$error_code,duration_ms:$duration_ms,created_at:$now,transport:'stdio',attestation:'authenticated adapter report; client software unverified'}) CREATE (t)-[:HAS_MCP_CALL]->(c) CREATE (c)-[:IN_SESSION]->(s)",result={'call_id':cid},extra={'id':cid},variables='t,a,s'))

@router.get('/v1/tasks/{task}/mcp-activity')
async def activity_list(task:str,after:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),p=Depends(authenticated),r=Depends(repo)):
    rows=await r.read(p,task,'MATCH (t)-[:HAS_MCP_CALL]->(c:MCPCall) WHERE c.seq>$after RETURN c ORDER BY c.seq LIMIT $limit',after=after,limit=limit)
    items=[x['c'].properties for x in rows]
    return {'items':items,'next_cursor':items[-1]['seq'] if items else after,'client_verification':{'codex_tool_invocation':'PENDING_OWNER_VERIFICATION','claude_tool_invocation':'PENDING_OWNER_VERIFICATION','antigravity_ide_tool_invocation':'PENDING_OWNER_VERIFICATION','antigravity_cli_tool_invocation':'PENDING_OWNER_VERIFICATION','real_two_cli_exchange':'PENDING_OWNER_VERIFICATION','real_three_client_exchange':'PENDING_OWNER_VERIFICATION'}}
