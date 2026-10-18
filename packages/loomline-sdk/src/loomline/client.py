"""Public HTTP client; deliberately independent of the Loomline server package."""
import asyncio
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import random
import re
import time
import uuid
from urllib.parse import quote
import httpx
from pydantic import ValidationError as ModelError
from .errors import *
from .models import Record,MemoryInput,MemoryRecord,ChangeBatch


def operation_id():return 'sdk_'+uuid.uuid4().hex
def segment(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):raise ValidationError('INVALID_IDENTIFIER')
    return quote(value,safe='')
def task_path(task):return '/v1/tasks/'+segment(task)
def intent(value=None):return segment(value or operation_id())


def failure(response,oid=None):
    try:code=response.json().get('error',{}).get('code','REQUEST_FAILED')
    except (ValueError,AttributeError):code='REQUEST_FAILED'
    if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code):code='REQUEST_FAILED'
    error=ERRORS.get(response.status_code,ServiceUnavailable if response.status_code>=500 else LoomlineError)
    if code=='COMMIT_OUTCOME_UNKNOWN':error=CommitOutcomeUnknown
    return error(code,response.status_code,oid)


def wait_time(response,attempt):
    header=response.headers.get('Retry-After') if response else None
    if header:
        try:delay=float(header)
        except ValueError:
            try:delay=(parsedate_to_datetime(header)-datetime.now(timezone.utc)).total_seconds()
            except (ValueError,TypeError):delay=0
        if delay>30:raise RateLimitError('RETRY_LATER',429)
        return max(0,delay)
    return min(2,.1*2**attempt)+random.uniform(0,.05)


def decode(response):
    try:value=response.json()
    except ValueError:raise ServiceUnavailable('INVALID_SERVER_RESPONSE',response.status_code) from None
    if isinstance(value,dict) and 'class' in value and 'source_turn_id' in value:
        try:MemoryRecord.model_validate(value)
        except ModelError:raise ServiceUnavailable('INVALID_MEMORY_RESPONSE',response.status_code) from None
    return Record(value,response.status_code)


def pack(context,goal,max_tokens,memory_classes):
    if not isinstance(max_tokens,int) or not 256<=max_tokens<=8192:raise ValidationError('INVALID_CONTEXT_BUDGET')
    if not isinstance(goal,str) or len(goal)>500:raise ValidationError('INVALID_GOAL')
    result={'contract_version':'0.1','task_id':context['task']['id'],'goal':goal,'untrusted_data':True,'token_estimate_method':'ceil(UTF-8 bytes / 3), approximate; not a model tokenizer','memories':[],'open_handoffs':[],'estimated_tokens':0,'truncated':False}
    def size(value):return math.ceil(len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())/3)
    # Preserve status/source/evidence labels; never promote hypotheses to facts.
    candidates=[];terms=set(re.findall(r'[a-z0-9]{3,}',goal.lower()))
    for cls in dict.fromkeys(memory_classes):
        if cls not in ('episodic','semantic','procedural'):raise ValidationError('INVALID_MEMORY_CLASS')
        candidates.extend(context.get(cls,[]))
    def rank(m):
        relevance=len(terms & set(re.findall(r'[a-z0-9]{3,}',m['content'].lower())))
        priority=4 if m['class']=='procedural' and m['status']=='active' else 3 if m['status']=='disputed' else 0
        links=min(3,len(m.get('support',[]))+len(m.get('challenges',[])))
        return (5*relevance+priority+links,m.get('created_at',''),m['id'])
    result['ranking']='goal term overlap, approved/disputed status, graph links, recency, ID'
    for m in sorted(candidates,key=rank,reverse=True):
            item={k:m.get(k) for k in ('id','reference','class','assertion_type','status','content','created_by','source_turn_id','version','steps')}
            item['support_ids']=[e['id'] for e in m.get('support',[])];item['challenge_ids']=[e['id'] for e in m.get('challenges',[])]
            result['memories'].append(item)
            if size(result)>max_tokens-12:result['memories'].pop();result['truncated']=True
    for h in context.get('open_handoffs',[]):
        result['open_handoffs'].append({k:h.get(k) for k in ('id','description','to_agent_id','status','version')})
        if size(result)>max_tokens-12:result['open_handoffs'].pop();result['truncated']=True
    result['estimated_tokens']=size(result)
    if result['estimated_tokens']>max_tokens:raise ValidationError('CONTEXT_BUDGET_TOO_SMALL')
    return Record(result)


