"""Separate framework process. Only task ID and public synthetic input cross boundaries."""
import argparse
from importlib.metadata import version
import json
import os
import socket
from .runtime import client,telemetry_off
from loomline.integrations.common import plan

def run(framework,task_id,branch,offline):
    telemetry_off()
    with client(framework) as c:
        identity=c.whoami()
        if framework=='custom':
            resumed=c.resume_task(task_id);sid=resumed.session_id
            c.register_framework(sid,'custom','0.1.0')
            reply=plan(c,task_id,sid,'verifier','Resume the unfinished assigned handoff. Use historical evidence, preserve disagreement, consult the approved procedure and complete the work.',offline,purpose='resume')
            p=reply['proposal'];h=c.get_handoff(task_id,p['handoff_id'])
            if h.status=='open':h=c.accept_handoff(task_id,h.id,expected_version=h.version)
            done=c.complete_handoff(task_id,p['handoff_id'],expected_version=h.version)
            body={'runtime':'custom Python public SDK','new_session':True,'recovered_turns':len(resumed.history['items']),'recovered_classes':[name for name in ('episodic','semantic','procedural') if resumed.context[name]],'applied_procedure_id':p['procedure_id'],'consulted_steps':p['consulted_steps'],'handoff_id':p['handoff_id'],'handoff_status':done.status,'model_reply':dict(reply)}
            actual_version='0.1.0'
        else:
            actual_version=version(framework)
            with c.session(task_id) as s:
                sid=s.session_id;c.register_framework(sid,framework,actual_version)
                if framework=='langchain':
                    ev=c.record_evidence(task_id,content='Deployment-17 completed at 14:01.',source_type='synthetic',source_ref='synthetic:deployment',observed_at='2026-10-17T14:01:00Z')
                    s.remember_fact('Deployment-17 completed at 14:01.',evidence_ids=[ev.evidence_id],entity_ids=['deployment-17'])
                    checkout=c.record_evidence(task_id,content='Checkout 5xx errors rose at 14:03.',source_type='synthetic',source_ref='synthetic:checkout',observed_at='2026-10-17T14:03:00Z')
                    s.observe('Checkout 5xx errors rose at 14:03.',evidence_ids=[checkout.evidence_id],entity_ids=['checkout'])
                    from loomline.integrations.langchain import run_agent
                    body=run_agent(c,task_id,sid,'Investigate the synthetic Checkout incident. Propose an uncertain deployment hypothesis from the actual deployment evidence using the Loomline memory tool.',offline=offline)
                elif framework=='langgraph':
                    content='Payments upstream timeouts started at 14:02, before Checkout failures.' if branch=='upstream' else 'Synthetic rollback of Deployment-17 at 14:04 restored Checkout; Payments remained healthy.'
                    evidence=c.record_evidence(task_id,content=content,source_type='synthetic',source_ref='synthetic:judge-'+branch,observed_at='2026-10-17T14:02:00Z' if branch=='upstream' else '2026-10-17T14:04:00Z')
                    s.remember_fact(content,evidence_ids=[evidence.evidence_id],entity_ids=['payments' if branch=='upstream' else 'deployment-17'])
                    from loomline.integrations.langgraph import workflow
                    result=workflow(c,task_id,sid,offline=offline).invoke({'goal':'Assess the existing deployment hypothesis using the newly supplied evidence: '+content+' Choose support or challenge honestly; retain uncertainty.'})
                    body={'runtime':'langgraph.StateGraph.compile.invoke',**result}
                else:
                    target=next(a['id'] for a in c.agents(task_id)['items'] if a['id'].endswith('custom'))
                    from loomline.integrations.crewai import run_crew
                    body=run_crew(c,task_id,sid,'Use the approved procedure and actual dependency/evidence paths. Create a cautious evidence-linked handoff to '+target+'. Cite the existing hypothesis and approved procedure, and the actual consulted step numbers.',offline=offline)
        ctx=c.get_context(task_id,limit=20)
        return {'status':'PASS','framework':framework,'framework_version':actual_version,'mode':'offline_framework_run' if offline else 'live_nvidia','task_id':task_id,'agent_id':identity.agent_id,'role':identity.role,'pid':os.getpid(),'host':socket.gethostname(),'session_id':sid,'memory_ids':[m['id'] for name in ('episodic','semantic','procedural') for m in ctx[name]],'body':body}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('framework',choices=['langchain','langgraph','crewai','custom']);parser.add_argument('--task',required=True);parser.add_argument('--branch',choices=['upstream','deployment'],default='upstream');mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--offline',action='store_true');mode.add_argument('--live-nvidia',action='store_true');args=parser.parse_args()
    try:print(json.dumps(run(args.framework,args.task,args.branch,args.offline)),flush=True)
    except Exception as exc:
        # Never dump third-party exception reprs, model prompts or credentials.
        from loomline import LoomlineError
        code=exc.code if isinstance(exc,LoomlineError) else type(exc).__name__
        print(json.dumps({'status':'FAIL','framework':args.framework,'task_id':args.task,'error_code':code}),flush=True)
        raise SystemExit(1)

if __name__=='__main__':main()
