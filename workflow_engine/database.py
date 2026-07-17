import hashlib
import importlib.resources
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from workflow_engine.errors import PolicyError


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if self.root.drive.lower() != "d:":
            raise PolicyError(f"project root must be on D drive: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.workflow_dir = self.root / ".workflow"
        self.workflow_dir.mkdir(exist_ok=True)
        self.path = self.workflow_dir / "engine.db"

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self):
        connection = self.connect()
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
            migration_dir = importlib.resources.files("workflow_engine").joinpath("migrations")
            migrations = sorted((item for item in migration_dir.iterdir() if item.name.endswith(".sql")), key=lambda item: item.name)
            for item in migrations:
                version = int(item.name.split("_", 1)[0])
                migration = item.read_text(encoding="utf-8")
                checksum = hashlib.sha256(migration.encode("utf-8")).hexdigest()
                row = connection.execute("SELECT checksum FROM schema_migrations WHERE version = ?", (version,)).fetchone()
                if row:
                    if row["checksum"] != checksum:
                        raise RuntimeError(f"migration checksum mismatch: {version}")
                    continue
                connection.executescript(migration)
                connection.execute("INSERT INTO schema_migrations(version, checksum, applied_at) VALUES(?, ?, ?)", (version, checksum, utc_now()))
                connection.commit()
        finally:
            connection.close()

    def read_one(self, query, parameters=()):
        connection = self.connect()
        try:
            return connection.execute(query, parameters).fetchone()
        finally:
            connection.close()

    def read_all(self, query, parameters=()):
        connection = self.connect()
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def event(self, connection, run_id, event_type, payload, task_id=None, attempt_id=None):
        connection.execute(
            "INSERT INTO events(run_id, task_id, attempt_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (run_id, task_id, attempt_id, event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True), utc_now()),
        )
