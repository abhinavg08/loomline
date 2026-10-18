class DomainError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


MEMORY_REFERENCE_GUIDANCE = ('Use the complete reference returned by remember/recall: '
    'loom://task/<task_id>/memory/<memory_id>. Bare IDs and evidence/session/turn URIs '
    'are not memory references. Read linked evidence through a memory trace.')


def parse_memory_reference(reference):
    import re
    match = re.fullmatch(r'loom://task/([A-Za-z0-9_-]{1,128})/memory/([A-Za-z0-9_-]{1,128})', reference)
    if not match:raise DomainError(400, 'INVALID_MEMORY_REFERENCE')
    return match.groups()


def require(condition, status=404, code='NOT_FOUND'):
    if not condition:
        raise DomainError(status, code)
