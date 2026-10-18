import asyncio
from backend.app.db import Database
from backend.app.schema import bootstrap


async def main():
    db = Database()
    try:
        await bootstrap(db)
        config = await db.redis.config_get('appendonly', 'appendfsync', 'dir')
        print({'schema': 'ready', 'persistence': config, 'server': (await db.redis.info('server'))['redis_version']})
    finally:
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())
