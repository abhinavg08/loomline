"""Portable operator output and actual FalkorDB identity permissions."""
from argparse import Namespace
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import httpx

import pytest

from backend.app.config import settings
from scripts import init_local, onboard, provision_agent, revoke_agent
from .conftest import uid


def test_stdlib_bootstrap_is_unique_private_idempotent_and_portable(tmp_path, capsys):
    roots = [tmp_path / 'first machine with spaces', tmp_path / 'second machine']
    for root in roots:
        (root / 'scripts').mkdir(parents=True)
        shutil.copy(Path(init_local.__file__).parent / 'sync_auth_registry.py', root / 'scripts')
        shutil.copy(Path(init_local.__file__).parents[1] / '.env.example', root)
        init_local.main(root=root)
        original = {path.name: path.read_bytes() for path in (root / '.secrets').iterdir() if path.is_file()}
        original_env = (root / '.env').read_bytes()
        init_local.main(root=root)
        assert original_env == (root / '.env').read_bytes()
        assert original == {path.name: path.read_bytes() for path in (root / '.secrets').iterdir() if path.is_file()}
        assert (root / '.secrets/server/auth.json').read_bytes() == (root / '.secrets/auth.json').read_bytes()
    assert (roots[0] / '.env').read_bytes() != (roots[1] / '.env').read_bytes()
    projects = [next(line.split('=', 1)[1] for line in (root / '.env').read_text().splitlines()
                     if line.startswith('COMPOSE_PROJECT_NAME=')) for root in roots]
    assert len(set(projects)) == 2
    assert all(__import__('re').fullmatch(r'loomline-[a-f0-9]{16}', project) for project in projects)
    tokens = [json.loads((root / '.secrets/agent_tokens.json').read_text()) for root in roots]
    assert not set(tokens[0].values()) & set(tokens[1].values())
    output = capsys.readouterr().out
    assert all(value not in output for record in tokens for value in record.values())


@pytest.mark.integration
async def test_operator_synthetic_flag_and_default_create_actual_task_metadata(client, tokens, monkeypatch, capsys):
    """Bridge the real SDK to the real ASGI API on its database fixture loop."""
    from loomline import LoomlineClient
    loop = asyncio.get_running_loop()

    class SameLoopTransport(httpx.BaseTransport):
        def handle_request(self, request):
            async def submit():
                response = await client.request(request.method, request.url.path,
                                                headers=dict(request.headers), content=request.content)
                return httpx.Response(response.status_code, headers=response.headers,
                                      content=response.content, request=request)
            return asyncio.run_coroutine_threadsafe(submit(), loop).result(timeout=20)

    @contextmanager
    def actual_api(name=None):
        with LoomlineClient('http://portable-test', token=tokens['alpha:coordinator'], transport=SameLoopTransport()) as api:
            yield api

    monkeypatch.setattr(onboard, 'client', actual_api)
    for flag, expected in ((['--synthetic'], True), ([], False)):
        await asyncio.to_thread(onboard.main, ['project', '--name', uid('Portable project'),
                                             '--description', 'Actual operator-created metadata', '--status', 'active', *flag])
        result = json.loads(capsys.readouterr().out)
        response = await client.get('/v1/tasks/' + result['project_id'] + '/context',
                                    headers={'Authorization': 'Bearer ' + tokens['alpha:coordinator']})
        assert response.status_code == 200
        task = response.json()['task']
        assert task['synthetic'] is expected
        assert task['description'] == 'Actual operator-created metadata' and task['status'] == 'active'


