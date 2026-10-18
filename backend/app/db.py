import asyncio
from falkordb.asyncio import FalkorDB
from redis.asyncio import Redis
from .config import settings
from .errors import DomainError


class Database:
    def __init__(self,config=None):
        self.config=config or settings
        self.tenants=self.config.tenant_graphs
        self.redis = Redis(host=self.config.falkordb_host, port=self.config.falkordb_port,
                           password=self.config.falkordb_password, max_connections=64,
                           socket_timeout=15, socket_connect_timeout=5, decode_responses=True)
        self.client = FalkorDB(connection_pool=self.redis.connection_pool)
        # The pinned image reports MAX_QUEUED_QUERIES=25. Keep headroom for
        # router/health traffic instead of overflowing its global pending queue.
        self.slots = asyncio.Semaphore(16)
        self.ready = False

    def graph(self, principal):
        from .auth import TenantContext
        if not isinstance(principal,TenantContext) or principal.tenant_id not in self.tenants:
            raise DomainError(401,'UNAUTHENTICATED')
        return self.client.select_graph(self.tenants[principal.tenant_id])

    async def query(self, principal, query, params=None, *, write=False):
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=3)
        except TimeoutError:
            raise DomainError(429, 'OVERLOADED') from None
        try:
            graph = self.graph(principal)
            method = graph.query if write else graph.ro_query
            result = await method(query, params or {}, timeout=10000)
            return [dict(zip([h[1] for h in result.header], row)) for row in result.result_set]
        finally:
            self.slots.release()

    async def close(self):
        await self.redis.aclose()
