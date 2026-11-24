import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from werkzeug.security import check_password_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = PROJECT_ROOT / "seed_demo.py"


def is_valid_cpf(cpf):
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    first_sum = sum(
        int(digit) * weight
        for digit, weight in zip(cpf[:9], range(10, 1, -1))
    )
    first_digit = 0 if first_sum % 11 < 2 else 11 - first_sum % 11
    second_sum = sum(
        int(digit) * weight
        for digit, weight in zip(cpf[:10], range(11, 1, -1))
    )
    second_digit = 0 if second_sum % 11 < 2 else 11 - second_sum % 11
    return cpf[-2:] == f"{first_digit}{second_digit}"


class DemoSeedScriptTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "demo.db"
        database_uri = "sqlite:///" + database_path.as_posix()
        self.database_path = database_path
        self.environment = os.environ.copy()
        self.environment["APP_ENV"] = "development"
        self.environment["DATABASE_URL"] = database_uri

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_seed(self, *arguments, environment=None):
        return subprocess.run(
            [sys.executable, str(SEED_SCRIPT), *arguments],
            cwd=PROJECT_ROOT,
            env=environment or self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_seed_creates_complete_demo_data_and_can_be_repeated(self):
        for _ in range(2):
            result = self._run_seed("--confirm-clear")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Massa fictícia de demonstração criada", result.stdout)

        with closing(sqlite3.connect(self.database_path)) as connection:
            expected_counts = {
                "usuarios": 6,
                "especialidades": 3,
                "salas": 3,
                "medicos": 3,
                "servicos": 4,
                "pacientes": 8,
                "solicitacoes": 5,
                "validacoes_pagamento_financeiro": 3,
                "agendamentos": 3,
                "senhas": 3,
                "atendimentos": 3,
            }
            for table, expected in expected_counts.items():
                with self.subTest(table=table):
                    actual = connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    self.assertEqual(actual, expected)

            admin_count = connection.execute(
                "SELECT COUNT(*) FROM usuarios WHERE username = 'admin'"
            ).fetchone()[0]
            self.assertEqual(admin_count, 1)
            admin_permission_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM usuario_permissoes
                JOIN usuarios ON usuarios.id = usuario_permissoes.usuario_id
                WHERE usuarios.username = 'admin'
                """
            ).fetchone()[0]
            self.assertGreater(admin_permission_count, 0)

            active_doctors = connection.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT sala_id), SUM(presenca_ativa)
                FROM medicos
                WHERE ativo = 1
                """
            ).fetchone()
            self.assertEqual(active_doctors, (3, 3, 3))

            pending_count = connection.execute(
                "SELECT COUNT(*) FROM solicitacoes "
                "WHERE status = 'aguardando_pagamento'"
            ).fetchone()[0]
            self.assertEqual(pending_count, 2)
            pending_with_doctor_count = connection.execute(
                "SELECT COUNT(*) FROM solicitacoes "
                "WHERE status = 'aguardando_pagamento' AND medico_id IS NOT NULL"
            ).fetchone()[0]
            self.assertEqual(pending_with_doctor_count, 2)

            today = connection.execute(
                "SELECT COUNT(*) FROM validacoes_pagamento_financeiro "
                "WHERE date(data_confirmacao) = date('now', 'localtime')"
            ).fetchone()[0]
            self.assertEqual(today, 3)

            cpf_values = [
                row[0]
                for row in connection.execute("SELECT cpf FROM pacientes").fetchall()
            ]
            self.assertEqual(len(set(cpf_values)), 8)
            self.assertTrue(all(is_valid_cpf(cpf) for cpf in cpf_values))

            finance_password = connection.execute(
                "SELECT senha_hash FROM usuarios WHERE username = 'financeiro'"
            ).fetchone()[0]
            self.assertTrue(check_password_hash(finance_password, "123456"))

            finance_permissions = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT permissoes.codigo
                    FROM permissoes
                    JOIN usuario_permissoes
                      ON usuario_permissoes.permissao_id = permissoes.id
                    JOIN usuarios
                      ON usuarios.id = usuario_permissoes.usuario_id
                    WHERE usuarios.username = 'financeiro'
                    """
                ).fetchall()
            }
            self.assertEqual(
                finance_permissions,
                {"acessar_dashboard", "gerenciar_financeiro", "consultar_servicos"},
            )

    def test_script_requires_confirmation_before_importing_application(self):
        result = self._run_seed()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.database_path.exists())

    def test_script_refuses_production_environment_before_database_access(self):
        production_environment = self.environment.copy()
        production_environment["APP_ENV"] = "production"
        result = self._run_seed(
            "--confirm-clear",
            environment=production_environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APP_ENV=production", result.stderr)
        self.assertFalse(self.database_path.exists())


if __name__ == "__main__":
    unittest.main()