class API:
    """Shared operation builders. Async subclass returns awaitables from _request."""
    def health(self):return self._request('GET','/health')
    def whoami(self):return self._request('GET','/v1/me')
    def capabilities(self):return self._request('GET','/v1/capabilities')
    def model_status(self):return self._request('GET','/v1/model-status')
    def list_scopes(self):return self._request('GET','/v1/scopes')
    def list_tasks(self,*,after=None,limit=50):return self._request('GET','/v1/tasks',params={'after':after,'limit':limit})
    def create_task(self,title,*,assigned_agent_ids,synthetic=False,template='blank',description=None,status='open',operation_id=None):
        body={'operation_id':intent(operation_id),'title':title,'assigned_agent_ids':list(assigned_agent_ids),'synthetic':synthetic,'template':template}
        if description is not None:body['description']=description
        if status!='open':body['status']=status
        return self._request('POST','/v1/tasks',json=body)
    def agents(self,task_id):return self._request('GET',task_path(task_id)+'/agents')
    def start_session(self,task_id,operation_id=None):return self._request('POST',task_path(task_id)+'/sessions',json={'operation_id':intent(operation_id)})
    def register_framework(self,session_id,framework,framework_version,operation_id=None):return self._request('POST','/v1/sessions/'+segment(session_id)+'/framework',json={'operation_id':intent(operation_id),'framework':framework,'framework_version':framework_version})
    def list_sessions(self,task_id,*,after=None,limit=100):return self._request('GET',task_path(task_id)+'/sessions',params={'after':after,'limit':limit})
    def record_turn(self,session_id,role,content,*,tool_name=None,tool_call_id=None,operation_id=None):
        if role not in ('user','assistant','tool') or not isinstance(content,str) or not 1<=len(content)<=8000:raise ValidationError('INVALID_TURN')
        return self._request('POST','/v1/sessions/'+segment(session_id)+'/turns',json={'operation_id':intent(operation_id),'role':role,'content':content,'tool_name':tool_name,'tool_call_id':tool_call_id})
    def get_history(self,task_id,*,before=None,limit=20):return self._request('GET',task_path(task_id)+'/turns',params={'before':before,'limit':limit})
    def session_turns(self,session_id,after_seq=0,limit=100):return self._request('GET','/v1/sessions/'+segment(session_id)+'/turns',params={'after_seq':after_seq,'limit':limit})
    def remember(self,task_id,*,session_id,source_turn_id,memory_class,assertion_type,status,content,operation_id=None,**references):
        try:body=MemoryInput(operation_id=intent(operation_id),session_id=session_id,source_turn_id=source_turn_id,memory_class=memory_class,assertion_type=assertion_type,status=status,content=content,**references).model_dump(by_alias=True)
        except (ModelError,TypeError):raise ValidationError('INVALID_MEMORY') from None
        return self._request('POST',task_path(task_id)+'/memories',json=body)
    def observe(self,task_id,content,**kw):return self.remember(task_id,content=content,memory_class='episodic',assertion_type='observation',status='active',**kw)
    def remember_episode(self,task_id,content,**kw):return self.remember(task_id,content=content,memory_class='episodic',assertion_type='episode',status='active',**kw)
    def remember_fact(self,task_id,content,**kw):return self.remember(task_id,content=content,memory_class='semantic',assertion_type='observation',status='active',**kw)
    def hypothesize(self,task_id,content,**kw):return self.remember(task_id,content=content,memory_class='semantic',assertion_type='hypothesis',status='proposed',**kw)
    def propose_procedure(self,task_id,content,*,steps,**kw):return self.remember(task_id,content=content,memory_class='procedural',assertion_type='procedure',status='proposed',steps=steps,**kw)
    def get_memory(self,task_id,memory_id):return self._request('GET',task_path(task_id)+'/memories/'+segment(memory_id))
    def resolve(self,memory_reference):return self._request('GET','/v1/resolve',params={'reference':memory_reference})
    def trace(self,memory_reference):return self._request('GET','/v1/trace',params={'reference':memory_reference})
    def get_context(self,task_id,*,query=None,limit=10,entity_id=None):return self._request('GET',task_path(task_id)+'/context',params={'query':query,'limit':limit,'entity_id':entity_id})
    recall=get_context
    def decision_context(self,task_id,entity_id='checkout'):return self._request('GET',task_path(task_id)+'/decision-context',params={'entity_id':entity_id})
    def record_evidence(self,task_id,*,content,source_type,source_ref,observed_at,operation_id=None):
        if isinstance(observed_at,datetime):observed_at=observed_at.isoformat()
        return self._request('POST',task_path(task_id)+'/evidence',json={'operation_id':intent(operation_id),'content':content,'source_type':source_type,'source_ref':source_ref,'observed_at':observed_at})
    def challenge(self,task_id,memory_id,*,evidence_id,reason,expected_version,operation_id=None):return self._request('POST',task_path(task_id)+'/memories/'+segment(memory_id)+'/challenges',json={'operation_id':intent(operation_id),'evidence_id':evidence_id,'reason':reason,'expected_version':expected_version})
    def support(self,task_id,memory_id,*,evidence_id,reason,expected_version,operation_id=None):return self._request('POST',task_path(task_id)+'/memories/'+segment(memory_id)+'/support',json={'operation_id':intent(operation_id),'evidence_id':evidence_id,'reason':reason,'expected_version':expected_version})
    def _status(self,task_id,memory_id,status,expected_version,reason,operation_id):return self._request('PATCH',task_path(task_id)+'/memories/'+segment(memory_id)+'/status',json={'operation_id':intent(operation_id),'status':status,'expected_version':expected_version,'reason':reason})
    def approve_procedure(self,task_id,memory_id,*,expected_version,reason,operation_id=None):return self._status(task_id,memory_id,'active',expected_version,reason,operation_id)
    def retire(self,task_id,memory_id,*,expected_version,reason,operation_id=None):return self._status(task_id,memory_id,'retired',expected_version,reason,operation_id)
    def supersede(self,task_id,memory_id,*,expected_version,reason,operation_id=None):return self._status(task_id,memory_id,'superseded',expected_version,reason,operation_id)
    def handoff(self,task_id,to_agent_id,description,*,related_memory_ids=(),operation_id=None):return self._request('POST',task_path(task_id)+'/handoffs',json={'operation_id':intent(operation_id),'to_agent_id':to_agent_id,'description':description,'related_memory_ids':list(related_memory_ids)})
    def get_handoff(self,task_id,handoff_id):return self._request('GET',task_path(task_id)+'/handoffs/'+segment(handoff_id))
    def _handoff_status(self,task_id,handoff_id,status,expected_version,operation_id):return self._request('PATCH',task_path(task_id)+'/handoffs/'+segment(handoff_id),json={'operation_id':intent(operation_id),'status':status,'expected_version':expected_version})
    def accept_handoff(self,task_id,handoff_id,*,expected_version,operation_id=None):return self._handoff_status(task_id,handoff_id,'accepted',expected_version,operation_id)
    def complete_handoff(self,task_id,handoff_id,*,expected_version,operation_id=None):return self._handoff_status(task_id,handoff_id,'done',expected_version,operation_id)
    def cancel_handoff(self,task_id,handoff_id,*,expected_version,operation_id=None):return self._handoff_status(task_id,handoff_id,'cancelled',expected_version,operation_id)
    def subscribe(self,task_id,enabled=True,*,operation_id=None):return self._request('POST',task_path(task_id)+'/subscriptions',json={'operation_id':intent(operation_id),'enabled':enabled})
    def get_inbox(self,*,after=None,task_id=None,limit=100):return self._request('GET','/v1/inbox',params={'after':after,'task_id':task_id,'limit':limit})
    def mark_inbox_read(self,inbox_id,operation_id=None):return self._request('POST','/v1/inbox/'+segment(inbox_id)+'/read',json={'operation_id':intent(operation_id)})
    def operation_status(self,task_id,operation_id):return self._request('GET',task_path(task_id)+'/operations/'+segment(operation_id))
    def changes_since(self,task_id,cursor=None,limit=50):return self._request('GET',task_path(task_id)+'/changes',params={'cursor':cursor,'limit':limit})
    def infer(self,task_id,session_id,operation_id=None):return self._request('POST','/v1/agent-inference',json={'operation_id':intent(operation_id),'task_id':task_id,'session_id':session_id})
    def claims(self,task_id,*,after=None,limit=50):return self._request('GET',task_path(task_id)+'/claims',params={'after':after,'limit':limit})
    def get_claim(self,task_id,work_key):return self._request('GET',task_path(task_id)+'/claims/'+segment(work_key))
    def claim_work(self,task_id,work_key,*,lease_seconds=300,expected_version=None,operation_id=None):return self._request('POST',task_path(task_id)+'/claims/'+segment(work_key),json={'operation_id':intent(operation_id),'lease_seconds':lease_seconds,'expected_version':expected_version})
    def release_work(self,task_id,work_key,*,expected_version,operation_id=None):return self._request('POST',task_path(task_id)+'/claims/'+segment(work_key)+'/release',json={'operation_id':intent(operation_id),'expected_version':expected_version})
    def record_mcp_activity(self,task_id,*,session_id,tool_name,outcome,error_code='NONE',duration_ms=0,operation_id=None):return self._request('POST',task_path(task_id)+'/mcp-activity',json={'operation_id':intent(operation_id),'session_id':session_id,'tool_name':tool_name,'outcome':outcome,'error_code':error_code,'duration_ms':duration_ms})
    def mcp_activity(self,task_id,*,after=0,limit=50):return self._request('GET',task_path(task_id)+'/mcp-activity',params={'after':after,'limit':limit})
    def reason(self,task_id,session_id,*,goal,purpose='investigate',include_shared_memory=True,operation_id=None):return self._request('POST','/v1/reasoning',json={'operation_id':intent(operation_id),'task_id':task_id,'session_id':session_id,'goal':goal,'purpose':purpose,'include_shared_memory':include_shared_memory})


