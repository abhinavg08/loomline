"""Read-only Studio credentials use the same real FalkorDB authorization boundary."""
import hashlib
import json
from argparse import Namespace

from fastapi.routing import APIRoute
import pytest
import pytest_asyncio

from backend.app.auth import TokenAuthenticator, authenticated
from backend.app.config import settings
from backend.app.main import app
from backend.app.nvidia import NvidiaInferenceService
from scripts import provision_agent, revoke_agent
from .conftest import auth, memory, uid

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def viewer(client, db, tmp_path, monkeypatch):
    # Exercise the actual local provision/revoke flow in a private test workspace.
    # Its Database still points at conftest's uniquely owned real test graphs.
    root = tmp_path / 'viewer-workspace'
    private = root / '.secrets'
    private.mkdir(parents=True)
    registry = private / 'auth.json'
    registry.write_bytes(__import__('pathlib').Path(settings.loom_auth_file).read_bytes())
    monkeypatch.setattr(settings, 'loom_auth_file', str(registry))
    monkeypatch.setattr(provision_agent, 'ROOT', root)
    monkeypatch.setattr(revoke_agent, 'ROOT', root)
    agent = uid('studio_viewer')
    args = Namespace(tenant='alpha', agent_id=agent, role='viewer', task='incident_42',
                     restrict_to_task=True, deny_procedure_approval=False)
    await provision_agent.provision(args)
    token = (private / (agent + '.token')).read_text()
    principal = TokenAuthenticator().authenticate(token)
    # Use the real inference service without issuing any inference request.
    service = NvidiaInferenceService()
    previous = getattr(app.state, 'nvidia', None)
    app.state.nvidia = service
    try:
        yield {'agent': agent, 'token': token, 'headers': {'Authorization': 'Bearer ' + token},
               'principal': principal, 'registry': registry, 'root': root}
    finally:
        await service.close()
        if previous is None:
            del app.state.nvidia
        else:
            app.state.nvidia = previous


async def graph_digest(db, principal, exclude_node_id=None):
    nodes = await db.query(principal, 'MATCH (n) RETURN n')
    edges = await db.query(principal, 'MATCH (a)-[e]->(b) RETURN a.id AS source,type(e) AS type,b.id AS target,e')
    value = {'nodes': sorted(json.dumps(row['n'].properties, sort_keys=True) for row in nodes
                             if row['n'].properties.get('id') != exclude_node_id),
             'edges': sorted(json.dumps([row['source'], row['type'], row['target'], row['e'].properties], sort_keys=True) for row in edges)}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def test_viewer_provision_and_authorized_studio_reads_are_read_only(client, db, tokens, viewer):
    principal = viewer['principal']
    assert principal.role == 'viewer'
    assert principal.allowed_task_ids == ('incident_42',)
    assert principal.can_approve_procedures is False
    records = json.loads(viewer['registry'].read_text())
    record = records[hashlib.sha256(viewer['token'].encode()).hexdigest()]
    assert record['can_approve_procedures'] is False

    created, request = await memory(client)
    handoff = await client.post('/v1/tasks/incident_42/handoffs', headers=auth(tokens, 'alpha:coordinator'),
                                json={'operation_id': uid(), 'to_agent_id': 'verifier',
                                      'description': 'Synthetic viewer inspection', 'related_memory_ids': [created['memory_id']]})
    assert handoff.status_code == 201
    reference = 'loom://task/incident_42/memory/' + created['memory_id']
    paths = ['/v1/me', '/v1/tasks', '/v1/scopes', '/v1/capabilities', '/v1/model-status',
             '/v1/inference-status', '/v1/verification', '/v1/inbox?task_id=incident_42',
             *('/v1/tasks/incident_42/' + suffix for suffix in
               ('agents', 'sessions', 'turns', 'context', 'context-pack', 'decision-context',
                'changes', 'integrity', 'claims', 'mcp-activity', 'mcp-preflight')),
             '/v1/tasks/incident_42/memories/' + created['memory_id'],
             '/v1/tasks/incident_42/handoffs/' + handoff.json()['handoff_id'],
             '/v1/sessions/' + request['session_id'] + '/turns',
             '/v1/resolve?reference=' + reference, '/v1/trace?reference=' + reference]
    before = await graph_digest(db, principal)
    for path in paths:
        response = await client.get(path, headers=viewer['headers'])
        assert response.status_code == 200, (path, response.status_code)
        secret_leaked = viewer['token'] in response.text
        assert secret_leaked is False
    trace = (await client.get('/v1/trace', params={'reference': reference}, headers=viewer['headers'])).json()
    assert trace['memory']['id'] == created['memory_id']
    assert trace['source_turn']['id'] == request['source_turn_id']
    assert trace['related_handoffs'][0]['id'] == handoff.json()['handoff_id']
    assert await graph_digest(db, principal) == before
    assert app.state.nvidia.metrics == []


