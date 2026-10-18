"""Named projects, backward-compatible receipts and safe onboarding discovery."""
import hashlib
import json
from pathlib import Path
import secrets

import httpx
import pytest

from backend.app.auth import TokenAuthenticator
from backend.app.config import ROOT, settings
from backend.app.main import app
from loomline import AsyncLoomlineClient
from .conftest import auth, uid

pytestmark = pytest.mark.integration


async def test_named_project_metadata_persists_through_sdk_task_list_graph_and_collaboration(client, tokens):
    async with AsyncLoomlineClient('http://test', token=tokens['alpha:coordinator'],
                                   transport=httpx.ASGITransport(app=app), max_attempts=1) as sdk:
        result = await sdk.create_task('Website collaboration', assigned_agent_ids=['investigator'],
                                       description='Shared design decisions and independent verification.',
                                       status='active')
        task = result.task_id
        listing = await sdk.list_tasks(limit=100)
        project = next(item for item in listing['items'] if item['id'] == task)
        assert project['title'] == 'Website collaboration'
        assert project['description'] == 'Shared design decisions and independent verification.'
        assert project['status'] == 'active'
        assert project['version'] == 1
    for view in ('graph', 'collaboration'):
        response = await client.get(f'/v1/tasks/{task}/{view}')
        assert response.status_code == 200, response.text
        assert response.json()['task']['description'] == project['description']
        assert response.json()['task']['status'] == 'active'
    denied = await client.get(f'/v1/tasks/{task}/graph', headers=auth(tokens, 'alpha:verifier'))
    assert denied.status_code == 404
    for invalid in ({'description': ''}, {'description': 'x' * 1001}, {'status': 'unrecognized'}):
        response = await client.post('/v1/tasks', headers=auth(tokens, 'alpha:coordinator'), json={
            'operation_id': uid(), 'title': 'TEST-CLIENT invalid metadata',
            'assigned_agent_ids': ['investigator'], **invalid})
        assert response.status_code == 400


async def test_default_task_receipt_keeps_legacy_hash_and_changed_metadata_conflicts(client, db, tokens):
    operation = uid()
    body = {'operation_id': operation, 'title': 'TEST-CLIENT legacy project',
            'assigned_agent_ids': ['investigator'], 'synthetic': False, 'template': 'blank'}
    headers = auth(tokens, 'alpha:coordinator')
    created = await client.post('/v1/tasks', headers=headers, json=body)
    assert created.status_code == 201
    task = created.json()['task_id']
    principal = TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    rows = await db.query(principal, 'MATCH (op:Operation {id:$id}) RETURN op', {'id': operation})
    legacy_hash = hashlib.sha256(json.dumps([
        'coordinator', 'alpha', body['title'], ['coordinator', 'investigator'], False, 'blank'
    ], sort_keys=True).encode()).hexdigest()
    assert rows[0]['op'].properties['payload_hash'] == legacy_hash
    # Omitted and explicitly defaulted presentation fields must replay the same
    # receipt; callers made before metadata existed remain compatible.
    for defaults in ({}, {'description': None, 'status': 'open'}):
        replay = await client.post('/v1/tasks', headers=headers, json={**body, **defaults})
        assert replay.status_code == 200
        assert replay.json() == created.json()
    for changed in ({'description': 'Different description'}, {'status': 'completed'}, {'title': 'Different title'}):
        conflict = await client.post('/v1/tasks', headers=headers, json={**body, **changed})
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    project = (await client.get(f'/v1/tasks/{task}/graph')).json()['task']
    assert project['title'] == body['title'] and project['status'] == 'open' and project.get('description', '') == ''
    # Non-default metadata participates in its own receipt and exact replay.
    another = {**body, 'operation_id': uid(), 'description': 'Reviewed project scope', 'status': 'completed'}
    initial = await client.post('/v1/tasks', headers=headers, json=another)
    replay = await client.post('/v1/tasks', headers=headers, json=another)
    assert initial.status_code == 201 and replay.status_code == 200
    assert initial.json() == replay.json()
    conflict = await client.post('/v1/tasks', headers=headers, json={**another, 'description': 'Changed scope'})
    assert conflict.status_code == 409