class Transport:
    def _setup(self,base_url,token,timeout,max_attempts,transport,async_mode):
        url=httpx.URL(base_url)
        if url.scheme not in ('http','https') or url.userinfo or url.query or url.fragment:raise ValidationError('INVALID_BASE_URL')
        if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValidationError('INVALID_CREDENTIAL')
        if not 1<=max_attempts<=5 or not 0<timeout<=180:raise ValidationError('INVALID_CLIENT_LIMIT')
        self.max_attempts=max_attempts
        cls=httpx.AsyncClient if async_mode else httpx.Client
        self._http=cls(base_url=base_url.rstrip('/'),headers={'Authorization':'Bearer '+token},timeout=timeout,transport=transport,follow_redirects=False,trust_env=False)
    def __repr__(self):return f'<{type(self).__name__} credentials=REDACTED>'
    @staticmethod
    def _params(kw):
        if 'params' in kw:kw['params']={k:v for k,v in kw['params'].items() if v is not None}
        return kw
    @staticmethod
    def _recover_path(path,body):
        match=re.match(r'^(/v1/tasks/[^/]+)/',path)
        return match.group(1)+'/operations/'+body['operation_id'] if match and body and body.get('operation_id') else None
    @staticmethod
    def _retry(response):
        if response.status_code not in (429,502,503,504):return False
        try:code=response.json().get('error',{}).get('code','')
        except (ValueError,AttributeError):code=''
        return not code.startswith('NIM_')


