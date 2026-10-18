"""Only public HTTP SDK and standard MCP clients. Never import the backend."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
import pytest
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

class Gateway:
    def __init__(self,log):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}';self.port=port;self.log=log;self.process=None
    def start(self):
        self.process=subprocess.Popen([os.environ['LOOM_TEST_BACKEND_PYTHON'],'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',str(self.port),'--workers','1','--no-access-log'],stdout=self.log,stderr=self.log)
        for _ in range(100):
            if self.process.poll() is not None:raise RuntimeError('Owned test gateway exited; inspect redacted gateway log')
            try:
                if httpx.get(self.url+'/health',timeout=1).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise RuntimeError('Owned test gateway startup timeout')
    def stop(self):
        if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=10)

@pytest.fixture(scope='session')
def gateway():
    assert os.environ.get('LOOM_GRAPH_NAMESPACE','').startswith('test_'),'Run with python -m scripts.mcp_verify; never run against user graphs'
    folder=Path(os.environ['LOOM_MCP_REPORT']).parent
    with (folder/'gateway.log').open('w') as log:
        gateway=Gateway(log);gateway.start()
        try:yield gateway
        finally:gateway.stop()

@pytest.fixture(scope='session')
def tokens():return json.loads(Path(os.environ['LOOM_TOKEN_FILE']).read_text())

@pytest.fixture(scope='session')
def profile_factory(gateway,tokens):
    folder=Path(os.environ['LOOM_TOKEN_FILE']).parent/'mcp_profiles';folder.mkdir(mode=0o700)
    def create(identity='alpha:coordinator',task='incident_42',approval=False,token=None):
        target=folder/(str(len(list(folder.iterdir())))+'.json');token_path=target.with_suffix('.token')
        token_path.write_text(token or tokens[identity]);token_path.chmod(0o600)
        target.write_text(json.dumps({'base_url':gateway.url,'task_id':task,'token_file':str(token_path),'allow_procedure_approval':approval,'timeout_seconds':2}));target.chmod(0o600)
        return target
    try:yield create
    finally:
        for file in folder.iterdir():file.unlink()
        folder.rmdir()

@asynccontextmanager
async def connect(profile):
    params=StdioServerParameters(command=sys.executable,args=['-m','loomline_mcp','--profile',str(profile)])
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=15) as client:
            await client.initialize();yield client

async def call(client,name,**arguments):
    result=await client.call_tool('loomline_'+name,arguments)
    assert not result.is_error, 'MCP_TOOL_ERROR: '+str([c.text for c in result.content if hasattr(c,'text')])
    assert result.structured_content['untrusted_data'] is True
    return result.structured_content['data']

async def denied(client,name,code=None,**arguments):
    result=await client.call_tool('loomline_'+name,arguments);assert result.is_error
    text=' '.join(getattr(c,'text','') for c in result.content)
    if code:assert code in text,text
    return text
