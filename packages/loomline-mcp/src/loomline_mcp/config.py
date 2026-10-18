import os
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator

class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    base_url:str='http://127.0.0.1:8000'
    task_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    token_file:str=Field(repr=False)
    allow_procedure_approval:bool=False
    timeout_seconds:int=Field(default=30,ge=1,le=120)

    @field_validator('base_url')
    @classmethod
    def trusted_endpoint(cls,value):
        url=urlsplit(value)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('Invalid gateway URL')
        if url.scheme=='http' and url.hostname not in ('127.0.0.1','localhost','::1','gateway'):raise ValueError('Remote gateways require HTTPS')
        return value.rstrip('/')

def load_profile(path):
    file=Path(path).expanduser().resolve()
    if file.stat().st_size>16384:raise ValueError('PROFILE_TOO_LARGE')
    p=Profile.model_validate_json(file.read_text(encoding='utf-8-sig'))
    token_path=Path(p.token_file).expanduser()
    if not token_path.is_absolute():token_path=file.parent/token_path
    if os.name!='nt' and token_path.stat().st_mode & 0o077:raise ValueError('PRIVATE_TOKEN_PERMISSIONS_REQUIRED')
    if token_path.stat().st_size>1024:raise ValueError('INVALID_CREDENTIAL_FILE')
    token=token_path.read_text().strip()
    if not token or any(ch.isspace() for ch in token):raise ValueError('INVALID_CREDENTIAL_FILE')
    return p,token
