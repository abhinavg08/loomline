import argparse
import json
import subprocess
import sys
from pathlib import Path
import os
import re
from .shared_client import AgentClient,op


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');parser.add_argument('--pause-before-resume',action='store_true');parser.add_argument('--resume');args=parser.parse_args()
    if args.resume:
        saved=json.loads(Path(args.resume).read_text());known=saved['known'];roles=saved['processes'];task=known['task_id']
    else:
        c=AgentClient('coordinator')
        if not args.offline:
            status=c.request('GET','/v1/inference-status')
            if not status.get('live_enabled'):raise SystemExit('NIM_LIVE_DISABLED: owner must replace exposed keys and explicitly enable live inference; use --offline for graph-only proof.')
        task=c.request('POST','/v1/demo-runs',json={'operation_id':op()})['task_id']
        known={'task_id':task};roles=[]
    child_env={**os.environ,'LOOM_TASK_ID':task}
    def run(role,phase='investigate'):
        command=[sys.executable,'-m','agents.'+role,'--phase',phase,'--known',json.dumps(known)]
        if args.offline:command.append('--offline')
        child=subprocess.run(command,capture_output=True,text=True,timeout=240,env=child_env)
        if child.returncode:
            # Persist only stable error codes, never provider payloads or stderr.
            match=re.search(r'\b(NIM_[A-Z0-9_]+|VERSION_CONFLICT|NETWORK_OUTCOME_UNKNOWN)\b',child.stderr)
            code=match.group(1) if match else 'AGENT_FAILED'
            failure={'status':'FAIL','synthetic':True,'task_id':task,'role':role,'phase':phase,'error_code':code,'known':known,'processes':roles}
            Path('artifacts').mkdir(exist_ok=True)
            Path('artifacts/'+task+'.failure.json').write_text(json.dumps(failure,indent=2))
            raise RuntimeError(role+' failed: '+code+'; task '+task+'. Inspect its failure report; no success recorded.') from None
        result=json.loads(child.stdout);known.update(result);roles.append(result)
    if args.resume:run('verifier','resume')
    else:
        run('investigator');run('coordinator','prepare');run('verifier');run('coordinator')
        if not args.pause_before_resume:run('verifier','resume')
    assert len({(r['process_host'],r['pid']) for r in roles})==len(roles)
    report={'status':'PAUSED' if args.pause_before_resume else 'PASS','synthetic':True,'mode':saved['mode'] if args.resume else 'offline_deterministic_policy' if args.offline else 'live_nvidia','task_id':task,'ui_url':os.environ.get('LOOM_PUBLIC_URL',os.environ.get('LOOM_URL','http://127.0.0.1:8000'))+'/?task='+task,'processes':roles,'known':known}
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/incident_'+('live' if report['mode']=='live_nvidia' else 'offline')+'.json').write_text(json.dumps(report,indent=2))
    Path('artifacts/'+task+'.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('status','synthetic','mode','task_id','ui_url')},indent=2))


if __name__=='__main__':main()
