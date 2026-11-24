import os
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text

from app import (
    ensure_medico_room_assignment_schema,
    ensure_priority_approval_reference_schema,
)


class SchemaMigrationTestCase(unittest.TestCase):
    def test_existing_medico_rows_are_preserved_when_room_column_is_added(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "legacy.db").replace("\\", "/")
            engine = create_engine(f"sqlite:///{database_path}")
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE salas (id INTEGER PRIMARY KEY)")
                    )
                    connection.execute(
                        text(
                            "CREATE TABLE medicos ("
                            "id INTEGER PRIMARY KEY, "
                            "nome_exibicao VARCHAR(100) NOT NULL)"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO medicos (id, nome_exibicao) "
                            "VALUES (1, 'Médico legado')"
                        )
                    )

                ensure_medico_room_assignment_schema(engine)

                columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("medicos")
                }
                self.assertIn("sala_id", columns)
                self.assertTrue(
                    any(
                        index["name"] == "uq_medicos_sala_id" and index["unique"]
                        for index in inspect(engine).get_indexes("medicos")
                    )
                )
                with engine.connect() as connection:
                    migrated = connection.execute(
                        text(
                            "SELECT id, nome_exibicao, sala_id "
                            "FROM medicos WHERE id = 1"
                        )
                    ).one()
                self.assertEqual(migrated.id, 1)
                self.assertEqual(migrated.nome_exibicao, "Médico legado")
                self.assertIsNone(migrated.sala_id)
            finally:
                engine.dispose()

    def test_existing_priority_policy_is_preserved_when_approval_reference_is_added(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "legacy.db").replace("\\", "/")
            engine = create_engine(f"sqlite:///{database_path}")
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "CREATE TABLE politica_prioridade ("
                            "id INTEGER PRIMARY KEY, "
                            "aprovada BOOLEAN NOT NULL, "
                            "categorias_habilitadas JSON NOT NULL, "
                            "aprovada_por_id INTEGER, "
                            "aprovada_em DATETIME, "
                            "atualizada_em DATETIME NOT NULL)"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO politica_prioridade "
                            "(id, aprovada, categorias_habilitadas, atualizada_em) "
                            "VALUES (1, 1, '[]', '2026-01-01 09:00:00')"
                        )
                    )

                ensure_priority_approval_reference_schema(engine)

                columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("politica_prioridade")
                }
                self.assertIn("referencia_aprovacao", columns)
                with engine.connect() as connection:
                    migrated = connection.execute(
                        text(
                            "SELECT id, aprovada, categorias_habilitadas, "
                            "referencia_aprovacao FROM politica_prioridade WHERE id = 1"
                        )
                    ).one()
                self.assertEqual(migrated.id, 1)
                self.assertTrue(migrated.aprovada)
                self.assertEqual(migrated.categorias_habilitadas, "[]")
                self.assertIsNone(migrated.referencia_aprovacao)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
