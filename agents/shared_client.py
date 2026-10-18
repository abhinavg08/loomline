"""Agent processes hold a Loomline identity token, never NVIDIA/DB credentials."""
import json
import os
from pathlib import Path
import uuid
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


def op():
    return 'agent_'+uuid.uuid4().hex


class AgentError(Exception):pass


class AgentClient:
    def __init__(self, role, tenant='alpha', base_url=None,task_id=None):
        self.task_id=task_id or os.environ.get('LOOM_TASK_ID','incident_42')
        self.task_path='/v1/tasks/'+self.task_id
        token=os.environ.get('LOOM_AGENT_TOKEN')
        if not token:
            token=json.loads(Path(os.environ.get('LOOM_TOKEN_FILE',ROOT/'.secrets/agent_tokens.json')).read_text())[tenant+':'+role]
        self.http=httpx.Client(base_url=base_url or os.environ.get('LOOM_URL','http://127.0.0.1:8000'),headers={'Authorization':'Bearer '+token},timeout=180)

    def request(self, method, path, **kw):
        # Retry unknown write outcomes with the identical intent ID/payload.
        for attempt in range(3):
            try:
                r=self.http.request(method,path,**kw)
                code=r.json().get('error',{}).get('code','REQUEST_FAILED') if r.status_code>=400 else ''
                if code in ('OVERLOADED','DATABASE_UNAVAILABLE','COMMIT_OUTCOME_UNKNOWN') and attempt<2:
                    time.sleep(.1*2**attempt)
                    continue
                if r.status_code>=400:raise AgentError(f'HTTP {r.status_code}: {code}')
                return r.json()
            except (httpx.TimeoutException,httpx.NetworkError):
                if attempt==2:
                    raise AgentError('NETWORK_OUTCOME_UNKNOWN: retry the same operation intent') from None
                time.sleep(.1*2**attempt)

    def session(self):
        return self.request('POST',self.task_path+'/sessions',json={'operation_id':op()})['session_id']

    def turn(self,sid,content,role='assistant'):
        return self.request('POST',f'/v1/sessions/{sid}/turns',json={'operation_id':op(),'role':role,'content':content})['turn_id']

    def remember(self,sid,tid,content,**kw):
        body={'operation_id':op(),'session_id':sid,'source_turn_id':tid,'class':'episodic','assertion_type':'observation','status':'active','content':content,**kw}
        return self.request('POST',self.task_path+'/memories',json=body),body
