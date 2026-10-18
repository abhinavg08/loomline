"""Independent role process: HTTP only. Synthetic telemetry; bounded LLM proposals."""
import argparse
import json
import os
import socket
from .shared_client import AgentClient,op

TASK_ID=os.environ.get('LOOM_TASK_ID','incident_42')
TASK='/v1/tasks/'+TASK_ID


def evidence(c,content,ref,time):
    return c.request('POST',TASK+'/evidence',json=dict(operation_id=op(),source_type='synthetic',source_ref='synthetic:'+ref,content=content,observed_at='2026-10-17T'+time+':00+00:00'))['evidence_id']


def proposal(c,role,sid,offline,known):
    if not offline:
        return c.request('POST','/v1/agent-inference',json=dict(operation_id=op(),task_id=TASK_ID,session_id=sid))
    if role=='investigator':
        item=dict(action='hypothesis',content='OFFLINE deterministic policy: Deployment-17 might explain the errors; attribution remains uncertain.',evidence_ids=[known['deployment_evidence']],entity_ids=['checkout','deployment-17'])
    elif role=='verifier':
        m=c.request('GET',TASK+'/memories/'+known['hypothesis_id'])
        item=dict(action='challenge',content='OFFLINE deterministic timing comparison',memory_id=m['id'],evidence_id=known['payments_evidence'],expected_version=m['version'],reason='Payments timeouts started after deployment and before checkout errors; deployment-only attribution is unproven.')
    else:
        paths=c.request('GET',TASK+'/decision-context')['paths']
        path=next(x for x in paths if x['subject_id']=='payments')
        item=dict(action='handoff',content='OFFLINE deterministic graph-based next step',to_agent_id='verifier',description='Compare deployment and Payments timeout timing',related_memory_ids=[known['hypothesis_id']],rationale=f"OFFLINE policy: prioritize {path['upstream']} investigation because {path['service']} DEPENDS_ON {path['upstream']}; evidence {path['evidence_id']} reports {path['evidence']}. Disputed deployment attribution remains uncertain.",evidence_ids=[path['evidence_id']])
    tid=c.turn(sid,json.dumps({'mode':'offline_deterministic_policy','proposal':item}))
    return {'mode':'offline_deterministic_policy','proposal':item,'source_turn_id':tid,'dependency_paths':c.request('GET',TASK+'/decision-context')['paths'] if role=='coordinator' else []}


