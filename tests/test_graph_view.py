"""The Studio graph uses genuine stored edges and the normal authorization path."""
import hashlib
import json
import secrets
import time

import pytest

from backend.app.auth import TokenAuthenticator
from backend.app.config import settings
from .conftest import auth, memory, source, uid

pytestmark = pytest.mark.integration


async def edges_in_database(db, principal, ids):
    rows = await db.query(principal,
                          'MATCH (s)-[e]->(t) WHERE s.id IN $ids AND t.id IN $ids '
                          'RETURN s.id AS source,type(e) AS type,t.id AS target', {'ids': ids})
    return {(row['source'], row['type'], row['target']) for row in rows}


async def snapshot(db, principal):
    rows = await db.query(principal, 'MATCH (n) RETURN n ORDER BY id(n)')
    edges = await db.query(principal, 'MATCH (s)-[e]->(t) RETURN s.id AS source,type(e) AS type,t.id AS target ORDER BY source,type,target')
    return hashlib.sha256(json.dumps({'nodes': [row['n'].properties for row in rows], 'edges': edges}, sort_keys=True).encode()).hexdigest()


async def test_graph_provenance_contains_only_persisted_edges_and_queries_are_read_only(client, db, tokens, monkeypatch):
    created, request = await memory(client)
    mid = created['memory_id']
    evidence = await client.post('/v1/tasks/incident_42/evidence', json={
        'operation_id': uid(), 'source_type': 'synthetic', 'source_ref': 'TEST-CLIENT graph evidence',
        'content': 'Synthetic independent counterexample', 'observed_at': '2026-10-18T00:00:00+00:00'})
    assert evidence.status_code == 201
    # A real semantic hypothesis, source turn and contrary evidence create the
    # actual CHALLENGED_BY edge, rather than a rendering-only relationship.
    hypothesis, _ = await memory(client, **{'class': 'semantic'}, assertion_type='hypothesis', status='proposed',
                                 evidence_ids=[evidence.json()['evidence_id']])
    challenge = await client.post('/v1/tasks/incident_42/memories/' + hypothesis['memory_id'] + '/challenges',
                                  headers=auth(tokens, 'alpha:verifier'), json={
                                      'operation_id': uid(), 'expected_version': 1,
                                      'evidence_id': evidence.json()['evidence_id'], 'reason': 'TEST-CLIENT counterexample'})
    assert challenge.status_code == 201
    handoff = await client.post('/v1/tasks/incident_42/handoffs', json={
        'operation_id': uid(), 'to_agent_id': 'verifier', 'description': 'TEST-CLIENT graph handoff',
        'related_memory_ids': [mid]}, headers=auth(tokens, 'alpha:coordinator'))
    assert handoff.status_code == 201
    principal = TokenAuthenticator().authenticate(tokens['alpha:investigator'])
    before = await snapshot(db, principal)
    writes = []
    actual_query = db.query

    async def observed_query(principal, query, params=None, *, write=False):
        writes.append(write)
        return await actual_query(principal, query, params, write=write)

    monkeypatch.setattr(db, 'query', observed_query)
    response = await client.get('/v1/tasks/incident_42/graph')
    assert response.status_code == 200, response.text
    graph = response.json()
    assert writes and not any(writes)
    assert {'Memory', 'Task', 'Agent', 'Session', 'Turn', 'Evidence', 'Handoff', 'MemoryEvent'} <= {node['type'] for node in graph['nodes']}
    tuples = {(edge['source_id'], edge['type'], edge['target_id']) for edge in graph['edges']}
    assert (mid, 'DERIVED_FROM', request['source_turn_id']) in tuples
    assert ('investigator', 'CREATED', mid) in tuples
    assert (request['session_id'], 'HAS_TURN', request['source_turn_id']) in tuples
    assert (handoff.json()['handoff_id'], 'REFERS_TO', mid) in tuples
    assert (hypothesis['memory_id'], 'CHALLENGED_BY', evidence.json()['evidence_id']) in tuples
    assert not any(kind in {'HAS_EVENT', 'USED_CONTEXT', 'INFLUENCED', 'CREATED_BY'} for _, kind, _ in tuples)
    assert tuples <= await edges_in_database(db, principal, [node['id'] for node in graph['nodes']])
    assert all(query['read_only'] and query['cypher'].startswith('MATCH (t:Task {id:$task})-[:ASSIGNED_TO]') for query in graph['queries'])
    assert all(query['parameters']['actor'] == 'investigator' for query in graph['queries'])
    assert 'Operation' not in {node['type'] for node in graph['nodes']}
    assert all(not any(key in node['properties'] for key in ('result_json', 'payload_hash', 'operation_id')) for node in graph['nodes'])
    assert await snapshot(db, principal) == before


