"""Clean Linux non-editable install/protocol check; no coding clients involved."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
from .release_safety import ROOT,configured_secrets,sensitive

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True);parser.add_argument('--image',default='loomline-mcp:0.1.0');parser.add_argument('--network',default='loomline_default');a=parser.parse_args();profile=Path(a.profile).resolve()
    p=json.loads(profile.read_text());token=Path(p['token_file'])
    if not token.is_absolute():token=profile.parent/token
    folder=ROOT/'artifacts/mcp';folder.mkdir(parents=True,exist_ok=True)
    derived=profile.parent/('container_'+uuid.uuid4().hex[:8]+'.json')
    derived.write_text(json.dumps({**p,'base_url':'http://gateway:8000','token_file':'/run/loomline-check/agent.token'}))
    # Windows Docker bind mounts expose synthetic POSIX modes. Stage a private,
    # non-root-owned, mode-600 ephemeral copy INSIDE this disposable container.
    # Neither host credential nor its permissions are modified.
    code="""import importlib.util,json,pathlib,subprocess,sys,os
assert importlib.util.find_spec('backend') is None
assert importlib.util.find_spec('crewai') is None
assert importlib.util.find_spec('falkordb') is None
import tempfile
root=pathlib.Path(tempfile.mkdtemp(prefix='loomline-check-'))
root.chmod(0o700)
token=root/'agent.token';token.write_bytes(pathlib.Path('/mounted/agent.token').read_bytes());token.chmod(0o600)
profile=root/'profile.json';data=json.loads(pathlib.Path('/mounted/profile.json').read_text());data['token_file']=str(token);profile.write_text(json.dumps(data));profile.chmod(0o600)
if os.geteuid()==0:
    for path in (root,token,profile):os.chown(path,10001,10001)
    os.setgroups([]);os.setgid(10001);os.setuid(10001)
assert os.geteuid()==10001
subprocess.run([sys.executable,'-m','pip','check'],check=True)
subprocess.run([sys.executable,'-m','loomline_mcp.preflight','--profile',str(profile)],check=True)
config=root/'mcp_config.json';config.write_text(json.dumps({'mcpServers':{'loomline':{'command':sys.executable,'args':['-m','loomline_mcp'],'cwd':str(root),'env':{'LOOM_MCP_PROFILE':str(profile),'PYTHONUNBUFFERED':'1'}}}}));config.chmod(0o600)
subprocess.run([sys.executable,'-m','loomline_mcp.preflight','--config',str(config)],check=True)
"""
    try:
        command=['docker','run','--rm','--user','0:0','--network',a.network,'--mount',f'type=bind,source={derived},target=/mounted/profile.json,readonly','--mount',f'type=bind,source={token.resolve()},target=/mounted/agent.token,readonly','--entrypoint','python',a.image,'-c',code]
        result=subprocess.run(command,capture_output=True,text=True,timeout=90)
        output=result.stdout+result.stderr
        if sensitive(output.encode(),configured_secrets()):raise RuntimeError('Package check output contains credential; log suppressed')
        (folder/'clean-package.log').write_text(output)
        report={'status':'PASS' if result.returncode==0 else 'FAIL','runtime':'clean non-root Linux Python 3.12.10; locked MCP 2.2.0','checks':['non-editable SDK and MCP wheel installation','pip check','no backend/FalkorDB/framework imports','real standard stdio client initialization/discovery/authenticated task call against existing gateway'],'credential_handling':'trusted root staging of one read-only credential to ephemeral mode-600 copy; drop to uid/gid 10001 BEFORE pip/MCP; no host key changes','owner_cli_verification':'PENDING_OWNER_VERIFICATION'}
        (folder/'package.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
        if result.returncode:raise SystemExit(result.returncode)
    finally:derived.unlink()

if __name__=='__main__':main()
