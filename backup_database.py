import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

from config import Config
from services.database_backup import (
    create_database_backup,
    prune_database_backups,
    restore_database,
)


DEFAULT_BACKUP_DIRECTORY = Path(Config.BACKUP_DIRECTORY)


def _default_backup_name():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return DEFAULT_BACKUP_DIRECTORY / f"clinica-nexo-{timestamp}.db"


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("retention must be a positive number of days") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("retention must be at least one day")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup or restore the SQLite database.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a consistent backup.")
    backup_parser.add_argument("--output", type=Path, help="Backup file path.")
    backup_parser.add_argument(
        "--retain-days",
        type=_positive_int,
        help="After a successful backup, remove managed backups older than this many days.",
    )

    restore_parser = subparsers.add_parser(
        "restore", help="Restore a backup while the application is stopped."
    )
    restore_parser.add_argument("backup_file", type=Path, help="SQLite backup to restore.")
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm replacing the live database.",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            destination = args.output or _default_backup_name()
            backup = create_database_backup(
                Config.SQLALCHEMY_DATABASE_URI,
                destination,
            )
            print(f"Backup created: {backup}")
            if args.retain_days is not None:
                removed = prune_database_backups(
                    DEFAULT_BACKUP_DIRECTORY,
                    args.retain_days,
                )
                print(f"Expired backups removed: {len(removed)}")
            return 0

        if not args.confirm:
            parser.error("restore requires --confirm because it replaces the live database.")
        database_path, safety_backup_path = restore_database(
            Config.SQLALCHEMY_DATABASE_URI,
            args.backup_file,
            DEFAULT_BACKUP_DIRECTORY,
        )
        print(f"Database restored: {database_path}")
        if safety_backup_path:
            print(f"Pre-restore backup: {safety_backup_path}")
        return 0
    except (FileExistsError, FileNotFoundError, OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
