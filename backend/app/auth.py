import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from fastapi import Header, Request
from .config import ROOT, TENANTS, settings
from .errors import DomainError


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    agent_id: str
    role: str
    allowed_task_ids: tuple[str,...] | None = None
    can_approve_procedures: bool = True


class TokenAuthenticator:
    """Replaceable local-demo authentication boundary. No HTTP-supplied identity fields."""
    def authenticate(self, token: str) -> TenantContext:
        path = Path(settings.loom_auth_file)
        if not path.is_absolute():
            path = ROOT / path
        records = json.loads(path.read_text())
        principal = records.get(hashlib.sha256(token.encode()).hexdigest())
        if not principal or principal['tenant_id'] not in TENANTS:
            raise DomainError(401, 'UNAUTHENTICATED')
        principal=dict(principal)
        if principal.get('allowed_task_ids') is not None:
            principal['allowed_task_ids']=tuple(principal['allowed_task_ids'])
        if principal.get('role') == 'viewer':
            principal['can_approve_procedures'] = False
        return TenantContext(**principal)


async def authenticated(request: Request, authorization: str = Header(default='')) -> TenantContext:
    if not authorization.startswith('Bearer '):
        raise DomainError(401, 'UNAUTHENTICATED')
    principal = TokenAuthenticator().authenticate(authorization[7:])
    # Enforce read-only access at the common dependency, before body validation
    # or any endpoint can allocate a session, mutate the graph, or call a model.
    if principal.role == 'viewer' and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        raise DomainError(403, 'READ_ONLY_IDENTITY')
    return principal
