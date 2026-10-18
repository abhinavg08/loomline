import argparse
import asyncio
from pathlib import Path
import tempfile
import time
import signal
from backend.app.config import settings
from backend.app.db import Database
from backend.app.router import EventRouter,RouterCrash
from backend.app.lease import InstanceLease


def heartbeat():return Path(tempfile.gettempdir())/('loomline-router-'+settings.loom_graph_namespace+'.heartbeat')


async def main(once,crash_after):
    # Docker sends SIGTERM. Let finally release our lease before process exit.
    loop=asyncio.get_running_loop();task=asyncio.current_task()
    try:loop.add_signal_handler(signal.SIGTERM,task.cancel)
    except (NotImplementedError,ValueError):pass  # Windows subprocess termination uses TTL recovery.
    db=Database()
    lease=InstanceLease(db,'router')
    try:
        await lease.acquire()
        router=EventRouter(db)
        while True:
            if not lease.valid():raise RuntimeError('Router instance lease lost')
            result=await router.run_once(crash_after)
            heartbeat().write_text(str(time.time()))
            if once:
                print(result);return
            await asyncio.sleep(.5)
    finally:
        await lease.close()
        await db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--crash-after',type=int)
    parser.add_argument('--health',action='store_true')
    args=parser.parse_args()
    if args.health:
        try:healthy=time.time()-float(heartbeat().read_text())<15
        except (OSError,ValueError):healthy=False
        raise SystemExit(0 if healthy else 1)
    try:asyncio.run(main(args.once,args.crash_after))
    except asyncio.CancelledError:pass
    except RouterCrash:
        print('Controlled router interruption; pending event retained.')
        raise SystemExit(86)
