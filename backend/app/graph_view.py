"""Bounded, read-only task graphs and collaboration facts from real FalkorDB edges.

These endpoints expose fixed parameterized operations, never a Cypher console.
The graph is a bounded view; task co-membership is not evidence of causality.
"""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re

from fastapi import APIRouter, Depends, Query

from .auth import authenticated
from .errors import DomainError, require
from .models import ID
from .platform import repo
from .repository import AUTH

router = APIRouter()
MAX_NODES, MAX_EDGES = 250, 400
RELATIONSHIPS = {
    'ASSIGNED_TO': 'authorizes this agent for the project, or assigns a handoff recipient',
    'HAS_SESSION': 'contains this recorded session',
    'HAS_TURN': 'contains this explicitly recorded conversation turn',
    'HAS_MEMORY': 'contains this shared memory',
    'CREATED': 'authored this memory using this authenticated identity',
    'DERIVED_FROM': 'records this turn as the memory source',
    'HAS_EVIDENCE': 'contains this evidence record',
    'SUPPORTED_BY': 'links supporting evidence to this memory',
    'CHALLENGED_BY': 'links contrary evidence to this memory',
    'HAS_ENTITY': 'includes this domain entity',
    'ABOUT': 'describes this domain entity',
    'DEPENDS_ON': 'records a domain dependency',
    'SUPERSEDES': 'links a replacement to the earlier memory',
    'HAS_HANDOFF': 'contains this coordination handoff',
    'REFERS_TO': 'includes this memory in the handoff',
    'HAS_CLAIM': 'contains this versioned work claim',
    'RECORDS': 'records a lifecycle change for this memory or claim',
    'ANNOUNCES_HANDOFF': 'records a handoff transition',
    'HAS_MCP_CALL': 'contains this adapter-reported MCP tool invocation',
    'IN_SESSION': 'records the invocation in this session',
}
# An explicit allowlist keeps operational receipts, inbox dispatch internals and
# any future private node property out of the presentation API by default.
COMMON = {'id', 'created_at', 'updated_at', 'task_id', 'status', 'version'}
PROPERTIES = {
    'Task': COMMON | {'title', 'description', 'synthetic', 'demo_run'},
    'Agent': COMMON | {'role', 'enabled'},
    'Session': COMMON | {'agent_id', 'started_at', 'framework', 'framework_version'},
    'Turn': COMMON | {'session_id', 'seq', 'role', 'content', 'tool_name', 'tool_call_id'},
    'Memory': COMMON | {'class', 'assertion_type', 'content', 'steps_json', 'created_by', 'source_turn_id'},
    'Evidence': COMMON | {'source_type', 'source_ref', 'content', 'observed_at'},
    'Entity': COMMON | {'name', 'entity_type'},
    'Handoff': COMMON | {'from_agent_id', 'to_agent_id', 'description'},
    'WorkClaim': COMMON | {'key', 'owner_agent_id', 'state', 'lease_until_ms'},
    'MemoryEvent': COMMON | {'seq', 'type', 'actor_id', 'target_id', 'target_kind',
                            'old_status', 'new_status', 'old_version', 'new_version',
                            'reason', 'owner_agent_id', 'evidence_id'},
    'MCPCall': COMMON | {'seq', 'session_id', 'agent_id', 'tool_name', 'outcome',
                        'error_code', 'duration_ms', 'transport', 'attestation'},
}
DIRECT = 'HAS_MEMORY|HAS_EVIDENCE|HAS_SESSION|HAS_HANDOFF|HAS_CLAIM|HAS_ENTITY|HAS_MCP_CALL|ASSIGNED_TO'
CAUSALITY = ('Edges are persisted FalkorDB relationships. Sharing a task or session does not prove '
             'that a retrieval caused a decision. MCP activity omits arguments and results; '
             'statements about using prior context are agent-reported unless separately evidenced. '
             'Authenticated authorship does not attest which coding application executed.')


