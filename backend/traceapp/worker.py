import asyncio
import fcntl
from .config import DATA
from .db import init
from .capture import Renderer
from .queue import schedule,claim,complete
from .notify import deliver_one

async def tick(renderer):
    schedule()
    jobs=claim()
    if jobs:
        try:
            captured=await renderer.capture(jobs[0]['url'])
        except Exception as exc:
            for job in jobs: complete(job,error=exc)
        else:
            for job in jobs: complete(job,capture=captured)
    return bool(jobs)

async def main():
    init()
    with (DATA/'worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        renderer=Renderer()
        while True:
            try:
                await tick(renderer)
            except Exception:
                print('Worker cycle failed; durable work will recover',flush=True)
            await asyncio.sleep(2)

async def notifications():
    init()
    while True:
        await deliver_one()
        await asyncio.sleep(2)

if __name__=='__main__':
    import sys
    asyncio.run(notifications() if '--notifications' in sys.argv else main())
