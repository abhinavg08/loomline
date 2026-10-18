from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from .common import plan

class State(TypedDict,total=False):
    goal:str
    recalled_ids:list[str]
    reply:dict
    result:dict
    stages:list[str]

def workflow(client,task_id,session_id,*,offline=False):
    def recall(state):
        ctx=client.get_context(task_id)
        return {'recalled_ids':[m['id'] for m in [*ctx['episodic'],*ctx['semantic']]],'stages':['recall']}
    def analyze(state):return {'reply':dict(plan(client,task_id,session_id,'verifier',state['goal'],offline)),'stages':[*state['stages'],'analyze']}
    def publish(state):
        p=state['reply']['proposal'];method=client.challenge if p['action']=='challenge' else client.support
        result=method(task_id,p['memory_id'],evidence_id=p['evidence_ids'][0],reason=p['content'],expected_version=p['expected_version'])
        client.record_turn(session_id,'tool','Applied '+p['action']+' '+result.event_id,tool_name='loomline_'+p['action'])
        return {'result':dict(result),'stages':[*state['stages'],'publish_'+p['action']]}
    graph=StateGraph(State);graph.add_node('recall',recall);graph.add_node('analyze',analyze);graph.add_node('publish',publish)
    graph.add_edge(START,'recall');graph.add_edge('recall','analyze');graph.add_edge('analyze','publish');graph.add_edge('publish',END)
    return graph.compile()