class LoomlineClient(API,Transport):
    def __init__(self,base_url,*,token,timeout=30,max_attempts=3,transport=None):self._setup(base_url,token,timeout,max_attempts,transport,False)
    def _request(self,method,path,**kw):
        kw=self._params(kw);body=kw.get('json',{});oid=body.get('operation_id');recover=self._recover_path(path,body)
        for attempt in range(self.max_attempts):
            response=None
            try:
                response=self._http.request(method,path,**kw)
                if response.is_success:return decode(response)
                if not self._retry(response) or attempt==self.max_attempts-1:raise failure(response,oid)
            except (httpx.TimeoutException,httpx.NetworkError):
                if recover:
                    try:
                        found=self._http.get(recover)
                        if found.status_code==200:return decode(found)
                    except (httpx.TimeoutException,httpx.NetworkError):pass
                if attempt==self.max_attempts-1:raise (CommitOutcomeUnknown if method!='GET' else ServiceUnavailable)('NETWORK_OUTCOME_UNKNOWN',0,oid) from None
            time.sleep(wait_time(response,attempt))
    def close(self):self._http.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def session(self,task_id,*,operation_id=None):return Session(self,task_id,operation_id)
    def resume_task(self,task_id,*,cursor=None,limit=10):
        history=self.get_history(task_id,before=cursor,limit=20);context=self.get_context(task_id,limit=limit);session=self.start_session(task_id)
        return Record({'session_id':session.session_id,'context':context,'history':history,'new_session':True})
    def context_pack(self,task_id,*,goal,max_tokens=2048,memory_classes=('episodic','semantic','procedural')):return pack(self.get_context(task_id,limit=20),goal,max_tokens,memory_classes)
    def iter_history(self,task_id,*,before=None,limit=100):
        while True:
            page=self.get_history(task_id,before=before,limit=limit)
            yield from page['items']
            before=page.get('next_cursor')
            if not before:return
    def iter_sessions(self,task_id,*,after=None,limit=100):
        while True:
            page=self.list_sessions(task_id,after=after,limit=limit);yield from page['items'];after=page.get('next_cursor')
            if not after:return
    def iter_inbox(self,*,after=None,task_id=None,limit=100):
        while True:
            page=self.get_inbox(after=after,task_id=task_id,limit=limit);yield from page['items'];after=page.get('next_cursor')
            if not after:return
    def watch(self,task_id,*,cursor=None,poll_interval=1,max_polls=None):
        if not .1<=poll_interval<=60:raise ValidationError('INVALID_POLL_INTERVAL')
        count=0
        while max_polls is None or count<max_polls:
            count+=1;batch=ChangeBatch(self.changes_since(task_id,cursor))
            if batch['items']:
                yield batch
                if not batch.acknowledged:return
                cursor=batch['next_cursor']
            else:time.sleep(poll_interval)