def run(role,phase,offline,known):
    c=AgentClient(role);sid=c.session()
    c.request('POST',TASK+'/subscriptions',json={'operation_id':op(),'enabled':True})
    result={'pid':os.getpid(),'process_host':socket.gethostname(),'role':role,'session_id':sid,'mode':'offline_deterministic_policy' if offline else 'live_nvidia'}
    if phase=='prepare':
        tid=c.turn(sid,'Synthetic approved procedure proposal: compare upstream timing before rollback')
        procedure,_=c.remember(sid,tid,'Check upstream dependency timeouts before rollback',**{'class':'procedural'},assertion_type='procedure',status='proposed',steps=['Read service dependency paths','Compare deployment and upstream timeout timestamps','Keep disputed hypotheses visible and hand off unresolved work'])
        c.request('PATCH',TASK+'/memories/'+procedure['memory_id']+'/status',json=dict(operation_id=op(),expected_version=1,status='active',reason='Coordinator reviewed synthetic incident procedure'))
        return {**result,'procedure_id':procedure['memory_id'],'mode':'graph_only_preparation'}
    if phase=='resume':
        ctx=c.request('GET',TASK+'/context')
        assert any(m['id']==known['hypothesis_id'] and m['status']=='disputed' for m in ctx['semantic'])
        assert ctx['episodic'] and ctx['procedural'] and ctx['recent_turns']
        c.turn(sid,'Resuming with approved procedure '+ctx['procedural'][0]['id']+': '+ctx['procedural'][0]['steps'][0])
        path=TASK+'/handoffs/'+known['handoff_id']
        assert c.request('GET',path)['status']=='open'
        c.request('PATCH',path,json=dict(operation_id=op(),expected_version=1,status='accepted'))
        c.request('PATCH',path,json=dict(operation_id=op(),expected_version=2,status='done'))
        return {**result,'mode':'graph_only_resume','recovered':True,'handoff_status':'done'}
    if role=='investigator':
        text='At 14:03 Checkout 5xx errors rose from 1% to 18%.'
        tid=c.turn(sid,text,'tool');e=evidence(c,text,'checkout-errors','14:03')
        episode,_=c.remember(sid,tid,text,entity_ids=['checkout'],evidence_ids=[e])
        text='Deployment-17 completed at 14:01.'
        tid=c.turn(sid,text,'tool');de=evidence(c,text,'deployment-17','14:01')
        observation,_=c.remember(sid,tid,text,**{'class':'semantic'},entity_ids=['deployment-17'],evidence_ids=[de])
        known['deployment_evidence']=de
        inference=proposal(c,role,sid,offline,known);p=inference['proposal']
        memory,_=c.remember(sid,inference['source_turn_id'],p['content'],**{'class':'semantic'},assertion_type='hypothesis',status='proposed',entity_ids=p['entity_ids'],evidence_ids=p['evidence_ids'])
        result.update(hypothesis_id=memory['memory_id'],episode_id=episode['memory_id'],deployment_evidence=de)
    elif role=='verifier':
        original=c.request('GET',TASK+'/memories/'+known['hypothesis_id'])
        assert original['created_by']=='investigator'
        text='Payments upstream timeouts started at 14:02'
        tid=c.turn(sid,text,'tool');e=evidence(c,text,'payments-timeouts','14:02')
        c.remember(sid,tid,text,**{'class':'semantic'},entity_ids=['payments'],evidence_ids=[e])
        known['payments_evidence']=e
        inference=proposal(c,role,sid,offline,known);p=inference['proposal']
        # Require this workflow's intended target, even if other demo data is present.
        assert p['memory_id']==known['hypothesis_id'],'Model selected a different hypothesis'
        challenge=c.request('POST',TASK+'/memories/'+p['memory_id']+'/challenges',json=dict(operation_id=op(),evidence_id=p['evidence_id'],reason=p['reason'],expected_version=p['expected_version']))
        result.update(challenge_id=challenge['challenge_id'],payments_evidence=e)
    else:
        inference=proposal(c,role,sid,offline,known);p=inference['proposal']
        assert inference['dependency_paths'],'No graph paths used'
        assert known['hypothesis_id'] in p['related_memory_ids'],'Handoff omitted the current disputed hypothesis'
        decision,_=c.remember(sid,inference['source_turn_id'],p['rationale'],**{'class':'semantic'},assertion_type='decision',entity_ids=['checkout','payments'],evidence_ids=p['evidence_ids'])
        handoff=c.request('POST',TASK+'/handoffs',json=dict(operation_id=op(),to_agent_id=p['to_agent_id'],description=p['description'],related_memory_ids=p['related_memory_ids']+[decision['memory_id']]))
        result.update(handoff_id=handoff['handoff_id'],decision_id=decision['memory_id'],dependency_paths=inference['dependency_paths'],rationale=p['rationale'])
    result.update(model=inference.get('model'),source_turn_id=inference['source_turn_id'])
    if not offline:result['nim_metrics']=c.request('GET','/v1/inference-status')['metrics']
    return result


def main(role=None):
    parser=argparse.ArgumentParser()
    if role is None:parser.add_argument('role',choices=['investigator','verifier','coordinator'])
    parser.add_argument('--phase',default='investigate',choices=['investigate','prepare','resume'])
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--known',default='{}')
    args=parser.parse_args()
    print(json.dumps(run(role or args.role,args.phase,args.offline,json.loads(args.known))),flush=True)


if __name__=='__main__':main()