async def test_me_capabilities_respect_role_and_task_scope_without_granting_permissions(client, db, tokens, tmp_path, monkeypatch):
    for identity, create in (('alpha:coordinator', True), ('alpha:investigator', False), ('alpha:verifier', False)):
        response = await client.get('/v1/me', headers=auth(tokens, identity))
        assert response.status_code == 200
        assert response.json() == {'tenant_id': 'alpha', 'agent_id': identity.split(':')[1],
                                   'role': identity.split(':')[1], 'can_create_projects': create,
                                   'read_only': False, 'task_scope_restricted': False}
    records = json.loads(Path(settings.loom_auth_file).read_text())
    coordinator = TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    isolated = []
    for role in ('coordinator', 'viewer'):
        agent, token = uid('project_' + role), secrets.token_urlsafe(32)
        records[hashlib.sha256(token.encode()).hexdigest()] = {
            'tenant_id': 'alpha', 'agent_id': agent, 'role': role, 'allowed_task_ids': ['incident_42']}
        await db.query(coordinator,
                       'MATCH (t:Task {id:$task}) CREATE (a:Agent {id:$id,role:$role,enabled:true}) '
                       'CREATE (t)-[:ASSIGNED_TO]->(a)',
                       {'task': 'incident_42', 'id': agent, 'role': role}, write=True)
        isolated.append((agent, token, role))
    registry = tmp_path / 'project-auth.json'
    registry.write_text(json.dumps(records))
    monkeypatch.setattr(settings, 'loom_auth_file', str(registry))
    for agent, token, role in isolated:
        headers = {'Authorization': 'Bearer ' + token}
        identity = (await client.get('/v1/me', headers=headers)).json()
        assert identity['agent_id'] == agent and identity['role'] == role
        assert identity['task_scope_restricted'] and not identity['can_create_projects']
        assert identity['read_only'] == (role == 'viewer')
        assert token not in json.dumps(identity)
        # Membership and scope both permit the intended read-only views.
        for suffix in ('graph', 'collaboration'):
            assert (await client.get('/v1/tasks/incident_42/' + suffix, headers=headers)).status_code == 200
        denied = await client.post('/v1/tasks', headers=headers, json={
            'operation_id': uid(), 'title': 'Should not create', 'assigned_agent_ids': [agent]})
        assert denied.status_code == 403
        assert denied.json()['error']['code'] == ('READ_ONLY_IDENTITY' if role == 'viewer' else 'TASK_SCOPED_PRINCIPAL')


async def test_public_help_serves_only_fixed_safe_markdown_without_authentication(client):
    allowed = {'README': 'README.md', 'START_HERE': 'docs/getting-started.md',
               'AGENT_SETUP': 'docs/connect-agents.md', 'STUDIO_AUTH': 'docs/security.md',
               'GRAPH_MODEL': 'docs/graph-model.md', 'MEMORY_GRAPH_GUIDE': 'docs/memory-graph.md'}
    for document, relative in allowed.items():
        # Even an invalid bearer is irrelevant: these exact shipped public
        # documents are intentionally available before a user signs in.
        response = await client.get('/help/' + document, headers={'Authorization': 'Bearer invalid'})
        assert response.status_code == 200, (document, response.status_code)
        assert response.text == (ROOT / relative).read_text(encoding='utf-8')
        assert response.headers['content-type'].startswith('text/markdown')
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert (await client.get('/help/' + document.lower() + '.md')).status_code == 200
    for forbidden in ('.env', 'auth.json', 'agent_tokens.json', 'IMPLEMENTATION_NOTES.md',
                      '.secrets', 'GRAPH_MODEL.md.md', '%2e%2e%2f.env', '%2e%2e%5c.env'):
        result = await client.get('/help/' + forbidden)
        assert result.status_code == 404, (forbidden, result.status_code)