async def test_graph_memory_pagination_filters_focus_and_validation(client):
    episodic = [(await memory(client))[0]['memory_id'] for _ in range(5)]
    semantic, body = await memory(client, **{'class': 'semantic'}, assertion_type='hypothesis', status='proposed')
    params = {'limit': 2, 'memory_class': 'episodic', 'agent_id': 'investigator'}
    first = (await client.get('/v1/tasks/incident_42/graph', params=params)).json()
    assert len(first['memory_page_ids']) == 2 and first['next_cursor']
    second = (await client.get('/v1/tasks/incident_42/graph', params={**params, 'before': first['next_cursor']})).json()
    assert len(second['memory_page_ids']) == 2
    assert not set(first['memory_page_ids']) & set(second['memory_page_ids'])
    third = (await client.get('/v1/tasks/incident_42/graph', params={**params, 'before': second['next_cursor']})).json()
    # Other tests may have created earlier episodic records in the shared,
    # uniquely owned test graph. All requested newly committed records appear.
    seen = set(first['memory_page_ids'] + second['memory_page_ids'] + third['memory_page_ids'])
    assert set(episodic) <= seen
    assert semantic['memory_id'] not in seen
    # A cursor is bound to this authenticated tenant/task/operation/filter set.
    assert (await client.get('/v1/tasks/incident_42/graph', params={
        **params, 'memory_class': 'semantic', 'before': first['next_cursor']})).status_code == 400
    assert (await client.get('/v1/tasks/incident_42/collaboration', params={
        'before': first['next_cursor']})).status_code == 400
    focused = await client.get('/v1/tasks/incident_42/graph', params={'focus': semantic['memory_id']})
    assert focused.status_code == 200, focused.text
    assert semantic['memory_id'] in {node['id'] for node in focused.json()['nodes']}
    assert body['source_turn_id'] in {node['id'] for node in focused.json()['nodes']}
    source_focus = await client.get('/v1/tasks/incident_42/graph', params={'focus': body['source_turn_id']})
    assert source_focus.status_code == 200, source_focus.text
    assert semantic['memory_id'] in {node['id'] for node in source_focus.json()['nodes']}
    filtered = (await client.get('/v1/tasks/incident_42/graph', params={'relationship': 'DERIVED_FROM'})).json()
    assert filtered['edges'] and all(edge['type'] == 'DERIVED_FROM' for edge in filtered['edges'])
    future = (await client.get('/v1/tasks/incident_42/graph', params={'since': '2099-01-01T00:00:00Z'})).json()
    assert future['memory_page_ids'] == []
    for values in ({'before': '!not-a-cursor'}, {'relationship': 'INVENTED'}, {'memory_class': 'private'},
                   {'since': 'yesterday'}, {'since': '2026-10-18'},
                   {'since': '0001-01-01T00:00:00+23:59'}, {'focus': 'anything OR true'}):
        result = await client.get('/v1/tasks/incident_42/graph', params=values)
        assert result.status_code == 400, (values, result.text)
    assert (await client.get('/v1/tasks/incident_42/graph?focus=missing_record')).status_code == 404
    assert (await client.get('/v1/tasks/incident_42/graph?limit=10000')).status_code == 400


async def test_graph_and_collaboration_enforce_tenant_assignment_and_viewer_read_only(client, db, tokens, tmp_path, monkeypatch):
    created, _ = await memory(client)
    token = secrets.token_urlsafe(32)
    registry = json.loads(__import__('pathlib').Path(settings.loom_auth_file).read_text())
    agent = uid('graph_viewer')
    registry[hashlib.sha256(token.encode()).hexdigest()] = {
        'tenant_id': 'alpha', 'agent_id': agent, 'role': 'viewer', 'allowed_task_ids': ['incident_42']}
    path = tmp_path / 'graph-auth.json'
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(settings, 'loom_auth_file', str(path))
    principal = TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    await db.query(principal, 'MATCH (t:Task {id:$task}) CREATE (a:Agent {id:$id,role:$role,enabled:true}) CREATE (t)-[:ASSIGNED_TO]->(a)',
                   {'task': 'incident_42', 'id': agent, 'role': 'viewer'}, write=True)
    headers = {'Authorization': 'Bearer ' + token}
    before = await snapshot(db, principal)
    for suffix in ('graph', 'collaboration'):
        response = await client.get('/v1/tasks/incident_42/' + suffix, headers=headers)
        assert response.status_code == 200, response.text
        assert token not in response.text
        for denied in ({'Authorization': 'Bearer invalid'}, auth(tokens, 'alpha:unassigned')):
            assert (await client.get('/v1/tasks/incident_42/' + suffix, headers=denied)).status_code in (401, 404)
        beta = await client.get('/v1/tasks/incident_42/' + suffix, headers=auth(tokens, 'beta:investigator'))
        assert beta.status_code == 200
        assert created['memory_id'] not in beta.text
    assert await snapshot(db, principal) == before
    assert (await client.get('/v1/tasks/incident_42/graph', params={'focus': created['memory_id']},
                              headers=auth(tokens, 'beta:investigator'))).status_code == 404
    other = await client.post('/v1/tasks', headers=auth(tokens, 'alpha:coordinator'), json={
        'operation_id': uid(), 'title': 'TEST-CLIENT other project', 'assigned_agent_ids': [agent]})
    assert other.status_code == 201
    for suffix in ('graph', 'collaboration'):
        assert (await client.get('/v1/tasks/' + other.json()['task_id'] + '/' + suffix, headers=headers)).status_code == 404
    # Viewers cannot mutate through another route after using the graph.
    assert (await client.post('/v1/tasks/incident_42/sessions', headers=headers,
                               json={'operation_id': uid()})).json() == {'error': {'code': 'READ_ONLY_IDENTITY'}}
    # Exclude the intentionally created second task when checking read behavior.
    # The actual graph reads above ran before that mutation and preserved hashes.
    assert before != await snapshot(db, principal)


