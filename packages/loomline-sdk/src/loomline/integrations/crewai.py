"""CrewAI Agent/Task/Crew with real tool execution and shared gateway planning."""
import json
from typing import Any
from pydantic import BaseModel,create_model,Field
from crewai import Agent,Task,Crew,BaseLLM,Process
from crewai.tools import BaseTool
from .common import actions,plan,tool_action

def memory_tools(client,task_id,session_id,executed):
    import inspect
    from typing import get_type_hints
    tools=[]
    for name,fn in actions(client,task_id,session_id,executed).items():
        hints=get_type_hints(fn)
        fields={k:(hints.get(k,Any),... if p.default is inspect.Parameter.empty else p.default) for k,p in inspect.signature(fn).parameters.items()}
        schema=create_model(name+'_args',**fields)
        class SDKTool(BaseTool):
            operation:Any=Field(exclude=True,repr=False)
            def _run(self,**kwargs):return json.dumps(self.operation(**kwargs))
        tools.append(SDKTool(name=name,description=fn.__doc__ or name,args_schema=schema,operation=fn))
    return tools

class GatewayCrewLLM(BaseLLM):
    def __init__(self,client,task_id,session_id,goal,offline):
        super().__init__(model='loomline/shared-nvidia-gateway',temperature=1)
        self.client=client;self.task_id=task_id;self.session_id=session_id;self.goal=goal;self.offline=offline;self.phase=0;self.reply={}
    def supports_function_calling(self):return False
    def supports_stop_words(self):return False
    def call(self,messages,tools=None,callbacks=None,available_functions=None,**kwargs):
        self.phase+=1
        if self.phase==1:return 'Thought: Select authorized recall.\nAction: loomline_recall\nAction Input: {}'
        if self.phase==2:
            self.reply=dict(plan(self.client,self.task_id,self.session_id,'coordinator',self.goal,self.offline))
            name,args=tool_action(self.reply)
            return 'Thought: Execute the validated evidence-linked action.\nAction: '+name+'\nAction Input: '+json.dumps(args)
        return 'Final Answer: Completed the authorized shared-memory handoff. Inspect the actual tool result and source IDs.'

def run_crew(client,task_id,session_id,goal,*,offline=False):
    executed=[];llm=GatewayCrewLLM(client,task_id,session_id,goal,offline)
    agent=Agent(role='Evidence coordinator',goal=goal,backstory='Use approved shared procedures, preserve uncertainty and hand off unfinished work.',llm=llm,tools=memory_tools(client,task_id,session_id,executed),allow_delegation=False,verbose=False,max_iter=5)
    task=Task(description=goal,expected_output='Persisted evidence-linked decision and handoff IDs from Loomline tools.',agent=agent)
    crew=Crew(agents=[agent],tasks=[task],process=Process.sequential,verbose=False,memory=False,cache=False,tracing=False)
    result=crew.kickoff()
    if 'loomline_handoff' not in executed:raise RuntimeError('Crew did not successfully execute the handoff tool')
    return {'runtime':'crewai.Crew.kickoff','executed_tools':executed,'model_reply':llm.reply,'final_output':str(result)}
