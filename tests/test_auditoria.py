from datetime import date
import os
import tempfile
import unittest

from app import create_app
from database import db
from database.models import Permissao, RegistroAuditoria, Usuario


class AuditLogViewTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "audit.db").replace("\\", "/")
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )
        self.client = self.app.test_client()
        response = self.client.post(
            "/login",
            data={"identifier": "admin", "password": "Admin@123"},
        )
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_authorized_user_can_review_redacted_audit_events(self):
        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            self.assertIn(
                "consultar_auditoria",
                {permission.codigo for permission in admin.permissoes},
            )
            db.session.add(
                RegistroAuditoria(
                    usuario_id=admin.id,
                    entidade="paciente",
                    entidade_id=42,
                    acao="consultar_prontuario",
                    detalhe="DADO CLINICO QUE NAO DEVE SER EXIBIDO",
                    ip="127.0.0.1",
                )
            )
            db.session.commit()

        hoje = date.today().isoformat()
        response = self.client.get(f"/auditoria?inicio={hoje}&fim={hoje}")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("consultar prontuario", body)
        self.assertIn("paciente #42", body)
        self.assertNotIn("DADO CLINICO QUE NAO DEVE SER EXIBIDO", body)

    def test_user_without_audit_permission_is_denied(self):
        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            audit_permission = Permissao.query.filter_by(
                codigo="consultar_auditoria"
            ).one()
            admin.permissoes.remove(audit_permission)
            db.session.commit()

        response = self.client.get("/auditoria", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

    def test_audit_history_is_paginated(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    RegistroAuditoria(
                        entidade="paciente",
                        entidade_id=record_id,
                        acao="consultar",
                    )
                    for record_id in range(1, 52)
                ]
            )
            db.session.commit()

        hoje = date.today().isoformat()
        response = self.client.get(f"/auditoria?inicio={hoje}&fim={hoje}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Página 1 de 2", response.get_data(as_text=True))
        next_page = self.client.get(
            f"/auditoria?inicio={hoje}&fim={hoje}&page=2"
        )
        self.assertIn("Página 2 de 2", next_page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