def cursor_scope(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


def cursor_encode(at, record_id, scope):
    payload = {'v': 1, 'scope': scope, 'at': at, 'id': record_id}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()


def cursor_decode(value, scope):
    if not value:
        return '9999', '\uffff'
    try:
        decoded = json.loads(base64.b64decode(value.encode(), altchars=b'-_', validate=True))
        require(isinstance(decoded, dict) and decoded.get('v') == 1 and
                decoded.get('scope') == scope and isinstance(decoded.get('at'), str) and
                len(decoded['at']) <= 64 and isinstance(decoded.get('id'), str) and
                re.fullmatch(ID, decoded['id']), 400, 'INVALID_CURSOR')
        return decoded['at'], decoded['id']
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise DomainError(400, 'INVALID_CURSOR') from None


def validate_filters(agent_id, memory_class='', relationship='', since='', focus='', focus_type=''):
    require(not agent_id or re.fullmatch(ID, agent_id), 400, 'INVALID_AGENT_ID')
    require(memory_class in ('', 'episodic', 'semantic', 'procedural'), 400, 'INVALID_MEMORY_CLASS')
    require(not relationship or relationship in RELATIONSHIPS, 400, 'INVALID_RELATIONSHIP')
    require(not focus or re.fullmatch(ID, focus), 400, 'INVALID_FOCUS')
    require(not focus_type or focus_type in PROPERTIES, 400, 'INVALID_FOCUS_TYPE')
    if since:
        try:
            stamp = datetime.fromisoformat(since.replace('Z', '+00:00'))
            require(stamp.tzinfo is not None, 400, 'INVALID_SINCE')
            since = stamp.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            raise DomainError(400, 'INVALID_SINCE') from None
    return since


def present(node, task):
    kind = next((label for label in node.labels or [] if label in PROPERTIES), None)
    if kind is None:
        return None
    props = {key: value for key, value in node.properties.items() if key in PROPERTIES[kind]}
    label = (props.get('title') or props.get('name') or props.get('key') or
             props.get('content') or props.get('description') or props.get('tool_name') or
             props.get('type') or props.get('id', kind))
    record = {'id': props['id'], 'key': kind + ':' + props['id'], 'type': kind,
              'label': str(label)[:100], 'properties': props}
    if kind == 'Memory':
        record['uri'] = f"loom://task/{task}/memory/{props['id']}"
    return record


class Inspection:
    def __init__(self, repository, principal, task):
        self.r, self.p, self.task = repository, principal, task
        self.queries = []

    async def read(self, name, tail, **params):
        rows = await self.r.read(self.p, self.task, tail, **params)
        samples = []
        for row in rows[:5]:
            sample = {}
            for key, value in row.items():
                if hasattr(value, 'properties') and hasattr(value, 'labels'):
                    record = present(value, self.task)
                    if record:
                        sample[key] = {field: record[field] for field in ('key', 'id', 'type', 'label')}
                elif value is None or isinstance(value, (str, int, float, bool)):
                    sample[key] = value
            samples.append(sample)
        self.queries.append({'name': name, 'cypher': AUTH + tail,
                             'parameters': self.r.params(self.p, self.task, **params),
                             'returned_rows': len(rows), 'returned_records': samples,
                             'sample_truncated': len(rows) > 5, 'read_only': True})
        return rows


# Every admitted neighbor must belong to the authorized task. In particular an
# Agent's sessions in another task and a shared Entity's other task are excluded.
def adjacent_query(incoming=False):
    pattern = '(other)-[edge]->(n)' if incoming else '(n)-[edge]->(other)'
    returns = 'other AS source,n AS target' if incoming else 'n AS source,other AS target'
    return (f'UNWIND $ids AS selected MATCH (n) WHERE id(n)=selected MATCH {pattern} '
            'WHERE type(edge) IN $types '
            'OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(member:Agent {id:other.id}) '
            'OPTIONAL MATCH (t)-[:HAS_ENTITY]->(entity:Entity {id:other.id}) '
            'OPTIONAL MATCH (t)-[:HAS_SESSION]->(:Session)-[:HAS_TURN]->(turn:Turn {id:other.id}) '
            'WITH n,other,edge,member,entity,turn '
            'WHERE (other:Task AND other.id=$task) OR other.task_id=$task '
            'OR member=other OR entity=other OR turn=other '
            f'RETURN DISTINCT {returns},type(edge) AS relationship '
            'ORDER BY id(source),relationship,id(target) LIMIT $cap')


@router.get('/v1/tasks/{task}/graph')
async def task_graph(task: str, limit: int = Query(20, ge=1, le=40),
                     before: str = Query('', max_length=1024),
                     agent_id: str = Query('', max_length=128),
                     memory_class: str = Query('', max_length=32),
                     relationship: str = Query('', max_length=40),
                     since: str = Query('', max_length=64), focus: str = Query('', max_length=128),
                     focus_type: str = Query('', max_length=32),
                     p=Depends(authenticated), r=Depends(repo)):
    task_data = await r.authorize(p, task)
    since = validate_filters(agent_id, memory_class, relationship, since, focus, focus_type)
    scope = cursor_scope('graph', p.tenant_id, p.agent_id, task, agent_id,
                         memory_class, relationship, since, focus, focus_type)
    cutoff, last_id = cursor_decode(before, scope)
    q = Inspection(r, p, task)
    nodes, internal_ids, edges = {}, {}, {}
    truncated = False

    def add(node):
        nonlocal truncated
        value = present(node, task)
        if value and value['key'] not in nodes:
            if len(nodes) == MAX_NODES:
                truncated = True
            else:
                nodes[value['key']] = value
                internal_ids[value['key']] = node.id

    def add_rows(rows):
        nonlocal truncated
        for row in rows:
            add(row['source']); add(row['target'])
            source_node, target_node = present(row['source'], task), present(row['target'], task)
            if not source_node or not target_node:
                continue
            source, target, kind = source_node['key'], target_node['key'], row['relationship']
            if source not in nodes or target not in nodes or (relationship and kind != relationship):
                continue
            key = hashlib.sha256(f'{source}:{kind}:{target}'.encode()).hexdigest()[:24]
            if key not in edges:
                if len(edges) == MAX_EDGES:
                    truncated = True
                else:
                    edges[key] = {'id': key, 'source': source, 'target': target, 'type': kind,
                                  'source_id': source_node['id'], 'target_id': target_node['id'],
                                  'source_type': source_node['type'], 'target_type': target_node['type'],
                                  'meaning': RELATIONSHIPS[kind]}

    # Use the actual Task node, not a presentation-only synthesized record.
    for row in await q.read('project', 'RETURN t AS node'):
        add(row['node'])
    members = await q.read('authorized identities',
                          'MATCH (t)-[:ASSIGNED_TO]->(n:Agent) RETURN n AS node ORDER BY n.id LIMIT 101')
    for row in members[:100]:
        add(row['node'])
    truncated |= len(members) > 100
    page, next_cursor = [], None
    if focus:
        # Three fixed paths cover direct task members, turns and task events.
        focused = await q.read('focused project record',
                               f'MATCH (t)-[:{DIRECT}]->(n {{id:$focus}}) '
                               "WHERE $focus_type='' OR $focus_type IN labels(n) RETURN DISTINCT n AS node LIMIT 3",
                               focus=focus, focus_type=focus_type)
        if focus == task and focus_type in ('', 'Task'):
            focused += await q.read('focused project', 'RETURN t AS node')
        focused += await q.read('focused source turn',
                                'MATCH (t)-[:HAS_SESSION]->(:Session)-[:HAS_TURN]->(n:Turn {id:$focus}) '
                                "WHERE $focus_type='' OR $focus_type IN labels(n) RETURN n AS node LIMIT 3",
                                focus=focus, focus_type=focus_type)
        focused += await q.read('focused lifecycle event',
                                'MATCH (n:MemoryEvent {task_id:$task,id:$focus}) '
                                "WHERE $focus_type='' OR $focus_type IN labels(n) RETURN n AS node LIMIT 3",
                                focus=focus, focus_type=focus_type)
        require(focused, 404, 'NOT_FOUND')
        focused = list({row['node'].id: row for row in focused}.values())
        require(len(focused) == 1, 400, 'AMBIGUOUS_FOCUS')
        add(focused[0]['node'])
        seeds = [present(focused[0]['node'], task)['key']]
    else:
        page = await q.read('memory page',
                            'MATCH (t)-[:HAS_MEMORY]->(n:Memory) '
                            "WHERE ($agent='' OR n.created_by=$agent) AND ($class='' OR n.class=$class) "
                            "AND ($since='' OR n.created_at>=$since) "
                            'AND (n.created_at<$cutoff OR (n.created_at=$cutoff AND n.id<$last)) '
                            'RETURN n AS node ORDER BY n.created_at DESC,n.id DESC LIMIT $cap',
                            agent=agent_id, **{'class': memory_class}, since=since,
                            cutoff=cutoff, last=last_id, cap=limit + 1)
        for row in page[:limit]:
            add(row['node'])
        if len(page) > limit:
            last = page[limit - 1]['node'].properties
            next_cursor = cursor_encode(last['created_at'], last['id'], scope)
        # Context records have their own small fixed budget. A filter constrains
        # the primary memories, while real linked neighbors retain their meaning.
        for edge, kind, clock, actor in (
                ('HAS_SESSION', 'Session', 'started_at', 'n.agent_id=$agent'),
                ('HAS_HANDOFF', 'Handoff', 'created_at', '(n.from_agent_id=$agent OR n.to_agent_id=$agent)'),
                ('HAS_CLAIM', 'WorkClaim', 'updated_at', 'n.owner_agent_id=$agent'),
                ('HAS_EVIDENCE', 'Evidence', 'created_at', 'true'),
                ('HAS_MCP_CALL', 'MCPCall', 'created_at', 'n.agent_id=$agent'),
                ('HAS_ENTITY', 'Entity', 'created_at', 'true')):
            rows = await q.read(kind.lower() + ' context',
                                f'MATCH (t)-[:{edge}]->(n:{kind}) '
                                f"WHERE ($agent='' OR {actor}) AND ($since='' OR n.{clock}>=$since) "
                                f'RETURN n AS node ORDER BY n.{clock} DESC,n.id DESC LIMIT 9',
                                agent=agent_id, since=since)
            truncated |= len(rows) > 8
            for row in rows[:8]:
                add(row['node'])
        # Auxiliary sessions/evidence/tool-call records provide project context;
        # expanding them by default would enumerate a long session's turns and
        # then every derived memory, defeating the primary-memory page budget.
        # Users can explicitly focus those record types to explore neighbors.
        seeds = [key for key, value in nodes.items()
                 if value['type'] in ('Memory', 'Handoff', 'WorkClaim')]

    visited = set()
    # Two bounded hops expose source turns -> sessions as well as evidence,
    # lifecycle events and handoffs. No full-tenant scan or fabricated joins.
    for depth in range(2):
        expand = [key for key in seeds if key not in visited]
        if not expand:
            break
        visited.update(expand)
        previous = set(nodes)
        for incoming in (False, True):
            rows = await q.read(f'persisted neighbors hop {depth + 1} ' + ('incoming' if incoming else 'outgoing'),
                                adjacent_query(incoming), ids=[internal_ids[key] for key in expand],
                                types=list(RELATIONSHIPS), cap=MAX_EDGES + 1)
            truncated |= len(rows) > MAX_EDGES
            add_rows(rows[:MAX_EDGES])
        # Follow a memory's source turn back to its session, or an actual linked
        # handoff/replacement memory. A shared evidence record or session is not
        # an invitation to load every other memory associated with it.
        seeds = [key for key in set(nodes) - previous
                 if nodes[key]['type'] in ('Turn', 'Memory', 'Handoff')]
    # Include only stored edges between displayed nodes, e.g. task membership and
    # author CREATED. Crucially an agent is never expanded across all its tasks.
    rows = await q.read('edges between displayed records',
                        'UNWIND $ids AS chosen MATCH (source) WHERE id(source)=chosen MATCH (source)-[edge]->(target) '
                        'WHERE id(target) IN $ids AND type(edge) IN $types '
                        'RETURN source,target,type(edge) AS relationship '
                        'ORDER BY id(source),relationship,id(target) LIMIT $cap',
                        ids=list(internal_ids.values()), types=list(RELATIONSHIPS), cap=MAX_EDGES + 1)
    truncated |= len(rows) > MAX_EDGES
    add_rows(rows[:MAX_EDGES])
    if relationship:
        connected = {'Task:' + task, *([present(focused[0]['node'], task)['key']] if focus else [])}
        for edge in edges.values():
            connected.update((edge['source'], edge['target']))
        nodes = {key: value for key, value in nodes.items() if key in connected}
    return {'task': task_data, 'nodes': list(nodes.values()), 'edges': list(edges.values()),
            'next_cursor': next_cursor, 'queries': q.queries,
            'memory_page_ids': [row['node'].properties['id'] for row in page[:limit]],
            'filters': {'agent_id': agent_id, 'memory_class': memory_class,
                        'relationship': relationship, 'since': since, 'focus': focus, 'focus_type': focus_type},
            'bounds': {'max_nodes': MAX_NODES, 'max_edges': MAX_EDGES,
                       'memory_page_size': limit, 'expansion_hops': 2, 'context_per_type': 8,
                       'truncated': bool(truncated or next_cursor),
                       'scope': 'authorized task; memory filters select seeds, linked context is retained; focus selects a neighborhood'},
            'interpretation': {'causality': CAUSALITY, 'client_verification': 'application verification is separate from identity attribution'},
            'relationship_types': RELATIONSHIPS}


def classification(props, task_data):
    text = ' '.join(str(props.get(key, '')) for key in ('content', 'description', 'source_ref'))
    if task_data.get('synthetic') or task_data.get('demo_run') or re.search(r'\bTEST[- _]CLIENT\b', text, re.I):
        return 'explicit_synthetic_or_test'
    return 'recorded_activity_application_unverified'


def timeline_item(kind, props, task_data):
    actor = props.get('created_by') or props.get('actor_id') or props.get('agent_id')
    at = props.get('created_at') or props.get('started_at') or props.get('updated_at') or ''
    memory_id = props.get('id') if kind == 'Memory' else props.get('target_id') if props.get('target_kind') == 'memory' else None
    if kind == 'Memory':
        title = f"Recorded {props.get('class', '')} memory"
    elif kind == 'Session':
        title = 'Started a recorded session'
    elif kind == 'MCPCall':
        title = props.get('tool_name', 'MCP tool') + ': ' + props.get('outcome', 'reported')
    else:
        title = props.get('type', 'Lifecycle event').replace('_', ' ').lower().capitalize()
        if props.get('new_status'):
            title += ' → ' + props['new_status']
    return {'id': props['id'], 'type': kind, 'actor_id': actor, 'at': at, 'title': title,
            'summary': props.get('content') or props.get('reason') or '',
            'record_id': props['id'], 'session_id': props.get('session_id') or (props['id'] if kind == 'Session' else None),
            'memory_id': memory_id,
            'provenance_ref': f'loom://task/{task_data["id"]}/memory/{memory_id}' if memory_id else None,
            'properties': props, 'classification': classification(props, task_data),
            'evidence_basis': 'authenticated persisted record; content statements are author-reported; application execution not attested'}


@router.get('/v1/tasks/{task}/collaboration')
async def collaboration(task: str, limit: int = Query(40, ge=1, le=100),
                        before: str = Query('', max_length=1024),
                        agent_id: str = Query('', max_length=128),
                        since: str = Query('', max_length=64),
                        p=Depends(authenticated), r=Depends(repo)):
    task_data = await r.authorize(p, task)
    since = validate_filters(agent_id, since=since)
    scope = cursor_scope('collaboration', p.tenant_id, p.agent_id, task, agent_id, since)
    cutoff, last = cursor_decode(before, scope)
    q = Inspection(r, p, task)
    members = await q.read('authorized identities',
                          'MATCH (t)-[:ASSIGNED_TO]->(agent:Agent {enabled:true}) RETURN agent AS node ORDER BY agent.id LIMIT 101')
    counts = {}
    count_queries = {
        'sessions': 'MATCH (t)-[:HAS_SESSION]->(n:Session) RETURN n.agent_id AS actor,count(n) AS count,max(n.started_at) AS last_at ORDER BY actor LIMIT 101',
        'turns': 'MATCH (t)-[:HAS_SESSION]->(s:Session)-[:HAS_TURN]->(n:Turn) RETURN s.agent_id AS actor,count(n) AS count,max(n.created_at) AS last_at ORDER BY actor LIMIT 101',
        'memories': 'MATCH (t)-[:HAS_MEMORY]->(n:Memory)<-[:CREATED]-(author:Agent) RETURN author.id AS actor,count(n) AS count,max(n.created_at) AS last_at ORDER BY actor LIMIT 101',
        'mcp_calls': 'MATCH (t)-[:HAS_MCP_CALL]->(n:MCPCall) RETURN n.agent_id AS actor,count(n) AS count,max(n.created_at) AS last_at ORDER BY actor LIMIT 101',
        'events': 'MATCH (n:MemoryEvent {task_id:$task}) RETURN n.actor_id AS actor,count(n) AS count,max(n.created_at) AS last_at ORDER BY actor LIMIT 101',
    }
    aggregate_truncated = len(members) > 100
    for kind, query in count_queries.items():
        rows = await q.read('contributor ' + kind, query)
        aggregate_truncated |= len(rows) > 100
        for row in rows[:100]:
            if row['actor'] is None:
                continue
            value = counts.setdefault(row['actor'], {'sessions': 0, 'turns': 0, 'memories': 0, 'mcp_calls': 0, 'events': 0, 'last_activity_at': ''})
            value[kind] = row['count']
            value['last_activity_at'] = max(value['last_activity_at'], row['last_at'] or '')
    authorized = []
    for row in members[:100]:
        props = present(row['node'], task)['properties']
        count = counts.get(props['id'], {'sessions': 0, 'turns': 0, 'memories': 0, 'mcp_calls': 0, 'events': 0, 'last_activity_at': ''})
        authorized.append({**props, 'counts': count, 'contributor': any(count[k] > 0 for k in ('turns', 'memories', 'mcp_calls', 'events')),
                           'client_verification': 'not attested by principal name or session metadata',
                           'presence': 'historical recorded activity; no live-presence claim'})
    contributors = [{'id': actor, 'counts': count,
                     'currently_authorized': any(agent['id'] == actor and agent.get('enabled', True) for agent in authorized),
                     'client_verification': 'not attested by principal name or session metadata'}
                    for actor, count in counts.items() if any(count[k] > 0 for k in ('turns', 'memories', 'mcp_calls', 'events'))]
    timeline = []
    for kind, match, clock, actor in (
            ('Memory', 'MATCH (t)-[:HAS_MEMORY]->(n:Memory)', 'n.created_at', 'n.created_by'),
            ('Session', 'MATCH (t)-[:HAS_SESSION]->(n:Session)', 'n.started_at', 'n.agent_id'),
            ('MemoryEvent', 'MATCH (n:MemoryEvent {task_id:$task})', 'n.created_at', 'n.actor_id'),
            ('MCPCall', 'MATCH (t)-[:HAS_MCP_CALL]->(n:MCPCall)', 'n.created_at', 'n.agent_id')):
        tail = (match + f" WHERE ($agent='' OR {actor}=$agent) AND ($since='' OR {clock}>=$since) "
                f'AND ({clock}<$cutoff OR ({clock}=$cutoff AND n.id<$last)) '
                f'RETURN n AS node ORDER BY {clock} DESC,n.id DESC LIMIT $cap')
        rows = await q.read('timeline ' + kind, tail, agent=agent_id, since=since, cutoff=cutoff, last=last, cap=limit + 1)
        for row in rows:
            props = present(row['node'], task)['properties']
            timeline.append(timeline_item(kind, props, task_data))
    timeline.sort(key=lambda item: (item['at'], item['id']), reverse=True)
    cursor = cursor_encode(timeline[limit - 1]['at'], timeline[limit - 1]['id'], scope) if len(timeline) > limit else None
    return {'task': task_data, 'authorized_agents': authorized,
            'contributors': sorted(contributors, key=lambda value: value['id']),
            'timeline': timeline[:limit], 'next_cursor': cursor,
            'counts': {'authorized_agents': len(authorized), 'contributors': len(contributors),
                       'sessions': sum(value['sessions'] for value in counts.values())},
            'bounds': {'timeline_page_size': limit, 'agent_aggregate_limit': 100,
                       'aggregates_truncated': aggregate_truncated},
            'interpretation': CAUSALITY, 'queries': q.queries}
