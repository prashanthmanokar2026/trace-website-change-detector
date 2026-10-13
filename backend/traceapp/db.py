import sqlite3
import fcntl
from pathlib import Path
from contextlib import contextmanager
from .config import DATA

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS monitors(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, interval INTEGER NOT NULL,
 paused INTEGER NOT NULL DEFAULT 0, public INTEGER NOT NULL DEFAULT 0,
 config TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT 'Waiting for first check',
 last_checked REAL, last_changed REAL, next_due REAL NOT NULL, significant_text TEXT,
 created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions(
 id INTEGER PRIMARY KEY, monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL, captured REAL NOT NULL, text TEXT NOT NULL, hash TEXT NOT NULL,
 image BLOB NOT NULL, geometry TEXT NOT NULL, html TEXT NOT NULL,
 meaningful INTEGER NOT NULL, reason TEXT NOT NULL, masks TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS versions_monitor ON versions(monitor_id,id);
CREATE TABLE IF NOT EXISTS checks(
 id INTEGER PRIMARY KEY, monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE,
 checked REAL NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, version_id INTEGER
);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, monitor_id INTEGER UNIQUE REFERENCES monitors(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'pending', due REAL NOT NULL, lease REAL,
 attempts INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL, token TEXT
);
CREATE TABLE IF NOT EXISTS domains(host TEXT PRIMARY KEY, next_allowed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(
 id INTEGER PRIMARY KEY, monitor_id INTEGER REFERENCES monitors(id) ON DELETE CASCADE,
 version_id INTEGER NOT NULL, channel TEXT NOT NULL, body TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 due REAL NOT NULL, error TEXT, UNIQUE(version_id,channel)
);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, expires REAL NOT NULL, csrf TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''

@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'trace.sqlite', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    # Multiple supervised processes can start together. Serialize schema and WAL
    # initialization before they begin ordinary transactional database access.
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA/'.schema.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('SELECT version FROM schema_version').fetchone()[0]
            if version == 1:
                migration=(Path(__file__).parent/'migrations'/'002_outbox_comparison.sql').read_text()
                for statement in migration.split(';'):
                    if statement.strip(): db.execute(statement)
                version=2
            if version != 2:
                raise RuntimeError('Unsupported database schema; restore compatible application')
