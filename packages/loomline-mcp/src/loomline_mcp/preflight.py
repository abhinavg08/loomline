"""Independent standard MCP client, never a coding CLI. Only safe metadata calls."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def check(profile=None,config=None,allow_local_docker=False):
    if config:
        from .client_config import load_stdio_config
        params=load_stdio_config(config,allow_local_docker=allow_local_docker)
    else:params=StdioServerParameters(command=sys.executable,args=['-m','loomline_mcp','--profile',str(Path(profile).resolve())])
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            initialized=await client.initialize()
            tools=await client.list_tools()
            result=await client.call_tool('loomline_whoami',{})
            if result.is_error:raise RuntimeError('MCP_IDENTITY_CALL_FAILED')
            identity=result.structured_content['data']
            resource=await client.read_resource('loomline://contract')
            assert json.loads(resource.contents[0].text)['storage'].startswith('FalkorDB')
            return {'status':'PASS','evidence_type':'independent MCP protocol test-client','configuration':'Antigravity-compatible mcpServers stdio' if config else 'private Loomline profile','protocol_version':initialized.protocol_version,'server_version':initialized.server_info.version,'tools':[t.name for t in tools.tools],'identity':identity['identity'],'task_id':identity['fixed_task_id'],'session_id':identity['session_id'],'stdio_stdout':'valid MCP framing','owner_codex_cli':'PENDING_OWNER_VERIFICATION','owner_claude_cli':'PENDING_OWNER_VERIFICATION','owner_antigravity_ide':'PENDING_OWNER_VERIFICATION','owner_antigravity_cli':'PENDING_OWNER_VERIFICATION','real_two_cli_exchange':'PENDING_OWNER_VERIFICATION','real_three_client_exchange':'PENDING_OWNER_VERIFICATION'}

def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--profile');group.add_argument('--config');parser.add_argument('--allow-local-docker',action='store_true',help='Trust the reviewed local checkout in an exact onboard-generated Docker configuration');a=parser.parse_args()
    if a.allow_local_docker and not a.config:parser.error('--allow-local-docker requires --config')
    try:print(json.dumps(asyncio.run(check(a.profile,a.config,a.allow_local_docker)),indent=2))
    except Exception:
        print(json.dumps({'status':'FAIL','code':'MCP_PREFLIGHT_FAILED','guidance':'Run doctor with the same interpreter/profile; inspect redacted stderr. No coding CLI was contacted.'}),file=sys.stderr);raise SystemExit(1) from None

if __name__=='__main__':main()
