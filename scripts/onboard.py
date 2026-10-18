"""Private, local Docker operator UX. Never prints or returns bearer values.

Run from the release directory with ``docker compose --profile tools run --rm
operator python -m scripts.onboard --help``. This is not an HTTP token issuer.
"""
import argparse
import asyncio
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from types import SimpleNamespace

from backend.app.config import ROOT
from loomline import LoomlineClient, LoomlineError
from . import provision_agent, revoke_agent


def private_root():
    return ROOT / '.secrets'


def safe_name(value):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,59}', value):
        raise SystemExit('Use a name starting with a lowercase letter, followed by up to 59 lowercase letters, digits, _ or -.')
    return value


def write_private(path, value):
    """Exclusive creation: reconnecting never overwrites an existing credential."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as output:
        output.write(value)


def public_url():
    return os.environ.get('LOOM_PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')


def internal_url():
    return os.environ.get('LOOM_URL', 'http://127.0.0.1:8000').rstrip('/')


def connection_folder(name):
    return private_root() / 'connections' / safe_name(name)


def profile(name):
    return json.loads((connection_folder(name) / 'host.profile.json').read_text())


@contextmanager
def client(name=None):
    if name:
        record = profile(name)
        token = (connection_folder(name) / record['token_file']).read_text().strip()
    else:
        token = json.loads((private_root() / 'agent_tokens.json').read_text())['alpha:coordinator']
    with LoomlineClient(internal_url(), token=token) as api:
        yield api


def bootstrap():
    """Expose only a discoverable private operator file, never its contents."""
    token = json.loads((private_root() / 'agent_tokens.json').read_text())['alpha:coordinator']
    target = private_root() / 'operator.token'
    if target.exists():
        if target.read_text().strip() != token:
            raise SystemExit('Existing operator.token differs; nothing overwritten. Check your private bootstrap registry.')
    else:
        write_private(target, token)
    with client() as api:
        identity = dict(api.whoami())
    return {'status': 'READY', 'identity': identity, 'studio_url': public_url(),
            'private_token_file': '.secrets/operator.token', 'secret_printed': False,
            'copy_on_windows': "Set-Clipboard -Value (Get-Content -Raw -LiteralPath ./.secrets/operator.token).Trim()",
            'copy_on_macos': 'pbcopy < .secrets/operator.token',
            'copy_on_linux_wayland': 'wl-copy < .secrets/operator.token'}


def project(name, description='', status='open', synthetic=False):
    with client() as api:
        result = api.create_task(name, assigned_agent_ids=['coordinator'],
                                 description=description or None, status=status, synthetic=synthetic)
    return {'status': 'CREATED', 'project_id': result['task_id'], 'project_name': name,
            'studio_url': public_url() + '/?task=' + result['task_id'],
            'next': 'Provision a different identity for each agent with identity --project PROJECT_ID --name AGENT_NAME --role investigator'}


async def identity(project_id, name, role, tenant='alpha'):
    name = safe_name(name)
    folder = connection_folder(name)
    if folder.exists():
        raise SystemExit('Connection name already exists; use a new name. No token or profile overwritten.')
    # The existing operator path writes an enabled Agent and ASSIGNED_TO edge to
    # real FalkorDB, hashes the new bearer, and mirrors the gateway registry.
    # Keep the operator CLI's stdout one JSON result; the existing trusted
    # provisioner reports safe metadata but is also used independently.
    with redirect_stdout(io.StringIO()):
        await provision_agent.provision(SimpleNamespace(
            tenant=tenant, agent_id=name, role=role, task=project_id,
            restrict_to_task=True, deny_procedure_approval=True))
    credential = private_root() / (name + '.token')
    folder.mkdir(parents=True, mode=0o700)
    write_private(folder / 'agent.token', credential.read_text().strip())
    common = {'task_id': project_id, 'token_file': 'agent.token',
              'allow_procedure_approval': False, 'timeout_seconds': 30}
    write_private(folder / 'host.profile.json', json.dumps({'base_url': public_url(), **common}, indent=2))
    write_private(folder / 'docker.profile.json', json.dumps({'base_url': 'http://gateway:8000', **common}, indent=2))
    write_private(folder / 'identity.json', json.dumps({'agent_id': name, 'role': role, 'tenant_id': tenant,
                                                      'project_id': project_id}, indent=2))
    return {'status': 'CREATED', 'agent_id': name, 'role': role, 'project_id': project_id,
            'task_restricted': True, 'procedure_approval': False,
            'private_token_file': '.secrets/connections/' + name + '/agent.token',
            'profile': '.secrets/connections/' + name + '/host.profile.json',
            'secret_printed': False,
            'mcp_allowed': role != 'viewer'}


def connection(name, host_root):
    name = safe_name(name)
    folder = connection_folder(name)
    metadata = json.loads((folder / 'identity.json').read_text())
    if metadata['role'] == 'viewer':
        raise SystemExit('A viewer cannot initialize MCP because initialization records a session. Use its token in read-only Studio or SDK instead.')
    # Host paths are supplied by the person running this command, not inferred
    # from /app inside Docker or inherited from the release author's laptop.
    if not (PurePosixPath(host_root).is_absolute() or PureWindowsPath(host_root).is_absolute()) or '\n' in host_root or '\r' in host_root:
        raise SystemExit('--host-root must be the absolute extracted checkout directory on the HOST computer.')
    args = ['compose', '--project-directory', host_root, '--profile', 'app', 'run', '--rm', '--no-deps', '-T',
            'mcp', '--profile', '/run/loomline/docker.profile.json']
    env = {'LOOM_MCP_DIRECTORY': './.secrets/connections/' + name}
    config = {'mcpServers': {'loomline': {'command': 'docker', 'args': args, 'env': env}}}
    # JSON strings are legal TOML basic strings; preserve Windows backslashes.
    toml = '[mcp_servers.loomline]\ncommand = "docker"\nargs = ' + json.dumps(args) + '\n' + \
           '[mcp_servers.loomline.env]\nLOOM_MCP_DIRECTORY = ' + json.dumps(env['LOOM_MCP_DIRECTORY']) + '\n'
    targets = {'mcp_config.json': json.dumps(config, indent=2), 'codex.toml': toml}
    if any((folder / target).exists() for target in targets):
        raise SystemExit('Generated connection files already exist; nothing overwritten. Use the existing files or provision a new identity.')
    for target, text in targets.items():
        write_private(folder / target, text)
    return {'status': 'GENERATED', 'agent_id': name, 'secret_printed': False,
            'configuration': config, 'codex_toml': toml,
            'private_files': ['.secrets/connections/' + name + '/' + target for target in targets],
            'working_directory': host_root, 'coding_application_modified': False,
            'before_connecting': 'docker compose --profile app build mcp'}


def verify(name):
    with client(name) as api:
        who = dict(api.whoami())
        record = profile(name)
        context = api.get_context(record['task_id'], limit=1)
    return {'status': 'CONNECTED', 'identity': who, 'project': context['task'],
            'secret_printed': False, 'transport': 'authenticated HTTP; MCP protocol is checked separately'}


def first_memory(name, content):
    record = profile(name)
    with client(name) as api:
        with api.session(record['task_id']) as session:
            memory = session.remember_episode(content)
            session_id = session.session_id
        retrieved = api.resolve(memory.reference)
    return {'status': 'COMMITTED_AND_RETRIEVED', 'project_id': record['task_id'],
            'session_id': session_id, 'memory_id': memory.id, 'reference': memory.reference,
            'content': retrieved['content'], 'source_turn_id': retrieved['source_turn_id'],
            'storage': 'FalkorDB via authenticated Loomline SDK; no model invoked'}


def recall(name, query=''):
    record = profile(name)
    with client(name) as api:
        context = api.get_context(record['task_id'], query=query or None, limit=10)
    return {'status': 'RETRIEVED', 'project': context['task'],
            'memories': [memory for memory_class in ('episodic', 'semantic', 'procedural')
                         for memory in context.get(memory_class, [])],
            'bounded_per_class': 10, 'storage': 'authorized real FalkorDB traversal; read only'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('bootstrap', help='Locate the first private coordinator bearer without displaying it')
    p = sub.add_parser('project', help='Create a named, blank project through the authenticated gateway')
    p.add_argument('--name', required=True); p.add_argument('--description', default='')
    p.add_argument('--status', choices=['open', 'active', 'completed', 'archived'], default='open')
    p.add_argument('--synthetic', action='store_true', help='Explicitly mark an acceptance/demo fixture; ordinary projects remain unmarked')
    p = sub.add_parser('identity', help='Provision a separate task-restricted identity, token and portable profiles')
    p.add_argument('--project', required=True); p.add_argument('--name', required=True)
    p.add_argument('--role', choices=['investigator', 'verifier', 'coordinator', 'viewer'], default='investigator')
    p.add_argument('--tenant', choices=['alpha', 'beta'], default='alpha')
    p = sub.add_parser('connection', help='Generate token-free MCP JSON and Codex TOML without modifying any client')
    p.add_argument('--name', required=True); p.add_argument('--host-root', required=True)
    p = sub.add_parser('verify', help='Read identity and authorized project without writing sessions')
    p.add_argument('--name', required=True)
    p = sub.add_parser('first-memory', help='Record a real source-linked episode then resolve it from FalkorDB')
    p.add_argument('--name', required=True); p.add_argument('--content', required=True)
    p = sub.add_parser('recall', help='Read actual shared memory as a separate authorized identity')
    p.add_argument('--name', required=True); p.add_argument('--query', default='')
    p = sub.add_parser('revoke', help='Disable this identity, remove its hashed credential, retain its history')
    p.add_argument('--name', required=True); p.add_argument('--tenant', choices=['alpha', 'beta'], default='alpha')
    args = parser.parse_args(argv)
    try:
        if args.action == 'bootstrap': result = bootstrap()
        elif args.action == 'project': result = project(args.name, args.description, args.status, args.synthetic)
        elif args.action == 'identity': result = asyncio.run(identity(args.project, args.name, args.role, args.tenant))
        elif args.action == 'connection': result = connection(args.name, args.host_root)
        elif args.action == 'verify': result = verify(args.name)
        elif args.action == 'first-memory': result = first_memory(args.name, args.content)
        elif args.action == 'recall': result = recall(args.name, args.query)
        else:
            asyncio.run(revoke_agent.revoke(args.tenant, safe_name(args.name)))
            return
        print(json.dumps(result, indent=2))
    except LoomlineError as error:
        raise SystemExit('Gateway rejected the operation: ' + error.code + '. Check health, identity permissions and the project ID.') from None
    except (FileNotFoundError, KeyError):
        raise SystemExit('Private local setup or connection profile not found. Run init_local, start the services, then bootstrap and identity. No credentials were displayed.') from None


if __name__ == '__main__':
    main()
