"""One illustrative paired trial, identical goals/model/budgets, history withheld in one arm.

Offline native framework runs prepare two equivalent, separately scoped fixtures.
Both resumed agents use fresh Python processes and REAL NVIDIA inference. There is
no forced answer: a valid model request for context remains an incomplete handoff.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .runtime import client,telemetry_off

GOAL='Resume my unfinished assigned handoff. Use historical evidence and the approved procedure, preserve disagreement and complete only grounded work. If essential context is missing, request it without inventing IDs or repeating the investigation.'

def worker(task,include):
    import os
    with client('custom') as c:
        sid=c.start_session(task).session_id
        c.register_framework(sid,'custom','0.1.0')
        reply=c.reason(task,sid,goal=GOAL,purpose='continuity_trial',include_shared_memory=include)
        p=reply.proposal;completed=False;correct=None
        if p['action']=='complete_handoff':
            h=c.get_handoff(task,p['handoff_id']);procedure=c.get_memory(task,p['procedure_id'])
            assert h.to_agent_id==c.whoami().agent_id and procedure.status=='active'
            trace=c.trace(procedure.reference)
            correct=bool(trace['source_turn'] and p['consulted_steps'] and p['evidence_ids'])
            assert correct,'Unsubstantiated completion is rejected'
            if h.status=='open':h=c.accept_handoff(task,h.id,expected_version=h.version)
            completed=c.complete_handoff(task,h.id,expected_version=h.version).status=='done'
        return {'task_id':task,'session_id':sid,'pid':os.getpid(),'history_access':include,'model_reply':dict(reply),'handoff_completed':completed,'source_correctness':correct,'new_investigation_steps':0,'missing_context_reported':p['content'] if p['action']=='request_context' else None}

def main():
    telemetry_off()
    parser=argparse.ArgumentParser();parser.add_argument('--live-nvidia',action='store_true',required=True);parser.add_argument('--worker-task');parser.add_argument('--history',choices=['on','off']);args=parser.parse_args()
    if args.worker_task:
        print(json.dumps(worker(args.worker_task,args.history=='on')));return
    folder=Path('artifacts/platform');folder.mkdir(parents=True,exist_ok=True)
    report={'method':'one paired illustrative trial; not statistically significant','goal':GOAL,'fixture_preparation':'two equivalent offline native-framework upstream investigations, paused after CrewAI; different task IDs, no private checkpoint exchange','only_experimental_difference':'historical shared memory included or withheld in gateway model payload','same_resources':'same configured model, role, prompt, decoding and output budgets; one inference per arm unless bounded provider retries','arms':[]}
    for include in (False,True):
        prepared=subprocess.run([sys.executable,'-m','examples.interop_lab','--offline','--branch','upstream','--pause-after','crewai'],capture_output=True,text=True,timeout=360)
        if prepared.returncode:
            (folder/'comparison-preparation-error.log').write_text(prepared.stdout+'\n'+prepared.stderr)
            raise RuntimeError('Fixture preparation failed; inspect private comparison-preparation-error.log')
        line=next(x for x in reversed(prepared.stdout.splitlines()) if x.startswith('{"status": "PAUSED"'))
        task=json.loads(line)['task_id']
        child=subprocess.run([sys.executable,'-m','examples.continuity_comparison','--live-nvidia','--worker-task',task,'--history','on' if include else 'off'],capture_output=True,text=True,timeout=180)
        if child.returncode:raise RuntimeError('Comparison worker failed; no result claimed')
        result=json.loads(child.stdout.splitlines()[-1]);report['arms'].append(result)
        (folder/'continuity-comparison.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'history_access':include,'task_id':task,'action':result['model_reply']['proposal']['action'],'handoff_completed':result['handoff_completed']}),flush=True)
    report['execution_status']='PASS';report['observed_benefit']=report['arms'][1]['handoff_completed'] and not report['arms'][0]['handoff_completed']
    (folder/'continuity-comparison.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'status':'PASS','observed_benefit':report['observed_benefit'],'report':str(folder/'continuity-comparison.json')}))

if __name__=='__main__':main()