async def test_collaboration_separates_authorization_contribution_sessions_and_reported_context(client, tokens):
    headers = auth(tokens, 'alpha:coordinator')
    result = await client.post('/v1/tasks', headers=headers, json={
        'operation_id': uid(), 'title': 'TEST-CLIENT contribution facts',
        'assigned_agent_ids': ['investigator', 'verifier']})
    task = result.json()['task_id']
    sid = (await client.post(f'/v1/tasks/{task}/sessions', json={'operation_id': uid()})).json()['session_id']
    # A coordinator session with no turn or tool activity is historical access,
    # not sufficient evidence of contributing to the work.
    await client.post(f'/v1/tasks/{task}/sessions', headers=headers, json={'operation_id': uid()})
    turn = await client.post(f'/v1/sessions/{sid}/turns', json={
        'operation_id': uid(), 'role': 'assistant', 'content': 'TEST-CLIENT: prior context informed this reported plan.'})
    mem = await client.post(f'/v1/tasks/{task}/memories', json={
        'operation_id': uid(), 'session_id': sid, 'source_turn_id': turn.json()['turn_id'],
        'class': 'episodic', 'assertion_type': 'episode', 'status': 'active',
        'content': 'TEST-CLIENT: I report using prior context; this is not an attested model decision.'})
    assert mem.status_code == 201
    call = await client.post(f'/v1/tasks/{task}/mcp-activity', json={
        'operation_id': uid(), 'session_id': sid, 'tool_name': 'loomline_recall', 'outcome': 'success', 'duration_ms': 3})
    assert call.status_code == 201
    response = await client.get(f'/v1/tasks/{task}/collaboration', params={'limit': 2})
    assert response.status_code == 200, response.text
    facts = response.json()
    assert facts['counts'] == {'authorized_agents': 3, 'contributors': 1, 'sessions': 2}
    assert [item['id'] for item in facts['contributors']] == ['investigator']
    members = {item['id']: item for item in facts['authorized_agents']}
    assert members['coordinator']['counts']['sessions'] == 1 and not members['coordinator']['contributor']
    assert members['verifier']['counts']['sessions'] == 0 and not members['verifier']['contributor']
    seen, cursor = [], None
    for _ in range(5):
        page = (await client.get(f'/v1/tasks/{task}/collaboration', params={'limit': 2, 'before': cursor or ''})).json()
        seen.extend(page['timeline'])
        cursor = page['next_cursor']
        if not cursor:
            break
    assert len({item['id'] for item in seen}) == len(seen)
    memory_item = next(item for item in seen if item['id'] == mem.json()['memory_id'])
    assert memory_item['classification'] == 'explicit_synthetic_or_test'
    assert memory_item['provenance_ref'].endswith('/memory/' + mem.json()['memory_id'])
    assert 'does not prove' in facts['interpretation']
    assert 'arguments and results' in facts['interpretation']


