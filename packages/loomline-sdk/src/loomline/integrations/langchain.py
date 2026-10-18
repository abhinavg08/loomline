"""Genuine LangChain tools and create_agent, with a gateway-backed planner model.

Provider JSON proposals are validated by Loomline then mapped to LangChain tool
calls. This does not claim native NVIDIA function-calling compatibility.
"""
from typing import Any
from pydantic import Field
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage,ToolMessage
from langchain_core.outputs import ChatGeneration,ChatResult
from langchain_core.tools import StructuredTool
from .common import actions,plan,tool_action


def memory_tools(client,task_id,session_id,executed=None):
    return [StructuredTool.from_function(fn,name=name) for name,fn in actions(client,task_id,session_id,executed if executed is not None else []).items()]


class GatewayPlannerModel(BaseChatModel):
    client:Any=Field(exclude=True,repr=False)
    task_id:str
    session_id:str
    offline:bool=False
    last_reply:dict=Field(default_factory=dict,exclude=True)
    @property
    def _llm_type(self):return 'loomline-nvidia-validated-planner'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        if any(isinstance(m,ToolMessage) for m in messages):message=AIMessage(content='Authorized memory tool result recorded; inspect the persisted source and evidence.')
        else:
            goal=str(messages[-1].content)[:500]
            reply=plan(self.client,self.task_id,self.session_id,'investigator',goal,self.offline)
            self.last_reply=dict(reply);name,args=tool_action(reply)
            message=AIMessage(content='',tool_calls=[{'id':'loomline_action_1','name':name,'args':args}])
        return ChatResult(generations=[ChatGeneration(message=message)])


def run_agent(client,task_id,session_id,goal,*,offline=False):
    executed=[];tools=memory_tools(client,task_id,session_id,executed)
    # Recall is a genuine typed LangChain tool invocation; no private state relay.
    next(t for t in tools if t.name=='loomline_recall').invoke({})
    model=GatewayPlannerModel(client=client,task_id=task_id,session_id=session_id,offline=offline)
    agent=create_agent(model,tools=tools)
    result=agent.invoke({'messages':[{'role':'user','content':goal}]},config={'recursion_limit':6})
    tool_results=[m.content for m in result['messages'] if isinstance(m,ToolMessage)]
    if 'loomline_remember' not in executed:raise RuntimeError('LangChain did not successfully commit the planned memory tool action')
    return {'runtime':'langchain.create_agent','executed_tools':executed,'model_reply':model.last_reply,'tool_results':tool_results}
