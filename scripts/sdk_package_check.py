"""Build an installable wheel; prove core-only import from a fresh isolated venv."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from .release_safety import ROOT,sensitive,configured_secrets

def main():
    folder=ROOT/'artifacts/platform'/('sdk-clean-'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'PYTHON_DOTENV_DISABLED':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'};env.pop('PYTHONPATH',None)
    def run(command):
        with (folder/'install.log').open('a') as log:subprocess.run(command,cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
    wheels=folder/'wheels';wheels.mkdir()
    run([sys.executable,'-m','pip','wheel','--no-deps','--wheel-dir',str(wheels),str(ROOT/'packages/loomline-sdk')])
    wheel=next(wheels.glob('loomline_sdk-*.whl'))
    import zipfile
    with zipfile.ZipFile(wheel) as archive:
        assert all(not sensitive(archive.read(n),configured_secrets()) for n in archive.namelist())
        assert 'loomline/py.typed' in archive.namelist()
    run([sys.executable,'-m','venv',str(folder/'venv')])
    executable=folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    run([str(executable),'-m','pip','install',str(wheel)])
    proof="import json,importlib.util; from importlib.metadata import version; from loomline import LoomlineClient,AsyncLoomlineClient; absent={n:importlib.util.find_spec(n) is None for n in ('backend','falkordb','redis','langchain','langgraph','crewai')}; assert all(absent.values()); print(json.dumps({'sdk':version('loomline-sdk'),'absent':absent}))"
    result=json.loads(subprocess.check_output([str(executable),'-c',proof],cwd=folder,env=env,text=True))
    run([str(executable),'-m','pip','check'])
    report={'status':'PASS','sdk':result,'wheel':str(wheel),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'core_only_clean_environment':True,'wheel_secret_scan':'PASS','typed_marker_present':True,'pip_check':'PASS'}
    (ROOT/'artifacts/platform/sdk-package.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