async def test_graph_stays_bounded_for_more_than_one_hundred_real_api_memories(client, tokens):
    headers = auth(tokens, 'alpha:coordinator')
    task = (await client.post('/v1/tasks', headers=headers, json={
        'operation_id': uid(), 'title': 'TEST-CLIENT graph bounded fixture',
        'assigned_agent_ids': ['investigator']})).json()['task_id']
    sid = (await client.post(f'/v1/tasks/{task}/sessions', json={'operation_id': uid()})).json()['session_id']
    for index in range(105):
        turn = await client.post(f'/v1/sessions/{sid}/turns', json={
            'operation_id': uid(), 'role': 'tool', 'content': f'TEST-CLIENT persistent observation {index}'})
        assert turn.status_code == 201
        response = await client.post(f'/v1/tasks/{task}/memories', json={
            'operation_id': uid(), 'session_id': sid, 'source_turn_id': turn.json()['turn_id'],
            'class': 'episodic', 'assertion_type': 'observation', 'status': 'active',
            'content': f'TEST-CLIENT graph fixture {index}'})
        assert response.status_code == 201
    started = time.monotonic()
    result = await client.get(f'/v1/tasks/{task}/graph', params={'limit': 40})
    assert result.status_code == 200, result.text
    graph = result.json()
    assert time.monotonic() - started < 10  # Driver timeout is also 10 seconds per query.
    assert len(graph['memory_page_ids']) == 40 and graph['next_cursor']
    assert len(graph['nodes']) <= 250 and len(graph['edges']) <= 400
    assert graph['bounds']['truncated']
    assert len(graph['queries']) <= 15
    assert all(query['returned_rows'] <= 401 for query in graph['queries'])
    # A small page must not expand the auxiliary Session -> all 105 Turns ->
    # all Memories, which would exhaust the browser cap before paging starts.
    page = (await client.get(f'/v1/tasks/{task}/graph', params={'limit': 2})).json()
    assert len(page['memory_page_ids']) == 2 and page['next_cursor']
    assert len([node for node in page['nodes'] if node['type'] == 'Memory']) == 2
    assert len([node for node in page['nodes'] if node['type'] == 'Turn']) == 2
    assert len(page['nodes']) < 30
    following = (await client.get(f'/v1/tasks/{task}/graph', params={
        'limit': 2, 'before': page['next_cursor']})).json()
    assert len(following['memory_page_ids']) == 2
    assert not set(page['memory_page_ids']) & set(following['memory_page_ids'])
    # Explicit session focus still performs the requested bounded expansion.
    session_view = await client.get(f'/v1/tasks/{task}/graph', params={'focus': sid, 'focus_type': 'Session'})
    assert session_view.status_code == 200
    assert len([node for node in session_view.json()['nodes'] if node['type'] == 'Turn']) > 2


async def test_graph_node_identity_uses_label_and_id_and_scope_checks_actual_nodes(client, db, tokens):
    created, _ = await memory(client)
    mid = created['memory_id']
    principal = TokenAuthenticator().authenticate(tokens['alpha:coordinator'])
    # Node uniqueness is per label, so an authorized Agent may share a raw ID
    # with a Memory without either record or edge being merged in the browser.
    await db.query(principal,
                   'MATCH (t:Task {id:$task}) CREATE (a:Agent {id:$id,role:$role,enabled:true}) '
                   'CREATE (t)-[:ASSIGNED_TO]->(a)',
                   {'task': 'incident_42', 'id': mid, 'role': 'investigator'}, write=True)
    response = await client.get('/v1/tasks/incident_42/graph')
    assert response.status_code == 200, response.text
    graph = response.json()
    collisions = [node for node in graph['nodes'] if node['id'] == mid]
    assert {node['key'] for node in collisions} == {'Agent:' + mid, 'Memory:' + mid}
    assert any(edge['type'] == 'HAS_MEMORY' and edge['target'] == 'Memory:' + mid for edge in graph['edges'])
    assert any(edge['type'] == 'ASSIGNED_TO' and edge['target'] == 'Agent:' + mid for edge in graph['edges'])
    assert (await client.get('/v1/tasks/incident_42/graph', params={'focus': mid})).json() == {'error': {'code': 'AMBIGUOUS_FOCUS'}}
    focus = await client.get('/v1/tasks/incident_42/graph', params={'focus': mid, 'focus_type': 'Memory'})
    assert focus.status_code == 200
    # A same-ID comparison is not sufficient for neighbor authorization. The
    # investigator owns this session in an unassigned OTHER task; its raw ID is
    # deliberately the same as the assigned investigator Agent.
    other = await client.post('/v1/tasks', headers=auth(tokens, 'alpha:coordinator'), json={
        'operation_id': uid(), 'title': 'TEST-CLIENT collision boundary', 'assigned_agent_ids': ['coordinator']})
    await db.query(principal,
                   'MATCH (t:Task {id:$other}),(a:Agent {id:$actor}) '
                   'CREATE (s:Session {id:$id,task_id:$other,agent_id:$actor,status:$status}) '
                   'CREATE (t)-[:HAS_SESSION]->(s) CREATE (a)-[:HAS_SESSION]->(s)',
                   {'other': other.json()['task_id'], 'actor': 'investigator',
                    'id': 'investigator', 'status': 'open'}, write=True)
    focused = await client.get('/v1/tasks/incident_42/graph', params={'focus': 'investigator', 'focus_type': 'Agent'})
    assert focused.status_code == 200, focused.text
    assert 'Session:investigator' not in {node['key'] for node in focused.json()['nodes']}
    assert other.json()['task_id'] not in focused.text
