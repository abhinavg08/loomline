"""Reproduce source-only export using fresh secrets, project, DB volume and images.

Host Python orchestrates only stdlib operations. The application, Python packages,
Node build, agents and acceptance tests execute inside the exported Docker build.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import uuid
import zipfile
from .release_safety import ROOT,allowed,export_source,inspect_zip


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def main():
    nonce=uuid.uuid4().hex[:16]
    work=ROOT/'artifacts/release'/('fresh_'+nonce)
    archive=ROOT/'artifacts/release'/('candidate_'+nonce+'.zip')
    archive_report=export_source(archive)
    work.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        for entry in source.namelist():
            if not allowed(entry):raise RuntimeError('Unsafe source member')
        source.extractall(work)
    assert not any((work/name).exists() for name in ('.env','.secrets','.conda','frontend/node_modules'))
    subprocess.run([sys.executable,'scripts/init_local.py'],cwd=work,check=True)
    db_port,api_port=free_port(),free_port()
    while api_port==db_port:api_port=free_port()
    project='loomline-release-'+nonce
    envpath=work/'.env'
    text=envpath.read_text().replace('FALKORDB_PORT=6379','FALKORDB_PORT='+str(db_port)).replace('LOOM_API_PORT=8000','LOOM_API_PORT='+str(api_port)).replace('LOOM_GRAPH_NAMESPACE=demo','LOOM_GRAPH_NAMESPACE=release_'+nonce)
    text+='\nCOMPOSE_PROJECT_NAME='+project+'\n'
    envpath.write_text(text)
    compose=['docker','compose','--project-name',project,'--profile','app']
    report={'status':'IN_PROGRESS','workspace':str(work),'project':project,'namespace':'release_'+nonce,'database_port':db_port,'api_port':api_port,'archive':archive_report,'checks':{}}
    manifest=ROOT/'artifacts/release/fresh-manifest.json'
    manifest.write_text(json.dumps(report,indent=2))
    def run(name,command):
        log=work/'artifacts/release'/f'{name}.log';log.parent.mkdir(parents=True,exist_ok=True)
        with log.open('w') as output:
            result=subprocess.run(command,cwd=work,stdout=output,stderr=subprocess.STDOUT)
        report['checks'][name]='PASS' if result.returncode==0 else 'FAIL'
        manifest.write_text(json.dumps(report,indent=2))
        print(name+': '+report['checks'][name],flush=True)
        if result.returncode:raise RuntimeError(name+' failed; inspect private log '+str(log))
    try:
        run('compose-config',compose+['config','--quiet'])
        run('fresh-build-and-health',compose+['up','-d','--build','--wait'])
        run('acceptance',compose+['run','--rm','--build','tests'])
        run('mcp-clean-build',['docker','build','-f','Dockerfile.mcp','-t',project+'-mcp','.'])
        run('mcp-owner-setup',compose+['run','--rm','operator','python','-m','scripts.mcp_setup','--name','fresh_check','--url','http://gateway:8000'])
        mcp_profile=work/'.secrets/mcp/fresh_check/codex.profile.json'
        profile=json.loads(mcp_profile.read_text());profile['token_file']=str(work/'.secrets/mcp_fresh_check_codex.token');mcp_profile.write_text(json.dumps(profile))
        run('mcp-clean-protocol',[sys.executable,'-m','scripts.mcp_package_check','--profile',str(mcp_profile),'--image',project+'-mcp','--network',project+'_default'])
        ag_profile=work/'.secrets/mcp/fresh_check/antigravity.profile.json'
        profile=json.loads(ag_profile.read_text());profile['token_file']=str(work/'.secrets/mcp_fresh_check_antigravity.token');ag_profile.write_text(json.dumps(profile))
        run('antigravity-clean-protocol',[sys.executable,'-m','scripts.mcp_package_check','--profile',str(ag_profile),'--image',project+'-mcp','--network',project+'_default'])
        run('platform-onboarding',compose+['run','--rm','operator'])
        # auth.json is atomically replaced by the operator; refresh the file bind.
        run('gateway-auth-refresh',compose+['up','-d','--force-recreate','--no-deps','gateway','--wait'])
        run('frameworks-build',compose+['build','integrations'])
        run('frameworks-offline',compose+['run','--rm','integrations'])
        run('platform-isolated-reliability',compose+['run','--rm','tests','python','-m','scripts.platform_verify'])
        run('two-agents',compose+['run','--rm','--build','client','python','-m','agents.demo_two_agents'])
        run('offline-incident',compose+['run','--rm','client','python','-m','agents.run_incident','--offline','--pause-before-resume'])
        incident=json.loads((work/'artifacts/incident_offline.json').read_text())
        report['task_id']=incident['task_id'];report['ui_url']=incident['ui_url']
        run('gateway-restart',compose+['restart','gateway'])
        run('gateway-health-after-restart',compose+['up','-d','--wait'])
        run('fresh-session-resume',compose+['run','--rm','client','python','-m','agents.run_incident','--resume','artifacts/'+incident['task_id']+'.json'])
        run('independent-api-recovery',compose+['run','--rm','tests','python','-m','scripts.restart_recovery_check'])
        run('router-pause-for-persistence',compose+['stop','router'])
        statecmd=compose+['run','--rm','-e','LOOM_GRAPH_NAMESPACE='+report['namespace'],'tests','python','-m','scripts.release_snapshot','--release']
        run('persistence-before',statecmd+['artifacts/release/persistence-before.json'])
        old=subprocess.check_output(compose+['ps','-q','falkordb'],cwd=work,text=True).strip()
        mounts=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Mounts}}',old],text=True))
        assert any(m['Name']==project+'_graph_data' and m['Destination']=='/var/lib/falkordb/data' for m in mounts if m['Type']=='volume'), 'Unexpected volume'
        run('db-container-recreation',compose+['up','-d','--force-recreate','--no-deps','falkordb','--wait'])
        new=subprocess.check_output(compose+['ps','-q','falkordb'],cwd=work,text=True).strip()
        assert old!=new, 'Database container was not recreated'
        run('persistence-after',statecmd+['artifacts/release/persistence-after.json'])
        before=json.loads((work/'artifacts/release/persistence-before.json').read_text())
        after=json.loads((work/'artifacts/release/persistence-after.json').read_text())
        assert before==after,'Persistent graph state changed across container recreation'
        report['checks']['persistent-volume-identical-state']='PASS'
        run('recovery-health',compose+['up','-d','--wait'])
        report['checks']['fresh-live-nvidia']='NOT RUN: clean export deliberately contains no provider keys; separate private live run is required'
        report['status']='PASS'
    except Exception:
        report['status']='FAIL'
        raise
    finally:
        manifest.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