class AsyncLoomlineClient(API,Transport):
    def __init__(self,base_url,*,token,timeout=30,max_attempts=3,transport=None):self._setup(base_url,token,timeout,max_attempts,transport,True)
    async def _request(self,method,path,**kw):
        kw=self._params(kw);body=kw.get('json',{});oid=body.get('operation_id');recover=self._recover_path(path,body)
        for attempt in range(self.max_attempts):
            response=None
            try:
                response=await self._http.request(method,path,**kw)
                if response.is_success:return decode(response)
                if not self._retry(response) or attempt==self.max_attempts-1:raise failure(response,oid)
            except (httpx.TimeoutException,httpx.NetworkError):
                if recover:
                    try:
                        found=await self._http.get(recover)
                        if found.status_code==200:return decode(found)
                    except (httpx.TimeoutException,httpx.NetworkError):pass
                if attempt==self.max_attempts-1:raise (CommitOutcomeUnknown if method!='GET' else ServiceUnavailable)('NETWORK_OUTCOME_UNKNOWN',0,oid) from None
            await asyncio.sleep(wait_time(response,attempt))
    async def aclose(self):await self._http.aclose()
    close=aclose
    async def __aenter__(self):return self
    async def __aexit__(self,*args):await self.aclose()
    def session(self,task_id,*,operation_id=None):return AsyncSession(self,task_id,operation_id)
    async def resume_task(self,task_id,*,cursor=None,limit=10):
        history=await self.get_history(task_id,before=cursor,limit=20);context=await self.get_context(task_id,limit=limit);session=await self.start_session(task_id)
        return Record({'session_id':session.session_id,'context':context,'history':history,'new_session':True})
    async def context_pack(self,task_id,*,goal,max_tokens=2048,memory_classes=('episodic','semantic','procedural')):return pack(await self.get_context(task_id,limit=20),goal,max_tokens,memory_classes)
    async def iter_history(self,task_id,*,before=None,limit=100):
        while True:
            page=await self.get_history(task_id,before=before,limit=limit)
            for item in page['items']:yield item
            before=page.get('next_cursor')
            if not before:return
    async def iter_sessions(self,task_id,*,after=None,limit=100):
        while True:
            page=await self.list_sessions(task_id,after=after,limit=limit)
            for item in page['items']:yield item
            after=page.get('next_cursor')
            if not after:return
    async def iter_inbox(self,*,after=None,task_id=None,limit=100):
        while True:
            page=await self.get_inbox(after=after,task_id=task_id,limit=limit)
            for item in page['items']:yield item
            after=page.get('next_cursor')
            if not after:return
    async def watch(self,task_id,*,cursor=None,poll_interval=1,max_polls=None):
        if not .1<=poll_interval<=60:raise ValidationError('INVALID_POLL_INTERVAL')
        count=0
        while max_polls is None or count<max_polls:
            count+=1;batch=ChangeBatch(await self.changes_since(task_id,cursor))
            if batch['items']:
                yield batch
                if not batch.acknowledged:return
                cursor=batch['next_cursor']
            else:await asyncio.sleep(poll_interval)


