import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url


def sqlite_database_path(database_url):
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Database backup supports SQLite databases only.")

    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        raise ValueError("A file-based SQLite database is required.")
    return Path(database).expanduser().resolve()


def _validate_database(database_path):
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    connection = sqlite3.connect(str(database_path))
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()

    if result != ("ok",):
        raise ValueError(f"SQLite integrity check failed: {database_path}")


def _copy_database(source_path, destination_path):
    source_connection = sqlite3.connect(str(source_path))
    destination_connection = sqlite3.connect(str(destination_path))
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    _validate_database(destination_path)


def _temporary_path(destination_path):
    return destination_path.with_name(
        f".{destination_path.name}.{uuid.uuid4().hex}.tmp"
    )


def create_database_backup(database_url, destination):
    source_path = sqlite_database_path(database_url)
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("Backup destination must differ from the live database.")
    if destination_path.exists():
        raise FileExistsError(f"Backup already exists: {destination_path}")

    _validate_database(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(destination_path)
    try:
        _copy_database(source_path, temporary_path)
        if destination_path.exists():
            raise FileExistsError(f"Backup already exists: {destination_path}")
        os.replace(temporary_path, destination_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return destination_path


def restore_database(database_url, backup_path, safety_backup_directory):
    database_path = sqlite_database_path(database_url)
    source_path = Path(backup_path).expanduser().resolve()
    if source_path == database_path:
        raise ValueError("Restore source must differ from the live database.")
    _validate_database(source_path)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    safety_backup_path = None
    if database_path.exists():
        safety_backup_path = Path(safety_backup_directory).expanduser().resolve() / (
            f"pre-restore-{uuid.uuid4().hex}.db"
        )
        create_database_backup(database_url, safety_backup_path)

    temporary_path = _temporary_path(database_path)
    try:
        _copy_database(source_path, temporary_path)
        os.replace(temporary_path, database_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return database_path, safety_backup_path


def prune_database_backups(backup_directory, retention_days, now=None):
    if retention_days < 1:
        raise ValueError("Backup retention must be at least one day.")

    directory = Path(backup_directory).expanduser().resolve()
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    candidates = list(directory.glob("clinica-nexo-*.db"))
    candidates.extend(directory.glob("pre-restore-*.db"))
    removed = []

    for candidate in candidates:
        if candidate.is_file() and datetime.fromtimestamp(candidate.stat().st_mtime) < cutoff:
            candidate.unlink()
            removed.append(candidate)

    return removed
