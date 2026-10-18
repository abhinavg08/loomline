"""All request data reaches storage through a trusted TenantContext.

Each commit uses one modifying query. The optional Operation match and all
preconditions precede CREATE; losing concurrent retries recover by lookup.
"""
import hashlib
import json
import base64
from datetime import datetime, timezone
from .errors import DomainError, require

AUTH = 'MATCH (t:Task {id:$task})-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) '


def now():
    return datetime.now(timezone.utc).isoformat()


def stable(*parts):
    return hashlib.sha256(':'.join(parts).encode()).hexdigest()[:40]


class Repository:
    def __init__(self, db):
        self.db = db

    def params(self, p, task, **values):
        return dict(task=task, actor=p.agent_id, **values)

    async def read(self, p, task, tail, **values):
        await self.authorize(p, task)
        return await self.db.query(p, AUTH + tail, self.params(p, task, **values))

    async def authorize(self, p, task):
        require(p.allowed_task_ids is None or task in p.allowed_task_ids)
        rows = await self.db.query(p, AUTH + 'RETURN t', self.params(p, task))
        require(rows)
        return rows[0]['t'].properties

    async def operation(self, p, task, op_id, digest=None):
        rows = await self.read(p, task, 'MATCH (op:Operation {id:$op_id}) RETURN op', op_id=op_id)
        if not rows:
            return None
        op = rows[0]['op'].properties
        # No operation details are disclosed across actors/tasks.
        if op['task_id']!=task:
            await self.authorize(p,op['task_id'])
            raise DomainError(409,'IDEMPOTENCY_CONFLICT')
        require(op['actor_id'] == p.agent_id,404 if digest is None else 409,'NOT_FOUND' if digest is None else 'IDEMPOTENCY_CONFLICT')
        require(digest is None or op['payload_hash']==digest,409,'IDEMPOTENCY_CONFLICT')
        result = json.loads(op['result_json'])
        if 'result_seq' in op:
            result['seq'] = op['result_seq']
        return result

    async def commit(self, p, task, kind, request, matches, body, *, result, extra=None, condition='true', variables='t,a'):
        await self.authorize(p, task)
        require(not request.operation_id.startswith('nim_') or kind.startswith('nim_turn:'),400,'RESERVED_OPERATION_ID')
        payload = request.model_dump(mode='json', by_alias=True)
        op_id = payload.pop('operation_id')
        digest = hashlib.sha256(json.dumps([kind, p.tenant_id, p.agent_id, task, payload], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        replay = await self.operation(p, task, op_id, digest)
        if replay is not None:
            return replay, False
        params = self.params(p, task, **payload)
        params.update(extra or {})
        result_id=next((result[k] for k in ('memory_id','session_id','turn_id','evidence_id','handoff_id','subscription_id','inbox_id','claim_id','call_id') if k in result),'')
        params.update(op_id=op_id, digest=digest, kind=kind, now=now(), result_json=json.dumps(result),result_id=result_id)
        query = AUTH + matches + f' WITH {variables} WHERE {condition} '
        query += f'OPTIONAL MATCH (existing:Operation {{id:$op_id}}) WITH {variables},existing WHERE existing IS NULL '
        query += 'CREATE (op:Operation {id:$op_id,kind:$kind,payload_hash:$digest,actor_id:$actor,task_id:$task,result_id:$result_id,result_json:$result_json,created_at:$now}) '
        query += body + ' RETURN op'
        rows = await self.db.query(p, query, params, write=True)
        if rows:
            op = rows[0]['op'].properties
            original = json.loads(op['result_json'])
            if 'result_seq' in op:
                original['seq'] = op['result_seq']
            return original, True
        replay = await self.operation(p, task, op_id, digest)
        if replay is not None:
            return replay, False
        raise DomainError(409, 'VERSION_CONFLICT' if 'expected_version' in payload else 'INVALID_INPUT')

    async def replay(self, p, task, kind, req):
        payload=req.model_dump(mode='json',by_alias=True)
        op_id=payload.pop('operation_id')
        digest=hashlib.sha256(json.dumps([kind,p.tenant_id,p.agent_id,task,payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result=await self.operation(p,task,op_id,digest)
        return (result,False) if result is not None else None

    def ids(self, p, operation_id, prefix):
        return prefix + '_' + stable(p.tenant_id, operation_id, prefix)

    async def create_session(self, p, task, req):
        sid = self.ids(p, req.operation_id, 'sess')
        return await self.commit(p, task, 'session', req, '',
            "CREATE (s:Session {id:$id,task_id:$task,agent_id:$actor,status:'open',next_seq:1,started_at:$now}) CREATE (a)-[:HAS_SESSION]->(s) CREATE (t)-[:HAS_SESSION]->(s)",
            result={'session_id': sid}, extra={'id': sid})

    async def create_demo_run(self,p,req):
        """A new authorized task is the reset boundary; prior runs are never cleared."""
        require(p.role=='coordinator',403,'FORBIDDEN')
        require(p.allowed_task_ids is None,403,'TASK_SCOPED_PRINCIPAL')
        require(not req.operation_id.startswith('nim_'),400,'RESERVED_OPERATION_ID')
        task='incident_'+stable(p.tenant_id,req.operation_id,'run')[:16]
        digest=hashlib.sha256(json.dumps(['demo_run',p.tenant_id,p.agent_id,task],separators=(',',':')).encode()).hexdigest()
        existing=await self.db.query(p,'MATCH (a:Agent {id:$actor,enabled:true}) MATCH (op:Operation {id:$op}) RETURN op',{'actor':p.agent_id,'op':req.operation_id})
        if existing:
            op=existing[0]['op'].properties
            await self.authorize(p,op['task_id'])
            require(op['actor_id']==p.agent_id and op['payload_hash']==digest,409,'IDEMPOTENCY_CONFLICT')
            return json.loads(op['result_json']),False
        prefix='' if p.tenant_id=='alpha' else 'beta_'
        result={'task_id':task,'synthetic':True}
        params={'actor':p.agent_id,'i':prefix+'investigator','v':prefix+'verifier','c':prefix+'coordinator','task':task,'op':req.operation_id,'digest':digest,'now':now(),'result':json.dumps(result)}
        query="MATCH (a:Agent {id:$actor,role:'coordinator',enabled:true}),(i:Agent {id:$i,enabled:true}),(v:Agent {id:$v,enabled:true}),(c:Agent {id:$c,enabled:true}) OPTIONAL MATCH (existing:Operation {id:$op}) WITH a,i,v,c,existing WHERE existing IS NULL "
        query+="CREATE (op:Operation {id:$op,kind:'demo_run',payload_hash:$digest,actor_id:$actor,task_id:$task,result_id:$task,result_json:$result,created_at:$now}) CREATE (t:Task {id:$task,title:'Synthetic Checkout investigation',demo_run:true,status:'investigating',version:1,created_at:$now,updated_at:$now}) CREATE (t)-[:ASSIGNED_TO]->(i) CREATE (t)-[:ASSIGNED_TO]->(v) CREATE (t)-[:ASSIGNED_TO]->(c) "
        query+="MERGE (checkout:Entity {id:'checkout'}) ON CREATE SET checkout.name='Checkout',checkout.entity_type='service' MERGE (payments:Entity {id:'payments'}) ON CREATE SET payments.name='Payments',payments.entity_type='service' MERGE (deploy:Entity {id:'deployment-17'}) ON CREATE SET deploy.name='Deployment-17',deploy.entity_type='deployment' CREATE (t)-[:HAS_ENTITY]->(checkout) CREATE (t)-[:HAS_ENTITY]->(payments) CREATE (t)-[:HAS_ENTITY]->(deploy) MERGE (checkout)-[:DEPENDS_ON]->(payments) RETURN op"
        rows=await self.db.query(p,query,params,write=True)
        if rows:return result,True
        replay=await self.operation(p,task,req.operation_id,digest)
        require(replay is not None,404,'NOT_FOUND')
        return replay,False

    async def session(self, p, sid, *, owner=False):
        rows = await self.db.query(p, "MATCH (t:Task)-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) MATCH (t)-[:HAS_SESSION]->(s:Session {id:$sid}) RETURN s", {'actor': p.agent_id, 'sid': sid})
        require(rows)
        s = rows[0]['s'].properties
        require(p.allowed_task_ids is None or s['task_id'] in p.allowed_task_ids)
        if owner:
            require(s['agent_id'] == p.agent_id)
        return s

    async def append_turn(self, p, sid, req,*,internal=False):
        s = await self.session(p, sid, owner=True)
        tid = self.ids(p, req.operation_id, 'turn')
        return await self.commit(p, s['task_id'], ('nim_turn:' if internal else 'turn:')+sid, req,
            'MATCH (a)-[:HAS_SESSION]->(s:Session {id:$sid}) MATCH (t)-[:HAS_SESSION]->(s) ',
            "SET op.result_seq=s.next_seq, s.next_seq=s.next_seq+1 CREATE (u:Turn {id:$id,session_id:$sid,seq:op.result_seq,role:$role,content:$content,tool_name:$tool_name,tool_call_id:$tool_call_id,content_hash:$content_hash,created_at:$now,operation_id:$op_id}) CREATE (s)-[:HAS_TURN]->(u)",
            result={'turn_id': tid}, extra={'sid': sid, 'id': tid, 'content_hash': hashlib.sha256(req.content.encode()).hexdigest()},
            variables='t,a,s', condition="s.status='open'")

    async def turns(self, p, sid, after=0, limit=100):
        s = await self.session(p, sid)
        rows = await self.read(p, s['task_id'], 'MATCH (t)-[:HAS_SESSION]->(s:Session {id:$sid})-[:HAS_TURN]->(u:Turn) WHERE u.seq>$after RETURN u ORDER BY u.seq LIMIT $limit', sid=sid, after=after, limit=limit)
        items = [r['u'].properties for r in rows]
        return {'items': items, 'next_cursor': items[-1]['seq'] if len(items) == limit else None}

    async def sessions(self, p, task, after='', limit=100):
        rows = await self.read(p, task, 'MATCH (t)-[:HAS_SESSION]->(s:Session) WHERE s.id>$after RETURN s ORDER BY s.id LIMIT $limit', after=after, limit=limit)
        return [r['s'].properties for r in rows]

    async def history(self,p,task,before='',limit=20):
        cutoff,session,seq='9999','',0
        if before:
            try:
                cutoff,session,seq=json.loads(base64.urlsafe_b64decode(before.encode()).decode())
                require(isinstance(cutoff,str) and isinstance(session,str) and isinstance(seq,int),400,'INVALID_INPUT')
            except (ValueError,TypeError,UnicodeError):
                raise DomainError(400,'INVALID_INPUT') from None
        rows=await self.read(p,task,'MATCH (t)-[:HAS_SESSION]->(s:Session)-[:HAS_TURN]->(u:Turn) WHERE u.created_at<$cutoff OR (u.created_at=$cutoff AND (s.id<$session OR (s.id=$session AND u.seq<$seq))) RETURN u ORDER BY u.created_at DESC,s.id DESC,u.seq DESC LIMIT $limit',cutoff=cutoff,session=session,seq=seq,limit=limit)
        items=[r['u'].properties for r in rows]
        last=items[-1] if items else None
        cursor=base64.urlsafe_b64encode(json.dumps([last['created_at'],last['session_id'],last['seq']]).encode()).decode() if len(items)==limit else None
        return {'items':items,'next_cursor':cursor}

    async def create_memory(self, p, task, req):
        await self.authorize(p, task)
        permitted = {'investigator': {'episode','observation','hypothesis'}, 'verifier': {'episode','observation','hypothesis'}, 'coordinator': {'episode','observation','hypothesis','procedure','decision'}}
        require(req.assertion_type in permitted.get(p.role, set()), 403, 'FORBIDDEN')
        source = await self.read(p, task, 'MATCH (a)-[:HAS_SESSION]->(s:Session {id:$sid}) MATCH (t)-[:HAS_SESSION]->(s)-[:HAS_TURN]->(u:Turn {id:$src}) RETURN u', sid=req.session_id, src=req.source_turn_id)
        require(source)
        mid, eid = (self.ids(p, req.operation_id, x) for x in ('mem', 'evt'))
        matches = 'MATCH (a)-[:HAS_SESSION]->(s:Session {id:$session_id}) MATCH (t)-[:HAS_SESSION]->(s)-[:HAS_TURN]->(src:Turn {id:$source_turn_id}) '
        variables = ['t','a','src']
        links = ''
        extra = {'id': mid,'eid': eid,'steps_json': json.dumps(req.steps) if req.steps else None,'memory_class': req.memory_class}
        for label, ids, edge, taskedge in [('Entity',req.entity_ids,'ABOUT','HAS_ENTITY'),('Evidence',req.evidence_ids,'SUPPORTED_BY','HAS_EVIDENCE')]:
            for i, ref in enumerate(ids):
                v = label.lower() + str(i)
                # Validate every reference before any modifying query.
                require(await self.read(p, task, f'MATCH (t)-[:{taskedge}]->(x:{label} {{id:$ref}}) RETURN x.id', ref=ref))
                matches += f'MATCH (t)-[:{taskedge}]->({v}:{label} {{id:${v}}}) '
                variables.append(v)
                extra[v] = ref
                links += f' CREATE (m)-[:{edge}]->({v}) '
        if req.supersedes_id:
            require(await self.read(p, task, 'MATCH (t)-[:HAS_MEMORY]->(old:Memory {id:$ref}) RETURN old.id', ref=req.supersedes_id))
            matches += 'MATCH (t)-[:HAS_MEMORY]->(old:Memory {id:$supersedes_id}) '
            variables.append('old')
            links += ' CREATE (m)-[:SUPERSEDES]->(old) '
        body = "CREATE (m:Memory {id:$id,class:$memory_class,assertion_type:$assertion_type,status:$status,content:$content,steps_json:$steps_json,task_id:$task,created_by:$actor,source_turn_id:$source_turn_id,version:1,created_at:$now,updated_at:$now,operation_id:$op_id}) CREATE (t)-[:HAS_MEMORY]->(m) CREATE (a)-[:CREATED]->(m) CREATE (m)-[:DERIVED_FROM]->(src) " + links
        body += self.event('MEMORY_CREATED', 'memory', 'm', 'RECORDS', "new_status:$status,new_version:1,")
        return await self.commit(p, task, 'memory', req, matches, body, extra=extra, variables=','.join(variables),
            result={'memory_id':mid,'reference':f'loom://task/{task}/memory/{mid}','event_id':eid,'version':1,'committed':True,'notification_delivery_guaranteed':False})

    @staticmethod
    def event(kind, target, variable, edge, fields=''):
        return f" SET t.event_seq=coalesce(t.event_seq,0)+1 CREATE (ev:MemoryEvent {{id:$eid,seq:t.event_seq,operation_id:$op_id,task_id:$task,type:'{kind}',actor_id:$actor,target_kind:'{target}',target_id:{variable}.id,{fields}created_at:$now,dispatch_status:'pending'}}) CREATE (ev)-[:{edge}]->({variable}) "

    async def memory(self, p, task, mid):
        rows = await self.read(p, task, 'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$id}) RETURN m', id=mid)
        require(rows)
        m = rows[0]['m'].properties
        for edge,key,label in [('SUPPORTED_BY','support','Evidence'),('CHALLENGED_BY','challenges','Evidence'),('ABOUT','entities','Entity')]:
            links = await self.read(p, task, f'MATCH (t)-[:HAS_MEMORY]->(m:Memory {{id:$id}})-[:{edge}]->(x:{label}) RETURN x LIMIT 100', id=mid)
            m[key] = [r['x'].properties for r in links]
        m['steps'] = json.loads(m.get('steps_json') or 'null')
        m['reference'] = f'loom://task/{task}/memory/{mid}'
        return m

    async def evidence(self,p,task,req):
        eid=self.ids(p,req.operation_id,'evidence')
        return await self.commit(p,task,'evidence',req,'',
            'CREATE (e:Evidence {id:$id,task_id:$task,source_type:$source_type,source_ref:$source_ref,content:$content,observed_at:$observed_at,created_at:$now}) CREATE (t)-[:HAS_EVIDENCE]->(e)',
            result={'evidence_id':eid},extra={'id':eid})

    async def challenge(self,p,task,mid,req):
        await self.authorize(p,task)
        require(p.role in ('verifier','coordinator'),403,'FORBIDDEN')
        replay=await self.replay(p,task,'challenge:'+mid,req)
        if replay: return replay
        m=await self.memory(p,task,mid)
        require(await self.read(p,task,'MATCH (t)-[:HAS_EVIDENCE]->(e:Evidence {id:$ref}) RETURN e.id',ref=req.evidence_id))
        require(m['version']==req.expected_version,409,'VERSION_CONFLICT')
        require(m['assertion_type']=='hypothesis' and m['status'] in ('proposed','active','disputed'),409,'INVALID_TRANSITION')
        eid=self.ids(p,req.operation_id,'evt')
        body="SET m.status='disputed',m.version=$new_version,m.updated_at=$now MERGE (m)-[:CHALLENGED_BY]->(e) "
        body+=self.event('MEMORY_CHALLENGED','memory','m','RECORDS',"old_status:$old_status,new_status:'disputed',old_version:$expected_version,new_version:$new_version,reason:$reason,evidence_id:$evidence_id,")
        return await self.commit(p,task,'challenge:'+mid,req,
            'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$id}) MATCH (t)-[:HAS_EVIDENCE]->(e:Evidence {id:$evidence_id}) ',body,
            result={'memory_id':mid,'challenge_id':eid,'event_id':eid,'status':'disputed','version':m['version']+1},
            extra={'id':mid,'eid':eid,'old_status':m['status'],'new_version':m['version']+1},variables='t,a,m,e',condition='m.version=$expected_version AND m.status=$old_status')

    async def memory_status(self,p,task,mid,req):
        await self.authorize(p,task)
        require(p.role=='coordinator',403,'FORBIDDEN')
        replay=await self.replay(p,task,'memory_status:'+mid,req)
        if replay: return replay
        m=await self.memory(p,task,mid)
        require(m['version']==req.expected_version,409,'VERSION_CONFLICT')
        if m['class']=='procedural':
            require(req.status!='active' or p.can_approve_procedures,403,'PROCEDURE_APPROVAL_DISABLED')
            allowed=(m['status'],req.status) in (('proposed','active'),('proposed','retired'),('active','retired'))
        else:
            allowed=req.status=='superseded' and m['status'] in ('active','proposed','disputed')
            if allowed:
                require(await self.read(p,task,'MATCH (t)-[:HAS_MEMORY]->(replacement:Memory)-[:SUPERSEDES]->(m:Memory {id:$ref}) RETURN replacement.id',ref=mid),409,'INVALID_TRANSITION')
        require(allowed,409,'INVALID_TRANSITION')
        eid=self.ids(p,req.operation_id,'evt')
        body='SET m.status=$status,m.version=$new_version,m.updated_at=$now '
        body+=self.event('MEMORY_STATUS_CHANGED','memory','m','RECORDS','old_status:$old_status,new_status:$status,old_version:$expected_version,new_version:$new_version,reason:$reason,')
        return await self.commit(p,task,'memory_status:'+mid,req,'MATCH (t)-[:HAS_MEMORY]->(m:Memory {id:$id}) ',body,
            result={'memory_id':mid,'event_id':eid,'status':req.status,'version':m['version']+1},
            extra={'id':mid,'eid':eid,'old_status':m['status'],'new_version':m['version']+1},variables='t,a,m',condition='m.version=$expected_version AND m.status=$old_status')

    async def context(self,p,task,limit=10,query=None,entity_id=None):
        tasknode=await self.authorize(p,task)
        result={'task':tasknode,'fetched_at':now(),'episodic':[],'semantic':[],'procedural':[],'proposed_procedures':[]}
        for cls in ('episodic','semantic','procedural'):
            entity_match='MATCH (m)-[:ABOUT]->(:Entity {id:$entity}) ' if entity_id and cls!='procedural' else ''
            status_filter=" AND m.status IN ['active','proposed'] " if cls=='procedural' else ''
            rows=await self.read(p,task,'MATCH (t)-[:HAS_MEMORY]->(m:Memory {class:$cls}) '+entity_match+'WHERE ($query IS NULL OR toLower(m.content) CONTAINS toLower($query)) '+status_filter+'RETURN m.id AS id ORDER BY m.created_at DESC LIMIT $limit',cls=cls,query=query,limit=limit,entity=entity_id)
            for row in rows:
                m=await self.memory(p,task,row['id'])
                # Bound graph expansion independently of total event history.
                for field in ('support','challenges','entities'): m[field]=m[field][:10]
                if cls=='procedural':
                    if m['status']=='active': result['procedural'].append(m)
                    elif m['status']=='proposed': result['proposed_procedures'].append(m)
                else: result[cls].append(m)
        turns=await self.history(p,task)
        result['recent_turns']=list(reversed(turns['items']))
        result['next_turn_cursor']=turns['next_cursor']
        hs=await self.read(p,task,'MATCH (t)-[:HAS_HANDOFF]->(h:Handoff) RETURN h ORDER BY h.created_at DESC LIMIT 10')
        result['handoffs']=[r['h'].properties for r in hs]
        result['open_handoffs']=[h for h in result['handoffs'] if h['status'] in ('open','accepted')]
        events=await self.read(p,task,'MATCH (e:MemoryEvent {task_id:$task}) RETURN e ORDER BY e.created_at DESC LIMIT 50')
        result['timeline']=[r['e'].properties for r in events]
        result['provenance_paths']=[{'memory_id':m['id'],'support_ids':[e['id'] for e in m['support']],'challenge_ids':[e['id'] for e in m['challenges']]} for cls in ('episodic','semantic','procedural','proposed_procedures') for m in result[cls]]
        return result

    async def decision_context(self,p,task,entity='checkout'):
        # Both dependency and provenance edges must actually exist to yield rows.
        rows=await self.read(p,task,
            'MATCH (t)-[:HAS_ENTITY]->(service:Entity {id:$entity})-[:DEPENDS_ON]->(upstream:Entity) '
            'MATCH (t)-[:HAS_ENTITY]->(upstream) MATCH (t)-[:HAS_MEMORY]->(m:Memory)-[:ABOUT]->(subject:Entity) '
            'WHERE subject=service OR subject=upstream '
            'MATCH (m)-[r:SUPPORTED_BY|CHALLENGED_BY]->(e:Evidence) MATCH (t)-[:HAS_EVIDENCE]->(e) '
            'RETURN service.id AS service_id,service.name AS service,upstream.id AS upstream_id,upstream.name AS upstream,subject.id AS subject_id,m.id AS memory_id,m.status AS status,m.content AS claim,e.id AS evidence_id,e.content AS evidence,e.observed_at AS observed_at,type(r) AS relationship ORDER BY m.created_at DESC,e.observed_at LIMIT 20',entity=entity)
        return {'task_id':task,'fetched_at':now(),'paths':rows,'query_semantics':'Task membership + DEPENDS_ON + ABOUT + SUPPORTED_BY/CHALLENGED_BY; per-query snapshot'}

    async def create_handoff(self,p,task,req):
        await self.authorize(p,task)
        require(p.role=='coordinator',403,'FORBIDDEN')
        require(await self.read(p,task,'MATCH (t)-[:ASSIGNED_TO]->(recipient:Agent {id:$ref,enabled:true}) RETURN recipient.id',ref=req.to_agent_id))
        hid,eid=(self.ids(p,req.operation_id,x) for x in ('handoff','evt'))
        matches='MATCH (t)-[:ASSIGNED_TO]->(recipient:Agent {id:$to_agent_id,enabled:true}) '
        variables=['t','a','recipient']; links='';extra={'id':hid,'eid':eid}
        require(len(set(req.related_memory_ids))==len(req.related_memory_ids),400,'INVALID_INPUT')
        for i,mid in enumerate(req.related_memory_ids):
            await self.memory(p,task,mid)
            var='m'+str(i);extra[var]=mid;variables.append(var)
            matches+=f'MATCH (t)-[:HAS_MEMORY]->({var}:Memory {{id:${var}}}) '
            links+=f'CREATE (h)-[:REFERS_TO]->({var}) '
        body="CREATE (h:Handoff {id:$id,task_id:$task,from_agent_id:$actor,to_agent_id:$to_agent_id,description:$description,status:'open',version:1,operation_id:$op_id,created_at:$now,updated_at:$now}) CREATE (t)-[:HAS_HANDOFF]->(h) CREATE (h)-[:ASSIGNED_TO]->(recipient) "+links
        body+=self.event('HANDOFF_CREATED','handoff','h','ANNOUNCES_HANDOFF',"new_status:'open',new_version:1,")
        return await self.commit(p,task,'handoff',req,matches,body,result={'handoff_id':hid,'event_id':eid,'version':1,'status':'open'},extra=extra,variables=','.join(variables))

    async def handoff(self,p,task,hid):
        rows=await self.read(p,task,'MATCH (t)-[:HAS_HANDOFF]->(h:Handoff {id:$id}) RETURN h',id=hid)
        require(rows)
        h=rows[0]['h'].properties
        refs=await self.read(p,task,'MATCH (t)-[:HAS_HANDOFF]->(h:Handoff {id:$id})-[:REFERS_TO]->(m:Memory) RETURN m.id AS id LIMIT 10',id=hid)
        h['related_memory_ids']=[r['id'] for r in refs]
        return h

    async def handoff_status(self,p,task,hid,req):
        h=await self.handoff(p,task,hid)
        assignee=h['to_agent_id']==p.agent_id
        require(assignee or (p.role=='coordinator' and req.status=='cancelled'),403,'FORBIDDEN')
        replay=await self.replay(p,task,'handoff_status:'+hid,req)
        if replay:return replay
        require(h['version']==req.expected_version,409,'VERSION_CONFLICT')
        require((h['status'],req.status) in (('open','accepted'),('accepted','done'),('open','cancelled'),('accepted','cancelled')),409,'INVALID_TRANSITION')
        eid=self.ids(p,req.operation_id,'evt')
        body='SET h.status=$status,h.version=$new_version,h.updated_at=$now '
        body+=self.event('HANDOFF_UPDATED','handoff','h','ANNOUNCES_HANDOFF','old_status:$old_status,new_status:$status,old_version:$expected_version,new_version:$new_version,')
        return await self.commit(p,task,'handoff_status:'+hid,req,'MATCH (t)-[:HAS_HANDOFF]->(h:Handoff {id:$id}) ',body,
            result={'handoff_id':hid,'event_id':eid,'status':req.status,'version':h['version']+1},
            extra={'id':hid,'eid':eid,'old_status':h['status'],'new_version':h['version']+1},variables='t,a,h',condition='h.version=$expected_version AND h.status=$old_status')

    async def subscription(self,p,task,req):
        sid='sub_'+stable(p.tenant_id,task,p.agent_id)
        return await self.commit(p,task,'subscription',req,'',
            'MERGE (s:Subscription {id:$id}) ON CREATE SET s.agent_id=$actor,s.task_id=$task,s.created_at=$now SET s.enabled=$enabled MERGE (a)-[:HAS_SUBSCRIPTION]->(s) MERGE (s)-[:COVERS_TASK]->(t)',
            result={'subscription_id':sid,'enabled':req.enabled},extra={'id':sid})

    async def inbox(self,p,after='',limit=100,task_id=None):
        if task_id:await self.authorize(p,task_id)
        rows=await self.db.query(p,
            'MATCH (t:Task)-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) MATCH (i:InboxItem)-[:FOR_AGENT]->(a) MATCH (i)-[:POINTS_TO]->(e:MemoryEvent) '
            'WHERE i.task_id=t.id AND e.task_id=t.id AND ($task IS NULL OR t.id=$task) AND ($unrestricted OR t.id IN $allowed) AND i.created_at+\'|\'+i.id>$after RETURN i,e ORDER BY i.created_at,i.id LIMIT $limit',
            {'actor':p.agent_id,'after':after,'limit':limit,'task':task_id,'unrestricted':p.allowed_task_ids is None,'allowed':list(p.allowed_task_ids or [])})
        items=[dict(**r['i'].properties,event=r['e'].properties) for r in rows]
        return {'items':items,'next_cursor':items[-1]['created_at']+'|'+items[-1]['id'] if len(items)==limit else None,'fetched_at':now()}

    async def inbox_read(self,p,iid,req):
        rows=await self.db.query(p,'MATCH (t:Task)-[:ASSIGNED_TO]->(a:Agent {id:$actor,enabled:true}) MATCH (i:InboxItem {id:$id})-[:FOR_AGENT]->(a) WHERE i.task_id=t.id RETURN i',{'actor':p.agent_id,'id':iid})
        require(rows)
        task=rows[0]['i'].properties['task_id']
        return await self.commit(p,task,'inbox_read:'+iid,req,'MATCH (i:InboxItem {id:$id})-[:FOR_AGENT]->(a) ',"SET i.status='read'",result={'inbox_id':iid,'status':'read'},extra={'id':iid},variables='t,a,i')

