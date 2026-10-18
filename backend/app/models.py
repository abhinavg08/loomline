from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
import re

ID = r'^[A-Za-z0-9_-]{1,128}$'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    @field_validator('*')
    @classmethod
    def nonblank(cls,value):
        if isinstance(value,str) and not value.strip():raise ValueError('Blank strings are not valid')
        return value


class Intent(Strict):
    operation_id: str = Field(pattern=ID)

    @field_validator('operation_id')
    @classmethod
    def safe_operation_id(cls,value):
        from .config import settings
        secrets=(settings.falkordb_password,settings.nvidia_api_key,settings.nvidia_investigator_api_key,settings.nvidia_verifier_api_key,settings.nvidia_coordinator_api_key)
        if value.startswith('nvapi-') or value in (s for s in secrets if s):
            raise ValueError('Credential is not an operation identifier')
        return value


class SessionRequest(Intent):
    pass


class TurnRequest(Intent):
    role: Literal['user', 'assistant', 'tool']
    content: str = Field(min_length=1, max_length=8000)
    tool_name: str | None = Field(default=None, max_length=100)
    tool_call_id: str | None = Field(default=None, max_length=128)

    @field_validator('content')
    @classmethod
    def redact(cls, value):
        from .config import settings
        for secret in (settings.falkordb_password,settings.nvidia_api_key,settings.nvidia_investigator_api_key,settings.nvidia_verifier_api_key,settings.nvidia_coordinator_api_key):
            if secret:value=value.replace(secret,'[REDACTED]')
        value=re.sub(r'(?<![\w-])[A-Za-z0-9_-]{43}(?![\w-])','[REDACTED]',value)
        return re.sub(r'(?i)(nvapi-[\w-]+|Bearer\s+[\w.-]+|(?:api[_-]?key|password|token)\s*[:=]\s*[^\s,;]+)', '[REDACTED]', value)

    @field_validator('tool_name','tool_call_id')
    @classmethod
    def safe_metadata(cls,value):return cls.redact(value) if value is not None else None


class MemoryRequest(Intent):
    session_id: str = Field(pattern=ID)
    source_turn_id: str = Field(pattern=ID)
    memory_class: Literal['episodic', 'semantic', 'procedural'] = Field(alias='class')
    assertion_type: Literal['episode', 'observation', 'hypothesis', 'decision', 'procedure']
    status: Literal['active', 'proposed']
    content: str = Field(min_length=1, max_length=4000)
    steps: list[str] | None = Field(default=None, max_length=20)
    entity_ids: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    supersedes_id: str | None = Field(default=None, pattern=ID)

    _redact = field_validator('content')(TurnRequest.redact.__func__)

    @model_validator(mode='after')
    def matrix(self):
        allowed = {'episodic': {'episode', 'observation'}, 'semantic': {'observation', 'hypothesis', 'decision'}, 'procedural': {'procedure'}}
        if self.assertion_type not in allowed[self.memory_class]:
            raise ValueError('Invalid memory assertion')
        initial = 'proposed' if self.assertion_type in ('hypothesis', 'procedure') else 'active'
        if self.status != initial:
            raise ValueError('Invalid initial status')
        if self.memory_class == 'procedural':
            if not self.steps or any(not s.strip() or len(s) > 500 for s in self.steps):
                raise ValueError('Procedure requires nonempty bounded steps')
            self.steps = [TurnRequest.redact(s) for s in self.steps]
        elif self.steps is not None:
            raise ValueError('Steps only allowed on procedures')
        for ids in (self.entity_ids, self.evidence_ids):
            if len(set(ids)) != len(ids) or any(not re.fullmatch(ID, s) for s in ids):
                raise ValueError('Invalid or duplicate reference')
        return self


class EvidenceRequest(Intent):
    source_type: Literal['synthetic', 'tool', 'document']
    source_ref: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=4000)
    observed_at: datetime
    _redact = field_validator('content', 'source_ref')(TurnRequest.redact.__func__)

    @field_validator('observed_at')
    @classmethod
    def timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError('Timezone required')
        return value


class ChallengeRequest(Intent):
    evidence_id: str = Field(pattern=ID)
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)
    _redact = field_validator('reason')(TurnRequest.redact.__func__)


class StatusRequest(Intent):
    expected_version: int = Field(ge=1)
    status: Literal['active', 'retired', 'superseded']
    reason: str = Field(min_length=1, max_length=1000)
    _redact = field_validator('reason')(TurnRequest.redact.__func__)


class HandoffRequest(Intent):
    to_agent_id: str = Field(pattern=ID)
    description: str = Field(min_length=1, max_length=2000)
    related_memory_ids: list[str] = Field(default_factory=list, max_length=10)
    _redact = field_validator('description')(TurnRequest.redact.__func__)


class HandoffStatusRequest(Intent):
    expected_version: int = Field(ge=1)
    status: Literal['accepted', 'done', 'cancelled']


class SubscriptionRequest(Intent):
    enabled: bool = True


class InferenceRequest(Intent):
    task_id: str = Field(pattern=ID)
    session_id: str = Field(pattern=ID)
