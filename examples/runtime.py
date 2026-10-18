"""Example-only explicit local credential loading. The core SDK never does this."""
import json
import os
from pathlib import Path
from loomline import LoomlineClient

def client(framework):
    value=os.environ.get('LOOM_AGENT_TOKEN')
    if not value:
        path=Path(os.environ.get('LOOM_TOKEN_FILE','.secrets/platform_tokens.json'))
        value=json.loads(path.read_text())[framework]
    return LoomlineClient(os.environ.get('LOOM_URL','http://127.0.0.1:8000'),token=value,timeout=120,max_attempts=2)

def telemetry_off():
    for name,value in {'PYTHON_DOTENV_DISABLED':'1','OTEL_SDK_DISABLED':'true','CREWAI_TELEMETRY_ENABLED':'false','CREWAI_DISABLE_TELEMETRY':'true','LANGCHAIN_TRACING_V2':'false','LANGSMITH_TRACING':'false','CREWAI_STORAGE_DIR':str(Path('artifacts/platform/crewai-local').resolve())}.items():os.environ[name]=value
