import argparse
import asyncio
import json
import logging
import os
import sys
from loomline import AsyncLoomlineClient,LoomlineError
from .config import load_profile
from .server import build_server

def safe_code(exc):
    if isinstance(exc,LoomlineError):return exc.code
    if isinstance(exc,BaseExceptionGroup):
        for child in exc.exceptions:
            code=safe_code(child)
            if code not in ('EXCEPTIONGROUP','BASEEXCEPTIONGROUP'):return code
    if isinstance(exc,ValueError) and str(exc).isupper() and str(exc).replace('_','').isalnum():return str(exc)
    return type(exc).__name__.upper()

async def doctor(profile,token):
    async with AsyncLoomlineClient(profile.base_url,token=token,timeout=profile.timeout_seconds,max_attempts=1) as c:
        health=await c.health();identity=await c.whoami();await c.get_context(profile.task_id,limit=1);capabilities=await c.capabilities()
        return {'status':'PASS','checks':['gateway health','credential authentication','fixed task authorization','contract discovery'],'identity':dict(identity),'task_id':profile.task_id,'schema_ready':health.get('schema_ready'),'contract':capabilities.get('contract_version'),'transport':'local stdio','mcp_protocol':'Run independent protocol preflight; doctor does not initialize a client','owner_codex_cli':'PENDING_OWNER_VERIFICATION','owner_claude_cli':'PENDING_OWNER_VERIFICATION','credentials_printed':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',choices=['serve','doctor'],default='serve');parser.add_argument('--profile',default=os.environ.get('LOOM_MCP_PROFILE'));args=parser.parse_args()
    logging.basicConfig(stream=sys.stderr,level=logging.ERROR)
    try:
        if not args.profile:raise ValueError('PROFILE_REQUIRED')
        profile,token=load_profile(args.profile)
        if args.command=='doctor':print(json.dumps(asyncio.run(doctor(profile,token)),indent=2))
        else:build_server(profile,token).run(transport='stdio')
    except (KeyboardInterrupt,BrokenPipeError):return
    except Exception as exc:
        code=safe_code(exc)
        print(json.dumps({'status':'FAIL','code':code,'guidance':'Check private profile/token permissions, Python MCP environment, gateway URL/health and task membership. No coding CLI was inspected.'}),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
