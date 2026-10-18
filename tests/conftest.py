import json
import uuid
import os
import asyncio

# Set before importing the application; no HTTP field can override this registry.
TEST_NAMESPACE='test_'+uuid.uuid4().hex[:16]
USED_DATABASE=False
os.environ['LOOM_GRAPH_NAMESPACE']=TEST_NAMESPACE
os.environ['NVIDIA_LIVE_ENABLED']='false'
import httpx
import pytest
import pytest_asyncio
from backend.app.config import ROOT,settings
from backend.app.db import Database
from backend.app.main import app
from backend.app.repository import Repository
from backend.app.schema import bootstrap
from scripts.init_local import provision_tokens


@pytest.fixture(scope='session',autouse=True)
def isolated_test_environment():
    private=ROOT/'.secrets'/TEST_NAMESPACE
    private.mkdir(parents=True,exist_ok=False,mode=0o700)
    provision_tokens(private)
    settings.loom_auth_file=str(private/'auth.json')
    os.environ['LOOM_AUTH_FILE']=settings.loom_auth_file
    async def cleanup():
        db=Database()
        try:
            assert settings.loom_graph_namespace==TEST_NAMESPACE and TEST_NAMESPACE.startswith('test_')
            graphs=await db.client.list_graphs()
            for name in db.tenants.values():
                assert name.startswith('loom_'+TEST_NAMESPACE+'_') and name not in ('loom_t_alpha','loom_t_beta')
                if name in graphs:await db.redis.execute_command('GRAPH.DELETE',name)
        finally:await db.close()
    yield private
    if USED_DATABASE:asyncio.run(cleanup())
    assert private.resolve().parent==(ROOT/'.secrets').resolve() and private.name==TEST_NAMESPACE
    for name in ('auth.json','agent_tokens.json'):(private/name).unlink()
    private.rmdir()


def uid(prefix='test'):
    return prefix + '_' + uuid.uuid4().hex


@pytest.fixture
def tokens(isolated_test_environment):
    class SecretTokens(dict):
        def __repr__(self):return '<local demo tokens: REDACTED>'
    return SecretTokens(json.loads((isolated_test_environment / 'agent_tokens.json').read_text()))


@pytest_asyncio.fixture
async def db():
    global USED_DATABASE
    USED_DATABASE=True
    database = Database()
    await bootstrap(database)
    yield database
    await database.close()


@pytest_asyncio.fixture
async def client(db, tokens):
    app.state.db = db
    app.state.repo = Repository(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Authorization':'Bearer '+tokens['alpha:investigator']}) as c:
        yield c


def auth(tokens, role):
    return {'Authorization':'Bearer '+tokens[role]}


async def source(client, headers=None):
    s = await client.post('/v1/tasks/incident_42/sessions', json={'operation_id':uid()}, headers=headers)
    assert s.status_code == 201, s.text
    sid = s.json()['session_id']
    u = await client.post(f'/v1/sessions/{sid}/turns', json={'operation_id':uid(),'role':'tool','content':'Synthetic observation: Checkout errors increased.'}, headers=headers)
    assert u.status_code == 201, u.text
    return sid, u.json()['turn_id']


async def memory(client, headers=None, **changes):
    sid, tid = await source(client, headers)
    body = dict(operation_id=uid(),session_id=sid,source_turn_id=tid,**{'class':'episodic'},assertion_type='observation',status='active',content='Synthetic observation')
    body.update(changes)
    response = await client.post('/v1/tasks/incident_42/memories', json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json(), body
