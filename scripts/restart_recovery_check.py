"""Restart a dedicated gateway subprocess; retain and recover real graph state."""
import json
import subprocess
import sys
import time
from pathlib import Path
import httpx
from agents.shared_client import AgentClient,op
from .isolation import temporary_runtime


def start(port,log,app_import='backend.app.main:app'):
    process=subprocess.Popen([sys.executable,'-m','uvicorn',app_import,'--host','127.0.0.1','--port',str(port),'--workers','1','--no-access-log'],stdout=log,stderr=log)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Recovery gateway exited; inspect artifacts/recovery.log')
        try:
            if httpx.get(f'http://127.0.0.1:{port}/health',timeout=1).status_code==200:
                return process
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    process.terminate()
    raise RuntimeError('Gateway startup timeout')


def main():
    Path('artifacts').mkdir(exist_ok=True)
    with open('artifacts/recovery.log','w') as log:
        process=start(8011,log)
        try:
            c=AgentClient('coordinator',base_url='http://127.0.0.1:8011')
            sid=c.session()
            tid=c.turn(sid,'Synthetic restart proof observation','tool')
            episode,_=c.remember(sid,tid,'Synthetic restart proof observation')
            hyp,_=c.remember(sid,tid,'Deployment might explain synthetic errors',**{'class':'semantic'},assertion_type='hypothesis',status='proposed')
            ev=c.request('POST','/v1/tasks/incident_42/evidence',json=dict(operation_id=op(),source_type='synthetic',source_ref='synthetic:restart',content='Contrary upstream timing',observed_at='2026-10-17T14:02:00+00:00'))
            c.request('POST','/v1/tasks/incident_42/memories/'+hyp['memory_id']+'/challenges',json=dict(operation_id=op(),evidence_id=ev['evidence_id'],reason='Contrary evidence preserved across API restart',expected_version=1))
            procedure,_=c.remember(sid,tid,'Synthetic recovery procedure',**{'class':'procedural'},assertion_type='procedure',status='proposed',steps=['Read preserved evidence','Resume unfinished work'])
            c.request('PATCH','/v1/tasks/incident_42/memories/'+procedure['memory_id']+'/status',json=dict(operation_id=op(),expected_version=1,status='active',reason='Reviewed procedure'))
            handoff=c.request('POST','/v1/tasks/incident_42/handoffs',json=dict(operation_id=op(),to_agent_id='verifier',description='Resume synthetic investigation after restart',related_memory_ids=[hyp['memory_id']]))
            old_pid=process.pid
            c.http.close()
            process.terminate(); process.wait(timeout=10)
            process=start(8011,log)
            fresh=AgentClient('coordinator',base_url='http://127.0.0.1:8011')
            new_sid=fresh.session()
            assert new_sid!=sid
            turns=fresh.request('GET',f'/v1/sessions/{sid}/turns')['items']
            assert turns[0]['id']==tid and turns[0]['seq']==1
            for resource,status in [(episode,'active'),(hyp,'disputed'),(procedure,'active')]:
                read=fresh.request('GET','/v1/tasks/incident_42/memories/'+resource['memory_id'])
                assert read['status']==status
                if resource is hyp: assert read['challenges'][0]['id']==ev['evidence_id']
                if resource is procedure: assert read['steps']
            ctx=fresh.request('GET','/v1/tasks/incident_42/context')
            assert any(m['id']==procedure['memory_id'] for m in ctx['procedural'])
            fresh.turn(new_sid,'Reusing '+procedure['memory_id']+': '+read['steps'][0])
            v=AgentClient('verifier',base_url='http://127.0.0.1:8011')
            path='/v1/tasks/incident_42/handoffs/'+handoff['handoff_id']
            assert v.request('GET',path)['status']=='open'
            v.request('PATCH',path,json=dict(operation_id=op(),expected_version=1,status='accepted'))
            v.request('PATCH',path,json=dict(operation_id=op(),expected_version=2,status='done'))
            report={'status':'PASS','old_gateway_pid':old_pid,'new_gateway_pid':process.pid,'old_session':sid,'new_session':new_sid,'ordered_turns':len(turns),'recovered':['episode','disputed hypothesis with evidence','approved procedure','handoff accepted/completed after restart']}
            Path('artifacts/api_recovery.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report,indent=2))
        finally:
            process.terminate(); process.wait(timeout=10)


if __name__=='__main__':
    with temporary_runtime():main()
