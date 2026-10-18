"""Read our documented stdio configuration for independent protocol verification.

This is deliberately NOT a general-purpose launcher for arbitrary MCP programs.
"""
import json
from pathlib import Path
import re
import shutil
import sys
from mcp import StdioServerParameters

def load_stdio_config(path,server_name='loomline',*,allow_local_docker=False):
    path=Path(path).resolve()
    if path.stat().st_size>16384:raise ValueError('CLIENT_CONFIG_TOO_LARGE')
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict) or set(value)!={'mcpServers'} or not isinstance(value['mcpServers'],dict):raise ValueError('INVALID_MCP_SERVERS_CONFIG')
    entry=value['mcpServers'].get(server_name)
    if not isinstance(entry,dict) or set(entry)-{'command','args','cwd','env','disabled','disabledTools'}:raise ValueError('INVALID_STDIO_ENTRY')
    if entry.get('disabled') or entry.get('disabledTools'):raise ValueError('PREFLIGHT_REQUIRES_ALL_LOOMLINE_TOOLS')
    command_text=entry.get('command','')
    if not isinstance(command_text,str):raise ValueError('INVALID_COMMAND')
    if command_text=='docker' or Path(command_text).name.lower() in ('docker','docker.exe'):
        if not allow_local_docker:raise ValueError('LOCAL_DOCKER_REQUIRES_EXPLICIT_TRUST')
        docker=shutil.which('docker')
        if not docker:raise ValueError('DOCKER_EXECUTABLE_NOT_FOUND')
        if command_text!='docker' and Path(command_text).resolve()!=Path(docker).resolve():raise ValueError('USE_DOCKER_FROM_TRUSTED_PATH')
        args=entry.get('args',[]);env=entry.get('env',{})
        if not isinstance(args,list) or len(args)!=12 or not all(isinstance(value,str) for value in args):raise ValueError('UNSUPPORTED_DOCKER_ARGUMENTS')
        root=Path(args[2])
        expected=['compose','--project-directory',args[2],'--profile','app','run','--rm','--no-deps','-T','mcp','--profile','/run/loomline/docker.profile.json']
        if args!=expected or not root.is_absolute() or not root.is_dir() or not (root/'docker-compose.yml').is_file():raise ValueError('TRUSTED_CHECKOUT_REQUIRED')
        if not isinstance(env,dict) or any(not isinstance(value,str) for value in env.values()) or set(env)-{'LOOM_MCP_DIRECTORY','PYTHONUNBUFFERED'} or not re.fullmatch(r'\./\.secrets/connections/[a-z][a-z0-9_-]{0,59}',env.get('LOOM_MCP_DIRECTORY','')) or env.get('PYTHONUNBUFFERED','1')!='1':raise ValueError('UNSUPPORTED_DOCKER_ENVIRONMENT')
        if entry.get('cwd') and (not Path(entry['cwd']).is_absolute() or Path(entry['cwd']).resolve()!=root.resolve()):raise ValueError('CHECKOUT_WORKING_DIRECTORY_REQUIRED')
        # Compose runs code from this checkout: the caller must explicitly trust
        # that local source. This narrow parser is not a sandbox for a malicious
        # compose.yml or Dockerfile, and never accepts arbitrary Docker flags.
        return StdioServerParameters(command=str(Path(docker).resolve()),args=args,cwd=str(root),env=env)
    command=Path(command_text)
    # Do not execute arbitrary paths/commands from an untrusted JSON document.
    if not command.is_absolute() or command.resolve()!=Path(sys.executable).resolve():raise ValueError('USE_CONFIGURED_LOOMLINE_PYTHON_FOR_PREFLIGHT')
    args=entry.get('args',[]);env=entry.get('env',{})
    if args!=['-m','loomline_mcp'] or not isinstance(env,dict) or set(env)-{'LOOM_MCP_PROFILE','PYTHONUNBUFFERED'}:raise ValueError('UNSUPPORTED_LAUNCHER_ARGUMENTS')
    if not isinstance(env.get('LOOM_MCP_PROFILE'),str) or not Path(env['LOOM_MCP_PROFILE']).is_absolute():raise ValueError('ABSOLUTE_PRIVATE_PROFILE_REQUIRED')
    if any(not isinstance(v,str) for v in env.values()):raise ValueError('INVALID_ENVIRONMENT')
    cwd=Path(entry.get('cwd',''))
    if not cwd.is_absolute() or not cwd.is_dir():raise ValueError('ABSOLUTE_WORKING_DIRECTORY_REQUIRED')
    return StdioServerParameters(command=str(command),args=args,cwd=str(cwd),env=env)
