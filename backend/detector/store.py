"""Initial SQLite baseline/version persistence, not the complete application DB.

Screenshot bytes must come from a future verified fetcher. Keeping bytes in this
small foundation makes version + screenshot writes atomic; the application phase
will migrate large images to files. No fetching or fabricated browser captures.
"""
import sqlite3
from typing import Optional

from .core import compare, normalize


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS monitors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                last_checked TEXT,
                last_changed TEXT,
                significant_text TEXT
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY,
                monitor_id INTEGER NOT NULL REFERENCES monitors(id),
                captured_at TEXT NOT NULL,
                text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                screenshot BLOB NOT NULL,
                meaningful INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY,
                monitor_id INTEGER NOT NULL REFERENCES monitors(id),
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_id INTEGER REFERENCES snapshots(id)
            );
        """)

    def close(self):
        self.db.close()

    def add_monitor(self, name: str) -> int:
        if not name.strip():
            raise ValueError("name is required")
        with self.db:
            return self.db.execute("INSERT INTO monitors(name) VALUES (?)",
                                   (name.strip(),)).lastrowid

    def record(self, monitor_id: int, *, checked_at: str, status: str,
               text: Optional[str] = None, screenshot: Optional[bytes] = None,
               threshold: float = 0.0) -> Optional[int]:
        """Record an already classified check; failures cannot replace baseline.

        checked_at is a caller-supplied UTC ISO timestamp. Future worker validates
        capture ordering and owns serialized processing for each monitor.
        """
        if status not in {"ok", "error", "blocked"}:
            raise ValueError("invalid check status")
        if status == "ok" and (text is None or not screenshot):
            raise ValueError("successful capture requires text and screenshot")
        with self.db:
            monitor = self.db.execute("SELECT * FROM monitors WHERE id=?",
                                      (monitor_id,)).fetchone()
            if monitor is None:
                raise ValueError("unknown monitor")
            version_id = None
            if status == "ok":
                previous = self.db.execute(
                    "SELECT text FROM snapshots WHERE monitor_id=? ORDER BY id DESC LIMIT 1",
                    (monitor_id,)).fetchone()
                result = compare(previous["text"] if previous else None, text,
                                 significant_baseline=monitor["significant_text"],
                                 threshold=threshold)
                if result.new_version:
                    version_id = self.db.execute(
                        """INSERT INTO snapshots
                        (monitor_id,captured_at,text,content_hash,screenshot,meaningful)
                        VALUES (?,?,?,?,?,?)""",
                        (monitor_id, checked_at, normalize(text), result.content_hash,
                         screenshot, int(result.meaningful))).lastrowid
                if previous is None or result.meaningful:
                    self.db.execute("UPDATE monitors SET significant_text=? WHERE id=?",
                                    (normalize(text), monitor_id))
                if result.meaningful:
                    self.db.execute("UPDATE monitors SET last_changed=? WHERE id=?",
                                    (checked_at, monitor_id))
            self.db.execute("UPDATE monitors SET status=?,last_checked=? WHERE id=?",
                            (status, checked_at, monitor_id))
            self.db.execute("INSERT INTO checks(monitor_id,checked_at,status,snapshot_id) VALUES (?,?,?,?)",
                            (monitor_id, checked_at, status, version_id))
            return version_id
