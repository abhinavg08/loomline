"""Run independent stdio MCP clients against real disposable FalkorDB graphs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from .isolation import temporary_runtime

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',default='artifacts/mcp');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];folder=(root/args.output_dir).resolve()
    if not folder.is_relative_to(root/'artifacts/mcp'):raise SystemExit('Output must be under artifacts/mcp')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'protocol.json').write_text(json.dumps({'status':'IN_PROGRESS'}))
    interpreter=root/('.venv-mcp/Scripts/python.exe' if os.name=='nt' else '.venv-mcp/bin/python')
    with temporary_runtime():
        env={**os.environ,'LOOM_TEST_BACKEND_PYTHON':sys.executable,'LOOM_MCP_REPORT':str(folder/'protocol.json')}
        with (folder/'pytest.log').open('w') as log:
            result=subprocess.run([str(interpreter),'-m','pytest','mcp_tests','-q','--tb=short','--basetemp',str(folder/('tmp_'+__import__('uuid').uuid4().hex[:12])),'--junitxml',str(folder/'junit.xml')],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        # Never echo failed assertion bodies, which might accidentally contain a private input.
        report=json.loads((folder/'protocol.json').read_text()) if (folder/'protocol.json').exists() else {}
        report.update(status='PASS' if result.returncode==0 else 'FAIL',evidence_type='independent MCP test clients + real FalkorDB',owner_codex_cli='PENDING_OWNER_VERIFICATION',owner_claude_cli='PENDING_OWNER_VERIFICATION',real_two_cli_exchange='PENDING_OWNER_VERIFICATION')
        report.update(owner_antigravity_ide='PENDING_OWNER_VERIFICATION',owner_antigravity_cli='PENDING_OWNER_VERIFICATION',real_three_client_exchange='PENDING_OWNER_VERIFICATION')
        suites=ET.parse(folder/'junit.xml').getroot().iter('testsuite')
        report['test_suites']=[{k:s.attrib[k] for k in ('tests','failures','errors','time') if k in s.attrib} for s in suites]
        report['antigravity_configuration_checks']='PASS' if result.returncode==0 else 'SEE_FAILURE_LOG'
    report['owned_test_graphs_cleaned']=True;(folder/'protocol.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    if result.returncode:raise SystemExit(result.returncode)

if __name__=='__main__':main()
