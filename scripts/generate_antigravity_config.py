"""Stage owner-readable configuration only; never touch a client config directory."""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def configuration(profile,python,cwd):
    profile=Path(profile).resolve();python=Path(python).resolve();cwd=Path(cwd).resolve()
    if not profile.is_file() or not python.is_file() or not cwd.is_dir():raise ValueError('PROFILE_PYTHON_OR_CWD_NOT_FOUND')
    return {'mcpServers':{'loomline':{'command':str(python),'args':['-m','loomline_mcp'],'cwd':str(cwd),'env':{'LOOM_MCP_PROFILE':str(profile),'PYTHONUNBUFFERED':'1'}}}}

def generate(profile,python,cwd,output):
    target=Path(output).resolve()
    if not any(target.is_relative_to(ROOT/d) for d in ('artifacts/mcp','.secrets/mcp')):raise ValueError('STAGING_DIRECTORY_REQUIRED')
    if target.exists():raise ValueError('REFUSING_EXISTING_CONFIG')
    value=configuration(profile,python,cwd)
    target.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as stream:json.dump(value,stream,indent=2)
    return {'status':'STAGED','config_file':str(target),'client_configuration_modified':False,'credentials_embedded':False,'owner_antigravity_ide':'PENDING_OWNER_VERIFICATION','owner_antigravity_cli':'PENDING_OWNER_VERIFICATION'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--python',default=str(ROOT/('.venv-mcp/Scripts/python.exe' if os.name=='nt' else '.venv-mcp/bin/python')));p.add_argument('--cwd',default=str(ROOT));p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(generate(a.profile,a.python,a.cwd,a.output),indent=2))

if __name__=='__main__':main()
