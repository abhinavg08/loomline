"""Opt in: exactly one inexpensive completion per configured role; no secret output."""
import json
from pathlib import Path
from agents.shared_client import AgentClient,op
import httpx


def main():
    report={'roles':{},'metrics':[],'through_gateway':True}
    status=AgentClient('coordinator').request('GET','/v1/inference-status')
    if not status.get('live_enabled'):
        report.update(status='BLOCKED',reason='NIM_LIVE_DISABLED; owner must replace exposed credentials before enabling live inference')
        Path('artifacts').mkdir(exist_ok=True)
        Path('artifacts/nvidia_live_probe_blocked.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        raise SystemExit(1)
    for role in ('investigator','verifier','coordinator'):
        c=AgentClient(role);sid=c.session()
        # No caller-side retries: exactly one probe intent per configured role.
        response=c.http.post('/v1/agent-inference/probe',json=dict(operation_id=op(),session_id=sid,task_id='incident_42'),timeout=120)
        if response.status_code==200:
            report['roles'][role]=response.json()['status'];report['model']=response.json()['model']
        else:report['roles'][role]=response.json().get('error',{}).get('code','FAIL')
        status=c.request('GET','/v1/inference-status')
        report['metrics']+=status['metrics']
    report['status']='PASS' if all(report['roles'].get(role)=='PASS' for role in ('investigator','verifier','coordinator')) else 'FAIL'
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/nvidia_live_probe.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    if report['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
