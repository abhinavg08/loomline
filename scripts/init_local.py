"""Generate local credentials without printing them. Safe to rerun; never overwrites."""
import hashlib
import json
import secrets
from pathlib import Path
import os


def provision_tokens(private):
    """Reusable for temporary test identities; return nothing containing secrets."""
    tokens,hashes={},{}
    for tenant in ('alpha','beta'):
        roles=('investigator','verifier','coordinator','unassigned') if tenant=='alpha' else ('investigator','verifier','coordinator')
        for role in roles:
            agent=role if tenant=='alpha' else 'beta_'+role
            token=secrets.token_urlsafe(32)
            tokens[tenant+':'+role]=token
            hashes[hashlib.sha256(token.encode()).hexdigest()]=dict(tenant_id=tenant,agent_id=agent,role=role)
    private.mkdir(parents=True,exist_ok=True)
    for name,value in [('auth.json',hashes),('agent_tokens.json',tokens)]:
        path=private/name
        if os.name!='nt' and path.exists():path.chmod(0o600)
        with os.fdopen(os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600),'w') as output:output.write(json.dumps(value,indent=2))


def main(rotate_tokens=False, root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    private = root / '.secrets'
    private.mkdir(exist_ok=True,mode=0o700)
    if rotate_tokens or not (private / 'auth.json').exists():
        provision_tokens(private)
    if not (root / '.env').exists():
        text = (root / '.env.example').read_text().replace('generate_with_scripts_init_local', secrets.token_urlsafe(36))
        # Different extracted directories must never silently reuse another
        # installation's Compose containers or persistent graph volume.
        text+='\nCOMPOSE_PROJECT_NAME=loomline-'+secrets.token_hex(8)+'\n'
        # Bootstrap can run as the host user in Docker on macOS/Linux. Preserve
        # that UID for operator/MCP containers so 0600 private files stay usable.
        if os.name!='nt':text+='\nLOOM_OPERATOR_UID='+str(os.getuid())+'\nLOOM_OPERATOR_GID='+str(os.getgid())+'\n'
        with os.fdopen(os.open(root/'.env',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as output:output.write(text)
    # Also works as a standalone stdlib script in the bootstrap Docker image.
    import importlib.util
    spec=importlib.util.spec_from_file_location('sync_registry',root/'scripts/sync_auth_registry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.sync(root)
    print('Local configuration ready; credentials were not printed.')


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--rotate-tokens',action='store_true')
    main(parser.parse_args().rotate_tokens)
