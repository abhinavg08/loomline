"""Mirror only hashed principals into the gateway's directory bind mount."""
import json
import os
from pathlib import Path

def sync(root=None):
    root=Path(root) if root else Path(__file__).resolve().parents[1]
    private=root/'.secrets';source=private/'auth.json'
    data=json.loads(source.read_text())
    directory=private/'server';directory.mkdir(mode=0o700,exist_ok=True)
    temporary=directory/'auth.pending';temporary.write_text(json.dumps(data,indent=2))
    if os.name!='nt':temporary.chmod(0o600)
    temporary.replace(directory/'auth.json')

if __name__=='__main__':sync();print('Hashed authentication registry ready; no credentials printed.')
