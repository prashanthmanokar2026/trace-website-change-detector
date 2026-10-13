"""Consistent online SQLite backup, including screenshot blobs."""
import argparse
from pathlib import Path
import sqlite3
from traceapp.config import DATA
parser=argparse.ArgumentParser();parser.add_argument('destination');args=parser.parse_args()
target=Path(args.destination)
if target.exists(): raise SystemExit('Refusing to overwrite an existing backup')
if not (DATA/'trace.sqlite').exists(): raise SystemExit('No database to back up')
with sqlite3.connect(DATA/'trace.sqlite') as source, sqlite3.connect(target) as destination:
    source.backup(destination)
target.chmod(0o600)
print('Backup created. Treat it as private: it includes owner captures and session records.')
