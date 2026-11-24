from datetime import date
import os
import tempfile
import unittest
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from database import db
from database.models import (
    Agendamento,
    AgendamentoSenha,
    ConfirmacaoPagamento,
    Especialidade,
    HistoricoStatus,
    Medico,
    Paciente,
    Permissao,
    RegistroAuditoria,
    Sala,
    Servico,
    Senha,
    Solicitacao,
    Usuario,
    ValidacaoPagamentoFinanceiro,
)
from services.permissions import permissions_for_profile


class FinanceiroWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "financeiro.db").replace(
            "\\", "/"
        )
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            suffix = uuid4().hex
            specialty = Especialidade(nome=f"Financeiro {suffix[:10]}", ativa=True)
            patient = Paciente(
                nome_completo="Paciente Financeiro",
                cpf=suffix[:11],
                data_nascimento=date(1990, 1, 1),
                telefone="11999999999",
                endereco="Rua Financeiro, 1",
                ativo=True,
            )
            finance_user = Usuario(
                nome_completo="Operador Financeiro",
                email=f"financeiro-{suffix}@example.test",
                username=f"financeiro-{suffix[:12]}",
                senha_hash=generate_password_hash("Finance-Test-123!"),
                perfil="financeiro",
                ativo=True,
            )
            doctor_user = Usuario(
                nome_completo="Médico Financeiro",
                email=f"doctor-finance-{suffix}@example.test",
                username=f"doctor-finance-{suffix[:12]}",
                senha_hash=generate_password_hash("Doctor-Finance-123!"),
                perfil="medico",
                ativo=True,
            )
            room = Sala(
                nome=f"Sala Financeira {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            db.session.add_all([specialty, patient, finance_user, doctor_user, room])
            db.session.flush()
            finance_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(permissions_for_profile("financeiro"))
            ).all()
            doctor_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(permissions_for_profile("medico"))
            ).all()
            doctor = Medico(
                usuario_id=doctor_user.id,
                especialidade_id=specialty.id,
                sala_id=room.id,
                crm=f"FIN-{suffix[:12]}",
                nome_exibicao="Médico Financeiro",
                ativo=True,
                status="disponivel",
                presenca_ativa=True,
            )
            service = Servico(
                nome=f"Consulta Financeira {suffix[:8]}",
                categoria="Consulta",
                valor=180.75,
                ativo=True,
                especialidade_id=specialty.id,
            )
            db.session.add_all([doctor, service])
            db.session.flush()
            request_record = Solicitacao(
                codigo=f"FIN-{suffix[:12]}",
                paciente_id=patient.id,
                servico_id=service.id,
                especialidade_id=specialty.id,
                medico_id=doctor.id,
                valor_snapshot=180.75,
                status="aguardando_pagamento",
            )
            db.session.add(request_record)
            db.session.commit()
            self.finance_username = finance_user.username
            self.doctor_username = doctor_user.username
            self.request_id = request_record.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _login_as(self, username, password):
        response = self.client.post(
            "/login",
            data={"identifier": username, "password": password},
        )
        self.assertEqual(response.status_code, 302)
        return response

    def test_finance_user_confirms_payment_and_releases_patient_to_queue(self):
        login = self._login_as(self.finance_username, "Finance-Test-123!")
        self.assertEqual(login.headers["Location"], "/financeiro")

        socket_client = self.app.extensions["socketio"].test_client(self.app)
        page = self.client.get("/financeiro")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("Paciente Financeiro", body)
        self.assertIn("Financeiro", body)
        self.assertIn("Médico Financeiro", body)
        self.assertIn("Consulta Financeira", body)
        self.assertIn("R$ 180,75", body)

        response = self.client.post(
            f"/financeiro/solicitacoes/{self.request_id}/confirmar",
            data={
                "forma_pagamento": "Pix",
                "referencia": "PIX-REF-001",
                "observacao": "Pagamento recebido no caixa",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pagamento confirmado.", response.get_data(as_text=True))
        self.assertIn("Senha N-", response.get_data(as_text=True))
        self.assertIn("Senhas emitidas", response.get_data(as_text=True))
        self.assertIn("Imprimir senha", response.get_data(as_text=True))
        self.assertIn("R$ 180,75", response.get_data(as_text=True))
        emitted_events = socket_client.get_received()
        self.assertTrue(
            any(
                event["name"] == "fila_atualizada"
                for event in emitted_events
            )
        )
        socket_client.disconnect()

        with self.app.app_context():
            request_record = db.session.get(Solicitacao, self.request_id)
            self.assertEqual(request_record.status, "agendado")
            self.assertEqual(
                request_record.agendamento.medico_id,
                request_record.medico_id,
            )
            self.assertEqual(
                request_record.validacao_pagamento.referencia_financeira,
                "Pix: PIX-REF-001",
            )
            self.assertEqual(
                request_record.validacao_pagamento.responsavel_financeiro,
                "Operador Financeiro",
            )
            self.assertEqual(
                request_record.confirmacao_pagamento.referencia_recibo,
                "PIX-REF-001",
            )
            self.assertEqual(
                request_record.confirmacao_pagamento.origem_confirmacao,
                "financeiro",
            )
            self.assertIn(
                "Forma de pagamento: Pix",
                request_record.confirmacao_pagamento.observacao,
            )
            self.assertEqual(
                Agendamento.query.filter_by(solicitacao_id=self.request_id).count(),
                1,
            )
            self.assertEqual(
                Senha.query.join(AgendamentoSenha)
                .join(Agendamento)
                .filter(Agendamento.solicitacao_id == self.request_id)
                .count(),
                1,
            )
            ticket = (
                Senha.query.join(AgendamentoSenha)
                .join(Agendamento)
                .filter(Agendamento.solicitacao_id == self.request_id)
                .one()
            )
            ticket_id = ticket.id
            self.assertEqual(ticket.numero_ordem, 1)
            self.assertFalse(ticket.prioridade)
            self.assertEqual(
                HistoricoStatus.query.filter_by(
                    solicitacao_id=self.request_id
                ).count(),
                3,
            )
            self.assertTrue(
                RegistroAuditoria.query.filter_by(
                    entidade="solicitacao",
                    entidade_id=self.request_id,
                    acao="validar_pagamento_financeiro",
                ).first()
            )
            self.assertEqual(
                ValidacaoPagamentoFinanceiro.query.filter_by(
                    solicitacao_id=self.request_id
                ).count(),
                1,
            )

        duplicate = self.client.post(
            f"/financeiro/solicitacoes/{self.request_id}/confirmar",
            data={"forma_pagamento": "Pix"},
            follow_redirects=True,
        )
        self.assertIn(
            "não está mais aguardando validação financeira",
            duplicate.get_data(as_text=True),
        )
        with self.app.app_context():
            self.assertEqual(
                ValidacaoPagamentoFinanceiro.query.filter_by(
                    solicitacao_id=self.request_id
                ).count(),
                1,
            )
            self.assertEqual(
                Agendamento.query.filter_by(solicitacao_id=self.request_id).count(),
                1,
            )

        print_response = self.client.get(f"/fila/{ticket_id}/imprimir")
        self.assertEqual(print_response.status_code, 200)
        self.assertIn("Senha de atendimento", print_response.get_data(as_text=True))

        self.client.post("/logout")
        self._login_as(self.doctor_username, "Doctor-Finance-123!")
        queue = self.client.get("/fila")
        self.assertEqual(queue.status_code, 200)
        self.assertIn("Paciente Financeiro", queue.get_data(as_text=True))

    def test_finance_issues_sequential_ticket_numbers(self):
        self._login_as(self.finance_username, "Finance-Test-123!")
        self.client.post(
            f"/financeiro/solicitacoes/{self.request_id}/confirmar",
            data={"forma_pagamento": "Pix"},
        )

        with self.app.app_context():
            original_request = db.session.get(Solicitacao, self.request_id)
            second_request = Solicitacao(
                codigo=f"FIN2-{uuid4().hex[:12]}",
                paciente_id=original_request.paciente_id,
                servico_id=original_request.servico_id,
                especialidade_id=original_request.especialidade_id,
                medico_id=original_request.medico_id,
                valor_snapshot=original_request.valor_snapshot,
                status="aguardando_pagamento",
            )
            db.session.add(second_request)
            db.session.commit()
            second_request_id = second_request.id

        response = self.client.post(
            f"/financeiro/solicitacoes/{second_request_id}/confirmar",
            data={"forma_pagamento": "Dinheiro"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("N-002", response.get_data(as_text=True))
        with self.app.app_context():
            tickets = (
                Senha.query.join(AgendamentoSenha)
                .join(Agendamento)
                .filter(Agendamento.solicitacao_id.in_([self.request_id, second_request_id]))
                .order_by(Senha.numero_ordem.asc())
                .all()
            )
            self.assertEqual([ticket.numero_ordem for ticket in tickets], [1, 2])

    def test_non_finance_profiles_cannot_open_cashier_routes(self):
        self._login_as("admin", "Admin@123")
        response = self.client.get("/financeiro")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")
        response = self.client.post(
            f"/financeiro/solicitacoes/{self.request_id}/confirmar",
            data={"forma_pagamento": "Pix"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                db.session.get(Solicitacao, self.request_id).validacao_pagamento
            )

    def test_admin_can_create_finance_profile_with_restricted_permissions(self):
        self._login_as("admin", "Admin@123")
        form = self.client.get("/usuarios/novo")
        self.assertEqual(form.status_code, 200)
        self.assertIn('value="financeiro"', form.get_data(as_text=True))

        with self.app.app_context():
            finance_permissions = Permissao.query.filter(
                Permissao.codigo.in_(permissions_for_profile("financeiro"))
            ).all()
            permission_ids = [str(permission.id) for permission in finance_permissions]
            permission_codes = {permission.codigo for permission in finance_permissions}

        suffix = uuid4().hex[:12]
        response = self.client.post(
            "/usuarios/novo",
            data={
                "nome_completo": "Novo Operador Financeiro",
                "email": f"novo-financeiro-{suffix}@example.test",
                "username": f"novo-fin-{suffix}",
                "perfil": "financeiro",
                "senha": "Finance-New-123!",
                "ativo": "on",
                "permissoes": permission_ids,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = Usuario.query.filter_by(username=f"novo-fin-{suffix}").one()
            self.assertEqual(user.perfil, "financeiro")
            self.assertEqual(
                {permission.codigo for permission in user.permissoes},
                permission_codes,
            )

    def test_payment_is_saved_when_no_doctor_is_available_immediately(self):
        with self.app.app_context():
            doctor_user = Usuario.query.filter_by(
                username=self.doctor_username
            ).one()
            doctor_user.medico.ativo = False
            db.session.commit()

        self._login_as(self.finance_username, "Finance-Test-123!")
        response = self.client.post(
            f"/financeiro/solicitacoes/{self.request_id}/confirmar",
            data={"forma_pagamento": "Dinheiro"},
            follow_redirects=True,
        )
        self.assertIn(
            "a solicitação está liberada para agendamento",
            response.get_data(as_text=True),
        )
        with self.app.app_context():
            request_record = db.session.get(Solicitacao, self.request_id)
            self.assertEqual(request_record.status, "confirmado")
            self.assertEqual(
                request_record.validacao_pagamento.referencia_financeira,
                "Dinheiro",
            )
            self.assertIsNone(request_record.agendamento)
            self.assertEqual(Senha.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
