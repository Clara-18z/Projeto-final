from contextlib import closing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta

from services.database_backup import (
    create_database_backup,
    prune_database_backups,
    restore_database,
)


class DatabaseBackupTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        self.database_path = os.path.join(self.root, "clinic.db")
        normalized_path = self.database_path.replace("\\", "/")
        self.database_url = f"sqlite:///{normalized_path}"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
            connection.execute("INSERT INTO records (value) VALUES ('before')")
            connection.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _values(self, database_path):
        with closing(sqlite3.connect(database_path)) as connection:
            return connection.execute("SELECT value FROM records").fetchall()

    def test_backup_captures_consistent_database_copy(self):
        backup_path = os.path.join(self.root, "backups", "clinic.db")
        created_path = create_database_backup(self.database_url, backup_path)

        self.assertEqual(created_path, Path(backup_path).resolve())
        self.assertEqual(self._values(backup_path), [("before",)])

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("INSERT INTO records (value) VALUES ('after')")
            connection.commit()
        self.assertEqual(self._values(backup_path), [("before",)])

    def test_restore_saves_current_database_before_replacing_it(self):
        backup_path = os.path.join(self.root, "backups", "snapshot.db")
        create_database_backup(self.database_url, backup_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("INSERT INTO records (value) VALUES ('after')")
            connection.commit()

        restored_path, safety_backup_path = restore_database(
            self.database_url,
            backup_path,
            os.path.join(self.root, "backups"),
        )

        self.assertEqual(restored_path, Path(self.database_path).resolve())
        self.assertTrue(os.path.isfile(safety_backup_path))
        self.assertEqual(self._values(self.database_path), [("before",)])
        self.assertEqual(self._values(safety_backup_path), [("before",), ("after",)])

    def test_restore_rejects_invalid_backup_without_changing_live_database(self):
        invalid_backup = os.path.join(self.root, "invalid.db")
        with open(invalid_backup, "wb") as backup_file:
            backup_file.write(b"not a sqlite database")

        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            restore_database(
                self.database_url,
                invalid_backup,
                os.path.join(self.root, "backups"),
            )
        self.assertEqual(self._values(self.database_path), [("before",)])

    def test_retention_removes_only_managed_backups_past_the_age_limit(self):
        backup_directory = Path(self.root, "backups")
        backup_directory.mkdir()
        expired_backup = backup_directory / "clinica-nexo-expired.db"
        expired_restore = backup_directory / "pre-restore-expired.db"
        recent_backup = backup_directory / "clinica-nexo-recent.db"
        unrelated_file = backup_directory / "manual-export.db"
        for path in (
            expired_backup,
            expired_restore,
            recent_backup,
            unrelated_file,
        ):
            path.write_bytes(b"test")

        old_timestamp = (datetime.now() - timedelta(days=31)).timestamp()
        os.utime(expired_backup, (old_timestamp, old_timestamp))
        os.utime(expired_restore, (old_timestamp, old_timestamp))

        removed = prune_database_backups(backup_directory, 30)

        self.assertEqual(set(removed), {expired_backup.resolve(), expired_restore.resolve()})
        self.assertTrue(recent_backup.exists())
        self.assertTrue(unrelated_file.exists())

    def test_retention_requires_a_positive_number_of_days(self):
        with self.assertRaisesRegex(ValueError, "at least one day"):
            prune_database_backups(self.root, 0)


if __name__ == "__main__":
    unittest.main()
