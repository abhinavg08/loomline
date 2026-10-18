from typing import Literal, Any
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .errors import ValidationError

class Record(dict):
    """JSON-compatible result with attribute access and wire-preserving equality."""
    def __init__(self,value:dict[str,Any],status_code:int=200):
        if not isinstance(value,dict):raise ValidationError('INVALID_SERVER_RESPONSE')
        super().__init__(value);self._status_code=status_code
    def __getattr__(self,name):
        if name=='memory_class':name='class'
        if name=='id' and 'id' not in self:
            for key in ('memory_id','session_id','turn_id','handoff_id','event_id'):
                if key in self:return self[key]
        try:return self[name]
        except KeyError:raise AttributeError(name) from None
    @property
    def outcome(self):return 'CREATED' if self._status_code==201 else 'REPLAYED'
    def model_dump(self):return dict(self)

class MemoryRecord(BaseModel):
    model_config=ConfigDict(extra='allow',populate_by_name=True,frozen=True,hide_input_in_errors=True)
    id:str
    reference:str
    task_id:str
    memory_class:Literal['episodic','semantic','procedural']=Field(alias='class')
    assertion_type:Literal['episode','observation','hypothesis','decision','procedure']
    status:Literal['active','proposed','disputed','retired','superseded']
    content:str
    created_by:str
    source_turn_id:str
    session_id:str|None=None
    version:int
    support:list[dict]=Field(default_factory=list)
    challenges:list[dict]=Field(default_factory=list)

class MemoryInput(BaseModel):
    model_config=ConfigDict(extra='forbid',populate_by_name=True,hide_input_in_errors=True)
    operation_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    session_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    source_turn_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    memory_class:Literal['episodic','semantic','procedural']=Field(alias='class')
    assertion_type:Literal['episode','observation','hypothesis','decision','procedure']
    status:Literal['active','proposed']
    content:str=Field(min_length=1,max_length=4000)
    evidence_ids:list[str]=Field(default_factory=list,max_length=10)
    entity_ids:list[str]=Field(default_factory=list,max_length=10)
    steps:list[str]|None=Field(default=None,max_length=20)
    supersedes_id:str|None=None
    @model_validator(mode='after')
    def matrix(self):
        valid={'episodic':('episode','observation'),'semantic':('observation','hypothesis','decision'),'procedural':('procedure',)}
        if self.assertion_type not in valid[self.memory_class]:raise ValueError('Invalid memory assertion')
        if self.status!=('proposed' if self.assertion_type in ('hypothesis','procedure') else 'active'):raise ValueError('Invalid initial status')
        if self.memory_class=='procedural' and (not self.steps or any(not s.strip() or len(s)>500 for s in self.steps)):raise ValueError('Procedure requires steps')
        if self.memory_class!='procedural' and self.steps is not None:raise ValueError('Steps only apply to procedures')
        return self

class ChangeBatch(Record):
    def __init__(self,value):super().__init__(value);self.acknowledged=False
    def ack(self):self.acknowledged=True;return self.get('next_cursor')
