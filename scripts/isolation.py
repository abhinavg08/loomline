"""Owned temporary namespace helpers; never clear demo graphs or volumes."""
from contextlib import contextmanager
import asyncio
import os
from pathlib import Path
import uuid
from backend.app.config import ROOT,settings
from backend.app.db import Database
from .init_local import provision_tokens


async def delete_owned_graphs(config,namespace):
    if config.loom_graph_namespace!=namespace or not namespace.startswith('test_') or len(namespace)!=21:
        raise RuntimeError('Refusing cleanup outside an owned test namespace')
    db=Database(config)
    try:
        names=await db.client.list_graphs()
        for graph in db.tenants.values():
            if graph not in (f'loom_{namespace}_alpha',f'loom_{namespace}_beta'):raise RuntimeError('Unsafe graph cleanup target')
            if graph in names:await db.redis.execute_command('GRAPH.DELETE',graph)
    finally:await db.close()


@contextmanager
def temporary_runtime():
    namespace='test_'+uuid.uuid4().hex[:16]
    private=ROOT/'.secrets'/namespace
    private.mkdir(parents=True,exist_ok=False,mode=0o700);provision_tokens(private)
    values={'LOOM_GRAPH_NAMESPACE':namespace,'LOOM_AUTH_FILE':str(private/'auth.json'),'LOOM_TOKEN_FILE':str(private/'agent_tokens.json'),'NVIDIA_LIVE_ENABLED':'false'}
    previous={key:os.environ.get(key) for key in values};os.environ.update(values)
    try:yield settings.model_copy(update={'loom_graph_namespace':namespace,'loom_auth_file':values['LOOM_AUTH_FILE'],'nvidia_live_enabled':False})
    finally:
        asyncio.run(delete_owned_graphs(settings.model_copy(update={'loom_graph_namespace':namespace}),namespace))
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        if private.resolve().parent!=(ROOT/'.secrets').resolve():raise RuntimeError('Unsafe private cleanup')
        for name in ('auth.json','agent_tokens.json'):(private/name).unlink()
        private.rmdir()
