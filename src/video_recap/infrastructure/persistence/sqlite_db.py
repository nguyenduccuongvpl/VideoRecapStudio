"""SQLite connection lifecycle, transactions, and schema migration manager."""

import datetime
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# --- SQL Schema Migrations ---

MIGRATIONS = {
    "1": """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            source_video_path TEXT NOT NULL,
            output_directory TEXT NOT NULL,
            preset_name TEXT NOT NULL,
            target_recap_duration REAL NOT NULL,
            voice_name TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            state TEXT NOT NULL,
            current_stage TEXT,
            error_details TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS stage_runs (
            job_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            error_message TEXT,
            PRIMARY KEY(job_id, stage_name),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS artifacts (
            project_id TEXT NOT NULL,
            category TEXT NOT NULL,
            filename TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            producer_stage TEXT NOT NULL,
            path TEXT NOT NULL,
            input_hashes TEXT NOT NULL,
            PRIMARY KEY(project_id, category, filename),
            FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS provider_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            latency_ms REAL NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            cost_usd REAL NOT NULL,
            request_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS qa_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            finding_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
    """
}


class DatabaseManager:
    """Manages SQLite connection lifecycle, WAL settings, and thread safety."""

    def __init__(self, db_path: Path | str) -> None:
        """Initialize database manager.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a thread-safe sqlite3 Connection with WAL and Foreign Keys enabled.

        Yields:
            The sqlite3 connection instance.
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            # Enable WAL mode for high performance concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            # Enable Foreign Key enforcement
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Execute a block within an explicit SQL Transaction.

        Automatically commits on success or rolls back on exception.

        Yields:
            The transaction connection instance.
        """
        with self.connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE TRANSACTION")
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e


def run_migrations(db_mgr: DatabaseManager) -> None:
    """Execute all pending SQL migrations to synchronize database schema.

    Args:
        db_mgr: The DatabaseManager instance.
    """
    with db_mgr.connection() as conn:
        # Create migrations table if not exists
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_migrations (version TEXT PRIMARY KEY, migrated_at TEXT NOT NULL)"
        )
        cursor = conn.execute("SELECT version FROM app_migrations")
        migrated_versions = {row["version"] for row in cursor.fetchall()}

    for version, sql in sorted(MIGRATIONS.items(), key=lambda item: int(item[0])):
        if version not in migrated_versions:
            # Run migration in a separate transaction block
            with db_mgr.transaction() as conn:
                conn.executescript(sql)
                utc_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO app_migrations (version, migrated_at) VALUES (?, ?)",
                    (version, utc_now),
                )
