import json
import subprocess
import sys
from pathlib import Path


def main():
    a=subprocess.Popen([sys.executable,'-m','agents.proof_worker','investigator'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        first=json.loads(a.stdout.readline())
        b=subprocess.run([sys.executable,'-m','agents.proof_worker','verifier',first['memory_id']],capture_output=True,text=True,timeout=60,check=True)
        second=json.loads(b.stdout)
        a.stdin.write(json.dumps(second)+'\n')
        a.stdin.flush()
        final=json.loads(a.stdout.readline())
        assert final['read_reply'] and first['pid']!=second['pid']
        assert a.wait(timeout=60)==0
        report={'status':'PASS','storage':'real FalkorDB','agents':[first,second],'bidirectional_read':True}
        Path('artifacts').mkdir(exist_ok=True)
        Path('artifacts/two_agents.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    finally:
        if a.poll() is None:
            a.terminate()


if __name__=='__main__':
    main()
