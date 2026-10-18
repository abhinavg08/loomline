"""Real gateway with sanitized DB diagnostics ONLY for owned synthetic tests."""
import json
import logging
import os
from pathlib import Path
from fastapi.responses import JSONResponse
from redis.exceptions import ResponseError
from backend.app.main import app,database_error
from backend.app.config import settings

if not settings.loom_graph_namespace.startswith('test_'):raise RuntimeError('Diagnostic gateway requires owned disposable test namespace')

@app.exception_handler(ResponseError)
async def diagnostic_error(request,exc):
    # The caller supplies only synthetic fixture data. Never log query arguments,
    # authorization headers, URLs, request/response bodies or arbitrary user graphs.
    message=str(exc)
    secrets=[settings.falkordb_password,settings.nvidia_api_key,settings.nvidia_investigator_api_key,settings.nvidia_verifier_api_key,settings.nvidia_coordinator_api_key]
    file=Path(os.environ['LOOM_TOKEN_FILE']);secrets.extend(json.loads(file.read_text()).values())
    if any(secret and secret in message for secret in secrets):message='REDACTED_DATABASE_ERROR'
    message=' '.join(message.split())[:512]
    logging.getLogger('loomline.owned_test').warning('Owned synthetic database error: %s',message)
    return await database_error(request,exc)
