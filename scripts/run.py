"""Local process runner; Ctrl-C stops all children. Not a production supervisor."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
root=Path(__file__).resolve().parents[1]
os.chdir(root)
env={**os.environ,'PYTHONPATH':str(root/'backend')}
commands=[['-m','traceapp.proxy'],['-m','traceapp.worker'],['-m','traceapp.worker','--notifications'],
          ['-m','uvicorn','traceapp.api:app','--host','127.0.0.1','--port','8000','--no-access-log']]
children=[]
def stop(*args): raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,stop)
try:
    for command in commands: children.append(subprocess.Popen([sys.executable,*command],env=env))
    print('Trace: http://127.0.0.1:8000 — Ctrl-C stops the API, worker, notifier and proxy.',flush=True)
    while all(p.poll() is None for p in children): time.sleep(1)
    if any(p.poll() not in (None,0) for p in children): raise RuntimeError('A Trace process stopped; inspect the message above')
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children:
        try: child.wait(timeout=8)
        except subprocess.TimeoutExpired: child.kill();child.wait()
