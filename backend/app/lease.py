"""Ephemeral deployment guard on the existing FalkorDB Redis endpoint.

This is not memory persistence or a distributed quota service. It rejects a
second concurrent gateway in the same server-selected graph namespace.
"""
import asyncio
import secrets
import time
from redis.exceptions import RedisError
from .errors import DomainError

RENEW="if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],30) else return 0 end"
RELEASE="if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


class InstanceLease:
    def __init__(self,db,kind):
        self.db=db;self.key='loomline:instance:'+db.config.loom_graph_namespace+':'+kind
        self.token=secrets.token_urlsafe(32);self.deadline=0;self.task=None

    async def acquire(self):
        if not await self.db.redis.set(self.key,self.token,nx=True,ex=30):
            raise DomainError(503,'SINGLE_INSTANCE_REQUIRED')
        self.deadline=time.monotonic()+30
        self.task=asyncio.create_task(self.renew())

    def valid(self):return time.monotonic()<self.deadline

    async def renew(self):
        delay=5
        while True:
            await asyncio.sleep(delay)
            try:
                if not await self.db.redis.eval(RENEW,1,self.key,self.token):
                    self.deadline=0;return
                self.deadline=time.monotonic()+30
                delay=5
            except RedisError:
                if not self.valid():self.deadline=0;return
                delay=1

    async def close(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
        self.deadline=0
        try:await self.db.redis.eval(RELEASE,1,self.key,self.token)
        except RedisError:pass
