import json
from ..client import Session

def scoped(client,task_id,session_id):
    session=Session(client,task_id);session.session_id=session_id
    return session


def offline_plan(client,task_id,session_id,role,goal,purpose='investigate'):
    """Explicit deterministic policy, not an LLM response. Reads actual shared state."""
    ctx=client.get_context(task_id,limit=20)
    all_memory=[*ctx['episodic'],*ctx['semantic'],*ctx['procedural']]
    evidence=[e for m in all_memory for e in [*m.get('support',[]),*m.get('challenges',[])]]
    if role=='investigator':
        e=next(e for e in evidence if 'Deployment-17' in e['content'])
        plan={'action':'hypothesis','content':'OFFLINE policy: Deployment-17 might explain Checkout errors; attribution remains uncertain.','evidence_ids':[e['id']],'entity_ids':['checkout','deployment-17']}
    elif purpose=='resume':
        h=next(h for h in ctx['open_handoffs'] if h['to_agent_id']==client.whoami().agent_id)
        procedure=ctx['procedural'][0]
        plan={'action':'complete_handoff','handoff_id':h['id'],'procedure_id':procedure['id'],'consulted_steps':[1,2],'content':'OFFLINE policy resumes recorded evidence and approved work','evidence_ids':[e['id'] for e in evidence][:3]}
    elif role=='verifier':
        m=next(m for m in ctx['semantic'] if m['assertion_type']=='hypothesis')
        contrary=[e for e in evidence if 'Payments upstream timeouts started' in e['content']]
        e=contrary[0] if contrary else next(e for e in evidence if 'rollback' in e['content'])
        plan={'action':'challenge' if contrary else 'support','memory_id':m['id'],'expected_version':m['version'],'evidence_ids':[e['id']],'content':'OFFLINE policy compares observed timing; this evidence '+('challenges deployment-only attribution' if contrary else 'supports further deployment investigation without proving causality')}
    else:
        procedure=ctx['procedural'][0];hyp=next(m for m in ctx['semantic'] if m['assertion_type']=='hypothesis')
        target=next(a['id'] for a in client.agents(task_id)['items'] if a['id'].endswith('custom'))
        plan={'action':'handoff','content':'OFFLINE policy: apply '+procedure['id']+' steps 1 and 2 to preserve disputed evidence and investigate the dependency.','evidence_ids':[e['id'] for e in evidence][:3],'to_agent_id':target,'related_memory_ids':[hyp['id']],'description':'Resume evidence comparison and approved procedure','procedure_id':procedure['id'],'consulted_steps':[1,2]}
    tid=client.record_turn(session_id,'assistant',json.dumps({'mode':'offline_framework_policy','proposal':plan})).turn_id
    return {'mode':'offline_framework_policy','proposal':plan,'source_turn_id':tid,'metrics':[]}


def plan(client,task_id,session_id,role,goal,offline,purpose='investigate'):
    return offline_plan(client,task_id,session_id,role,goal,purpose) if offline else client.reason(task_id,session_id,goal=goal,purpose=purpose)


def actions(client,task_id,session_id,executed):
    session=scoped(client,task_id,session_id)
    def recall(query:str='',limit:int=10)->dict:
        """Recall bounded authorized task memory including procedures and disagreements."""
        result=client.get_context(task_id,query=query or None,limit=limit);executed.append('loomline_recall');return dict(result)
    def remember(content:str,memory_class:str,assertion_type:str,status:str,source_turn_id:str,evidence_ids:list[str],entity_ids:list[str]|None=None)->dict:
        """Publish one source-linked typed memory; preserve the proposed/active matrix."""
        result=session.remember(content,source_turn_id=source_turn_id,memory_class=memory_class,assertion_type=assertion_type,status=status,evidence_ids=evidence_ids,entity_ids=entity_ids or []);executed.append('loomline_remember');return dict(result)
    def trace(reference:str)->dict:
        """Follow actual author/source/evidence/status provenance for a Loomline URI."""
        result=client.trace(reference);executed.append('loomline_trace');return dict(result)
    def handoff(to_agent_id:str,description:str,related_memory_ids:list[str],content:str,source_turn_id:str,evidence_ids:list[str],procedure_id:str,consulted_steps:list[int])->dict:
        """Apply approved procedure steps, publish a decision and create durable work."""
        procedure=client.get_memory(task_id,procedure_id)
        if procedure.status!='active' or procedure.memory_class!='procedural':raise ValueError('Approved procedure required')
        steps=[procedure['steps'][i-1] for i in consulted_steps if 1<=i<=len(procedure['steps'])]
        if not steps or len(steps)!=len(consulted_steps):raise ValueError('Invalid procedure step')
        decision=session.remember(content+' | Consulted '+procedure_id+': '+'; '.join(steps),source_turn_id=source_turn_id,memory_class='semantic',assertion_type='decision',status='active',evidence_ids=evidence_ids,entity_ids=['checkout','payments'])
        result=client.handoff(task_id,to_agent_id,description,related_memory_ids=[*related_memory_ids,decision.memory_id,procedure_id]);executed.append('loomline_handoff')
        return {**result,'decision_id':decision.memory_id,'procedure_id':procedure_id,'consulted_steps':consulted_steps}
    def challenge(memory_id:str,evidence_id:str,reason:str,expected_version:int)->dict:
        """Challenge an existing hypothesis with authorized contrary evidence and CAS."""
        result=client.challenge(task_id,memory_id,evidence_id=evidence_id,reason=reason,expected_version=expected_version);executed.append('loomline_challenge');return dict(result)
    return {'loomline_recall':recall,'loomline_remember':remember,'loomline_trace':trace,'loomline_handoff':handoff,'loomline_challenge':challenge}


def tool_action(reply):
    p=reply['proposal'];action=p['action']
    if action=='hypothesis':return 'loomline_remember',{'content':p['content'],'memory_class':'semantic','assertion_type':'hypothesis','status':'proposed','source_turn_id':reply['source_turn_id'],'evidence_ids':p['evidence_ids'],'entity_ids':p.get('entity_ids',[])}
    if action=='handoff':return 'loomline_handoff',{key:(reply['source_turn_id'] if key=='source_turn_id' else p[key]) for key in ('to_agent_id','description','related_memory_ids','content','source_turn_id','evidence_ids','procedure_id','consulted_steps')}
    if action=='challenge':return 'loomline_challenge',{'memory_id':p['memory_id'],'evidence_id':p['evidence_ids'][0],'reason':p['content'],'expected_version':p['expected_version']}
    raise ValueError('Unsupported tool action')