@pytest.mark.integration
async def test_portable_onboarding_provisions_real_scoped_identity_and_private_configs(client, db, tmp_path, monkeypatch, capsys):
    root = tmp_path / 'release with spaces'
    private = root / '.secrets'
    private.mkdir(parents=True)
    registry = private / 'auth.json'
    registry.write_bytes(Path(settings.loom_auth_file).read_bytes())
    monkeypatch.setattr(settings, 'loom_auth_file', str(registry))
    for module in (onboard, provision_agent, revoke_agent):
        monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setenv('LOOM_PUBLIC_URL', 'http://127.0.0.1:18888')
    name = uid('portable')
    result = await onboard.identity('incident_42', name, 'investigator')
    token = (private / (name + '.token')).read_text()
    assert token not in json.dumps(result)
    assert result['task_restricted'] and result['procedure_approval'] is False
    host = json.loads((onboard.connection_folder(name) / 'host.profile.json').read_text())
    docker = json.loads((onboard.connection_folder(name) / 'docker.profile.json').read_text())
    assert host['base_url'] == 'http://127.0.0.1:18888'
    assert docker['base_url'] == 'http://gateway:8000'
    assert host['token_file'] == docker['token_file'] == 'agent.token'
    assert (onboard.connection_folder(name) / host['token_file']).read_text() == token
    record = json.loads(registry.read_text())[hashlib.sha256(token.encode()).hexdigest()]
    assert record['allowed_task_ids'] == ['incident_42']
    assert record['can_approve_procedures'] is False
    headers = {'Authorization': 'Bearer ' + token}
    assert (await client.get('/v1/me', headers=headers)).json()['agent_id'] == name
    assert (await client.get('/v1/tasks/incident_42/context', headers=headers)).status_code == 200
    assert (await client.get('/v1/tasks/private_task/context', headers=headers)).status_code == 404
    assert (await client.get('/v1/tasks', headers=headers)).json()['items'][0]['id'] == 'incident_42'
    session = await client.post('/v1/tasks/incident_42/sessions', headers=headers, json={'operation_id': uid()})
    assert session.status_code == 201
    with pytest.raises(SystemExit, match='already exists'):
        await onboard.identity('incident_42', name, 'investigator')
    config = onboard.connection(name, r'C:\Teammate Files\Loomline install')
    assert config['configuration']['mcpServers']['loomline']['command'] == 'docker'
    args = config['configuration']['mcpServers']['loomline']['args']
    assert args[2] == r'C:\Teammate Files\Loomline install'
    parsed = tomllib.loads(config['codex_toml'])
    assert parsed['mcp_servers']['loomline']['args'] == args
    assert parsed['mcp_servers']['loomline']['env']['LOOM_MCP_DIRECTORY'] == './.secrets/connections/' + name
    assert token not in json.dumps(config)
    assert not any('D:\\loomline' in arg for arg in args)
    assert (onboard.connection_folder(name) / 'mcp_config.json').is_file()
    with pytest.raises(SystemExit, match='already exist'):
        onboard.connection(name, '/another/path')
    await revoke_agent.revoke('alpha', name)
    assert (await client.get('/v1/me', headers=headers)).status_code == 401
    sessions = await db.client.select_graph(settings.tenant_graphs['alpha']).ro_query(
        'MATCH (a:Agent {id:$id})-[:HAS_SESSION]->(s:Session) RETURN s.id', {'id': name})
    assert len(sessions.result_set) == 1
    assert token not in capsys.readouterr().out


@pytest.mark.integration
async def test_portable_viewer_is_read_only_and_cannot_be_mcp_profile(client, db, tmp_path, monkeypatch, capsys):
    root = tmp_path / 'viewer portable release'
    private = root / '.secrets'; private.mkdir(parents=True)
    registry = private / 'auth.json'; registry.write_bytes(Path(settings.loom_auth_file).read_bytes())
    monkeypatch.setattr(settings, 'loom_auth_file', str(registry))
    for module in (onboard, provision_agent, revoke_agent):
        monkeypatch.setattr(module, 'ROOT', root)
    name = uid('viewer')
    result = await onboard.identity('incident_42', name, 'viewer')
    assert result['mcp_allowed'] is False
    token = (onboard.connection_folder(name) / 'agent.token').read_text()
    headers = {'Authorization': 'Bearer ' + token}
    assert (await client.get('/v1/tasks/incident_42/context', headers=headers)).status_code == 200
    denied = await client.post('/v1/tasks/incident_42/sessions', headers=headers, json={'operation_id': uid()})
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'READ_ONLY_IDENTITY'
    with pytest.raises(SystemExit, match='cannot initialize MCP'):
        onboard.connection(name, '/home/teammate/Loomline')
    assert token not in capsys.readouterr().out


def test_private_writes_and_generated_paths_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard, 'ROOT', tmp_path)
    target = tmp_path / 'private' / 'file'
    onboard.write_private(target, 'first')
    with pytest.raises(FileExistsError):
        onboard.write_private(target, 'second')
    assert target.read_text() == 'first'
    for value in ('../outside', 'with space', 'Uppercase', '/tmp/absolute', 'x\nattack'):
        with pytest.raises(SystemExit):
            onboard.safe_name(value)
    folder = onboard.connection_folder('normal')
    onboard.write_private(folder / 'identity.json', json.dumps({'role': 'investigator'}))
    for value in ('relative/path', '/home/project\nattack'):
        with pytest.raises(SystemExit, match='absolute extracted'):
            onboard.connection('normal', value)
