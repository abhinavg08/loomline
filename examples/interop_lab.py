"""One command / four independent runtimes / one real shared-memory task."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from .runtime import client,telemetry_off

STAGES=['langchain','langgraph','crewai','custom']

def main():
    telemetry_off()
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group();mode.add_argument('--offline',action='store_true');mode.add_argument('--live-nvidia',action='store_true');parser.add_argument('--branch',choices=['upstream','deployment'],default='upstream');parser.add_argument('--pause-after',choices=STAGES[:-1]);parser.add_argument('--resume');args=parser.parse_args()
    if not args.resume and not (args.offline or args.live_nvidia):raise SystemExit('Choose --offline or --live-nvidia explicitly')
    reports=Path('artifacts/platform');reports.mkdir(parents=True,exist_ok=True)
    with client('crewai') as coordinator:
        assert coordinator.health()['schema_ready']
        coordinator.capabilities()
        if args.resume:
            report=json.loads(Path(args.resume).read_text());task=report['task_id'];args.branch=report['branch'];offline=report['mode']=='offline_framework_run'
        else:
            offline=args.offline
            if not offline:
                status=coordinator.model_status()
                if not status['live_enabled'] or not status['role_configured']:raise SystemExit('Live NIM configuration unavailable; no offline fallback substituted')
            identities={}
            for framework in STAGES:
                with client(framework) as c:identities[framework]=c.whoami().agent_id
            assert len(set(identities.values()))==4,'Four independent authenticated identities required'
            task=coordinator.create_task('Interoperability Lab · '+args.branch,assigned_agent_ids=list(identities.values()),synthetic=True,template='checkout').task_id
            with coordinator.session(task) as s:
                s.observe('Operator selected synthetic branch: '+args.branch+'. Mode: '+('offline framework policy' if offline else 'real NVIDIA reasoning'))
                procedure=s.propose_procedure('Evidence-aware continuity procedure',steps=['Read original support and contrary evidence; preserve uncertainty','Follow Checkout DEPENDS_ON Payments and compare observed timing','Delegate unfinished work with source IDs; resume before completing'])
            coordinator.approve_procedure(task,procedure.memory_id,expected_version=1,reason='Local operator reviewed the synthetic lab procedure')
            report={'status':'RUNNING','task_id':task,'branch':args.branch,'mode':'offline_framework_run' if offline else 'live_nvidia','identities':identities,'processes':[],'ui_url':os.environ.get('LOOM_PUBLIC_URL',os.environ.get('LOOM_URL','http://127.0.0.1:8000'))+'/?task='+task}
        path=reports/(task+'.json')
        def save():path.write_text(json.dumps(report,indent=2));(reports/'latest-lab.json').write_text(json.dumps(report,indent=2))
        save()
        for framework in STAGES:
            if any(p['framework']==framework and p['status']=='PASS' for p in report['processes']):continue
            command=[sys.executable,'-m','examples.framework_worker',framework,'--task',task,'--branch',args.branch,'--offline' if offline else '--live-nvidia']
            child=subprocess.run(command,capture_output=True,text=True,timeout=360)
            (reports/(task+'-'+framework+'.log')).write_text(child.stdout)  # Explicit JSON + framework runtime output, never env/headers.
            lines=[s for s in child.stdout.splitlines() if s.startswith('{"status":')]
            result=json.loads(lines[-1]) if lines else {'status':'FAIL','framework':framework,'error_code':'NO_WORKER_RESULT'}
            report['processes'].append(result)
            if child.returncode or result['status']!='PASS':
                report['status']='FAIL';save();print(json.dumps({'status':'FAIL','task_id':task,'framework':framework,'error_code':result.get('error_code'),'report':str(path),'ui_url':report['ui_url']}));raise SystemExit(1)
            save();print(json.dumps({'stage':framework,'status':'PASS','agent_id':result['agent_id'],'pid':result['pid'],'session_id':result['session_id']}),flush=True)
            if args.pause_after==framework:report['status']='PAUSED';save();print(json.dumps({'status':'PAUSED','task_id':task,'report':str(path),'ui_url':report['ui_url']}));return
        assert len({p['agent_id'] for p in report['processes'] if p['status']=='PASS'})==4
        assert len({p['session_id'] for p in report['processes'] if p['status']=='PASS'})==4
        report['status']='PASS';report['final_context']=dict(coordinator.get_context(task,limit=20));save()
        from .verify_lab import verify
        try:report['verification']=verify(report)
        except Exception:
            report['status']='FAIL';report['verification_error']='GRAPH_VERIFICATION_FAILED';save();raise
        save()
        print(json.dumps({'status':'PASS','mode':report['mode'],'task_id':task,'report':str(path),'ui_url':report['ui_url']}))

if __name__=='__main__':main()