async def test_every_mutating_api_route_rejects_viewer_before_validation_and_side_effects(client, db, viewer):
    routes = [route for route in app.routes if isinstance(route, APIRoute) and route.path.startswith('/v1/')
              and route.methods - {'GET', 'HEAD', 'OPTIONS'}]
    # This inventory grows automatically when another mutating API is added.
    assert len(routes) >= 20
    before = await graph_digest(db, viewer['principal'])
    for route in routes:
        assert any(dependency.call is authenticated for dependency in route.dependant.dependencies), route.path
        path = route.path
        for parameter in route.param_convertors:
            path = path.replace('{' + parameter + '}', 'incident_42' if parameter == 'task' else 'viewer_denied')
        for method in route.methods - {'GET', 'HEAD', 'OPTIONS'}:
            # Invalid model bodies must not turn this into a validation error or
            # reach inference/session/claim/handoff/inbox handlers.
            response = await client.request(method, path, headers=viewer['headers'], json={})
            assert response.status_code == 403, (method, route.path, response.status_code)
            assert response.json() == {'error': {'code': 'READ_ONLY_IDENTITY'}}
    assert await graph_digest(db, viewer['principal']) == before
    assert app.state.nvidia.metrics == []


async def test_viewer_task_assignment_restriction_and_tenant_are_all_required(client, db, tokens, viewer):
    coordinator = TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    # Membership alone cannot expand a restricted bearer beyond its allowlist.
    other = await client.post('/v1/tasks', headers=auth(tokens, 'alpha:coordinator'),
                              json={'operation_id': uid(), 'title': 'Isolated viewer scope test',
                                    'assigned_agent_ids': [viewer['agent']]})
    assert other.status_code == 201
    for suffix in ('context', 'agents', 'sessions', 'turns', 'claims', 'mcp-activity'):
        response = await client.get('/v1/tasks/' + other.json()['task_id'] + '/' + suffix, headers=viewer['headers'])
        assert response.status_code == 404
    page = (await client.get('/v1/tasks', headers=viewer['headers'])).json()
    assert [task['id'] for task in page['items']] == ['incident_42']
    created, _ = await memory(client)
    # A separately provisioned viewer in another physical tenant graph cannot
    # access this tenant's memory despite having the same task name.
    beta_agent = uid('beta_studio_viewer')
    await provision_agent.provision(Namespace(tenant='beta', agent_id=beta_agent, role='viewer',
                                              task='incident_42', restrict_to_task=True,
                                              deny_procedure_approval=False))
    beta_token = (viewer['root'] / '.secrets' / (beta_agent + '.token')).read_text()
    beta_headers = {'Authorization': 'Bearer ' + beta_token}
    assert (await client.get('/v1/me', headers=beta_headers)).json()['tenant_id'] == 'beta'
    for path in ('/v1/resolve', '/v1/trace'):
        response = await client.get(path, params={'reference': 'loom://task/incident_42/memory/' + created['memory_id']},
                                    headers=beta_headers)
        assert response.status_code == 404
    # A valid allowed_task_ids entry also cannot replace enabled graph membership.
    await db.query(coordinator, 'MATCH (t:Task {id:$task})-[r:ASSIGNED_TO]->(a:Agent {id:$agent}) DELETE r',
                   {'task': 'incident_42', 'agent': viewer['agent']}, write=True)
    assert (await client.get('/v1/tasks/incident_42/context', headers=viewer['headers'])).status_code == 404
    assert (await client.get('/v1/tasks', headers=viewer['headers'])).json()['items'] == []


async def test_viewer_revocation_blocks_existing_bearer_and_preserves_history(client, db, viewer):
    await memory(client)
    before = await graph_digest(db, viewer['principal'], exclude_node_id=viewer['agent'])
    assert (await client.get('/v1/tasks/incident_42/context', headers=viewer['headers'])).status_code == 200
    await revoke_agent.revoke('alpha', viewer['agent'])
    for path in ('/v1/me', '/v1/tasks', '/v1/tasks/incident_42/context'):
        response = await client.get(path, headers=viewer['headers'])
        assert response.status_code == 401
        assert response.json() == {'error': {'code': 'UNAUTHENTICATED'}}
    # Revocation disables only the isolated identity and removes its registry
    # entry; no stored memory/session/turn is deleted.
    nodes = await db.query(viewer['principal'], 'MATCH (a:Agent {id:$agent}) RETURN a.enabled AS enabled',
                           {'agent': viewer['agent']})
    assert nodes == [{'enabled': False}]
    assert await graph_digest(db, viewer['principal'], exclude_node_id=viewer['agent']) == before
    registry = json.loads(viewer['registry'].read_text())
    assert hashlib.sha256(viewer['token'].encode()).hexdigest() not in registry
    assert (viewer['root'] / '.secrets' / (viewer['agent'] + '.token')).is_file()