class Session:
    def __init__(self,client,task_id,oid=None):self.client=client;self.task_id=task_id;self.operation_id=intent(oid);self.session_id=None
    def __repr__(self):return f'<{type(self).__name__} task={self.task_id!r} session={self.session_id!r}>'
    def __enter__(self):self.session_id=self.client.start_session(self.task_id,self.operation_id).session_id;return self
    def __exit__(self,*args):pass
    def record_turn(self,role,content,**kw):return self.client.record_turn(self.session_id,role,content,**kw)
    def recall(self,**kw):return self.client.recall(self.task_id,**kw)
    def handoff(self,to_agent_id,description,**kw):return self.client.handoff(self.task_id,to_agent_id,description,**kw)
    def remember(self,content,*,source_turn_id=None,source_role='tool',operation_id=None,**kw):
        oid=intent(operation_id)
        if source_turn_id is None:source_turn_id=self.record_turn(source_role,content,operation_id='source_'+hashlib.sha256(oid.encode()).hexdigest()[:40]).turn_id
        return self.client.remember(self.task_id,session_id=self.session_id,source_turn_id=source_turn_id,content=content,operation_id=oid,**kw)
    def observe(self,content,**kw):return self.remember(content,memory_class='episodic',assertion_type='observation',status='active',**kw)
    def remember_episode(self,content,**kw):return self.remember(content,memory_class='episodic',assertion_type='episode',status='active',**kw)
    def remember_fact(self,content,**kw):return self.remember(content,memory_class='semantic',assertion_type='observation',status='active',**kw)
    def hypothesize(self,content,**kw):return self.remember(content,memory_class='semantic',assertion_type='hypothesis',status='proposed',source_role='assistant',**kw)
    def propose_procedure(self,content,*,steps,**kw):return self.remember(content,memory_class='procedural',assertion_type='procedure',status='proposed',steps=steps,source_role='assistant',**kw)


class AsyncSession(Session):
    async def __aenter__(self):self.session_id=(await self.client.start_session(self.task_id,self.operation_id)).session_id;return self
    async def __aexit__(self,*args):pass
    async def remember(self,content,*,source_turn_id=None,source_role='tool',operation_id=None,**kw):
        oid=intent(operation_id)
        if source_turn_id is None:source_turn_id=(await self.record_turn(source_role,content,operation_id='source_'+hashlib.sha256(oid.encode()).hexdigest()[:40])).turn_id
        return await self.client.remember(self.task_id,session_id=self.session_id,source_turn_id=source_turn_id,content=content,operation_id=oid,**kw)
