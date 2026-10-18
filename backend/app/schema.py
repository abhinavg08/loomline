import asyncio
from datetime import datetime, timezone
from redis.exceptions import ResponseError

LABELS = ('Agent', 'Task', 'Session', 'Turn', 'Memory', 'Evidence', 'Entity', 'Operation', 'MemoryEvent', 'Handoff', 'InboxItem', 'Subscription', 'WorkClaim', 'MCPCall')


async def bootstrap(db):
    now = datetime.now(timezone.utc).isoformat()
    for tenant, name in db.tenants.items():
        g = db.client.select_graph(name)
        for label in LABELS:
            try:
                await g.query(f'CREATE INDEX FOR (n:{label}) ON (n.id)')
            except ResponseError as exc:
                if 'already indexed' not in str(exc).lower():
                    raise
        for _ in range(200):
            indices = await g.ro_query('CALL db.indexes() YIELD status RETURN status')
            if all(r[0] == 'OPERATIONAL' for r in indices.result_set):
                break
            await asyncio.sleep(.05)
        else:
            raise RuntimeError('Index readiness timed out')
        for label in LABELS:
            try:
                await db.redis.execute_command('GRAPH.CONSTRAINT', 'CREATE', name, 'UNIQUE', 'NODE', label, 'PROPERTIES', 1, 'id')
            except ResponseError as exc:
                if 'already exists' not in str(exc).lower():
                    raise
        for _ in range(200):
            rows = await g.ro_query('CALL db.constraints() YIELD status RETURN status')
            if len(rows.result_set) == len(LABELS) and all(r[0] == 'OPERATIONAL' for r in rows.result_set):
                break
            await asyncio.sleep(.05)
        else:
            raise RuntimeError('Constraint readiness timed out')
        for role in ('investigator', 'verifier', 'coordinator', 'unassigned'):
            agent = role if tenant == 'alpha' else 'beta_' + role
            await g.query('MERGE (a:Agent {id:$id}) ON CREATE SET a.role=$role,a.enabled=true,a.created_at=$now RETURN a.id', {'id': agent, 'role': role, 'now': now})
        await g.query("MERGE (t:Task {id:'incident_42'}) ON CREATE SET t.title=$title,t.status='investigating',t.version=1,t.created_at=$now,t.updated_at=$now RETURN t.id", {'title': tenant + ' synthetic Checkout incident', 'now': now})
        for role in ('investigator', 'verifier', 'coordinator'):
            agent = role if tenant == 'alpha' else 'beta_' + role
            await g.query("MATCH (t:Task {id:'incident_42'}),(a:Agent {id:$id}) MERGE (t)-[:ASSIGNED_TO]->(a)", {'id': agent})
        for entity, label in (('checkout', 'Checkout'), ('payments', 'Payments'), ('deployment-17', 'Deployment-17')):
            await g.query("MATCH (t:Task {id:'incident_42'}) MERGE (e:Entity {id:$id}) ON CREATE SET e.name=$name,e.entity_type='service' MERGE (t)-[:HAS_ENTITY]->(e)", {'id': entity, 'name': label})
        await g.query("MATCH (c:Entity {id:'checkout'}),(p:Entity {id:'payments'}) MERGE (c)-[:DEPENDS_ON]->(p)")
    db.ready = True
