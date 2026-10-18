"""Create a NEW disposable Git repository and separate worktrees. No coding CLI."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]

def prepare():
    folder=ROOT/'artifacts/mcp'/('demo_'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True,exist_ok=False)
    seed=folder/'seed';seed.mkdir()
    source=ROOT/'examples/mcp_collaboration'
    for name in ('cache.py','test_cache.py','EVIDENCE.md','AGENTS.md','MISSION.md'):shutil.copyfile(source/name,seed/name)
    shutil.copyfile(source/'AGENTS.md',seed/'CLAUDE.md')
    (seed/'.gitignore').write_text('__pycache__/\n*.pyc\n.agents/mcp_config.json\n')
    def git(*args):return subprocess.run(['git',*args],cwd=seed,check=True,capture_output=True,text=True)
    git('init');git('add','cache.py','test_cache.py','EVIDENCE.md','AGENTS.md','CLAUDE.md','MISSION.md','.gitignore')
    git('-c','user.name=Loomline Fixture','-c','user.email=fixture@localhost','commit','-m','Add disposable TTL failure fixture')
    paths={}
    for name in ('codex','claude','antigravity'):
        target=folder/name;git('worktree','add','-b','demo/'+name,str(target));paths[name]=str(target)
    # Verify genuine failures without changing the version the owner will investigate.
    result=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=seed,capture_output=True,text=True)
    (folder/'baseline.log').write_text(result.stdout+result.stderr)
    if result.returncode==0:raise RuntimeError('Fixture unexpectedly passes before the owner investigation')
    golden=folder/'validation_only';golden.mkdir()
    for name in ('cache.py','test_cache.py'):shutil.copyfile(seed/name,golden/name)
    path=golden/'cache.py';text=path.read_text();assert 'self.clock()+ttl_ms)' in text
    path.write_text(text.replace('self.clock()+ttl_ms)','self.clock()+ttl_ms/1000)'))
    checked=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=golden,capture_output=True,text=True)
    (folder/'fixed-validation.log').write_text(checked.stdout+checked.stderr)
    if checked.returncode:raise RuntimeError('Fixture final-fix tests failed')
    report={'status':'PREPARED','paths':paths,'fixture_baseline':'3 failures / 6 tests (expected)','validation_only_fixed_copy':'6 passed','identical_mission_file':str(seed/'MISSION.md'),'owner_cli_experiment':'PENDING_OWNER_VERIFICATION','owner_antigravity_ide':'PENDING_OWNER_VERIFICATION','owner_antigravity_cli':'PENDING_OWNER_VERIFICATION','coding_clients_launched':False,'active_mcp_configs_written':False,'folder':str(folder)}
    (folder/'fixture.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return report

if __name__=='__main__':prepare()
