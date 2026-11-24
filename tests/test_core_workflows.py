from datetime import date, datetime, time, timedelta
import os
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from werkzeug.security import generate_password_hash

from app import create_app, ensure_medico_presence_schema
from database import db
from database.models import (
    Agendamento,
    AgendamentoSenha,
    AusenciaMedica,
    ConfirmacaoPagamento,
    DisponibilidadeMedica,
    Especialidade,
    JustificativaAusenciaMedica,
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


class CoreWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "core.db").replace("\\", "/")
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
            self.specialty = Especialidade(nome=f"Especialidade {suffix[:8]}", ativa=True)
            self.patient = Paciente(
                nome_completo="Paciente de Teste",
                cpf="12345678909",
                data_nascimento=date(1990, 1, 1),
                telefone="11999999999",
                endereco="Rua de Teste, 10",
                ativo=True,
            )
            self.staff_user = Usuario(
                nome_completo="Médico de Teste",
                email=f"medico-{suffix}@example.test",
                username=f"medico-{suffix[:12]}",
                senha_hash=generate_password_hash("Doctor-Core-Test-123!"),
                perfil="medico",
                ativo=True,
            )
            self.receptionist_user = Usuario(
                nome_completo="Recepcionista de Teste",
                email=f"recepcao-core-{suffix}@example.test",
                username=f"recepcao-core-{suffix[:12]}",
                senha_hash=generate_password_hash("Reception-Core-Test-123!"),
                perfil="recepcionista",
                ativo=True,
            )
            self.finance_user = Usuario(
                nome_completo="Operador Financeiro",
                email=f"financeiro-core-{suffix}@example.test",
                username=f"financeiro-core-{suffix[:12]}",
                senha_hash=generate_password_hash("Finance-Core-Test-123!"),
                perfil="financeiro",
                ativo=True,
            )
            db.session.add_all(
                [
                    self.specialty,
                    self.patient,
                    self.staff_user,
                    self.receptionist_user,
                    self.finance_user,
                ]
            )
            db.session.flush()
            self.staff_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "consultar_servicos",
                        "gerenciar_agenda",
                        "gerenciar_atendimento",
                    }
                )
            ).all()
            self.receptionist_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "gerenciar_pacientes",
                        "consultar_servicos",
                        "gerenciar_solicitacoes",
                        "gerenciar_agenda",
                        "gerenciar_fila",
                    }
                )
            ).all()
            self.finance_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(permissions_for_profile("financeiro"))
            ).all()
            self.doctor = Medico(
                usuario_id=self.staff_user.id,
                especialidade_id=self.specialty.id,
                crm=f"CORE-{suffix[:12]}",
                nome_exibicao="Médico de Teste",
                ativo=True,
                status="disponivel",
                presenca_ativa=True,
            )
            self.room = Sala(
                nome=f"Sala Core {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            self.doctor.sala = self.room
            self.alternate_room = Sala(
                nome=f"Sala Alternativa {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            self.service = Servico(
                nome=f"Consulta Core {suffix[:8]}",
                categoria="Consulta",
                valor=125.50,
                ativo=True,
                especialidade_id=self.specialty.id,
            )
            db.session.add_all(
                [self.doctor, self.room, self.alternate_room, self.service]
            )
            db.session.commit()
            self.specialty_id = self.specialty.id
            self.patient_id = self.patient.id
            self.doctor_id = self.doctor.id
            self.room_id = self.room.id
            self.alternate_room_id = self.alternate_room.id
            self.service_id = self.service.id
            self.doctor_user_id = self.staff_user.id
            self.doctor_username = self.staff_user.username
            self.receptionist_username = self.receptionist_user.username
            self.finance_username = self.finance_user.username

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

    def test_existing_database_adds_presence_column_without_resetting_records(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("CREATE TABLE medicos (id INTEGER PRIMARY KEY)")
                )
                connection.execute(text("INSERT INTO medicos (id) VALUES (17)"))

            ensure_medico_presence_schema(engine)

            columns = {
                column["name"] for column in inspect(engine).get_columns("medicos")
            }
            self.assertIn("presenca_ativa", columns)
            with engine.connect() as connection:
                record = connection.execute(
                    text("SELECT id, presenca_ativa FROM medicos WHERE id = 17")
                ).one()
            self.assertEqual(record, (17, 0))
        finally:
            engine.dispose()

    def _login_as_receptionist(self):
        self.client.post("/logout")
        response = self.client.post(
            "/login",
            data={
                "identifier": self.receptionist_username,
                "password": "Reception-Core-Test-123!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _login_as_finance(self):
        self.client.post("/logout")
        response = self.client.post(
            "/login",
            data={
                "identifier": self.finance_username,
                "password": "Finance-Core-Test-123!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _create_request(self, paid=False):
        with self.app.app_context():
            suffix = uuid4().hex
            request_record = Solicitacao(
                codigo=f"CORE-{suffix[:16]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                valor_snapshot=125.50,
                status="confirmado" if paid else "aguardando_pagamento",
            )
            db.session.add(request_record)
            db.session.flush()
            if paid:
                admin_id = Usuario.query.filter_by(username="admin").one().id
                db.session.add(
                    ValidacaoPagamentoFinanceiro(
                        solicitacao_id=request_record.id,
                        referencia_financeira=f"REC-{suffix[:10]}",
                        responsavel_financeiro="Equipe Financeira",
                        data_confirmacao=datetime.now(),
                        registrada_por_id=admin_id,
                    )
                )
            db.session.commit()
            return request_record.id

    def test_delete_actions_are_available_and_unlinked_records_can_be_removed(self):
        with self.app.app_context():
            suffix = uuid4().hex
            specialty = Especialidade(nome=f"Excluir {suffix[:8]}", ativa=True)
            room = Sala(
                nome=f"Sala Excluir {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            patient = Paciente(
                nome_completo="Paciente sem histórico",
                cpf=suffix[:11],
                data_nascimento=date(1990, 1, 1),
                telefone="11999999999",
                endereco="Rua de Teste",
                ativo=True,
            )
            user = Usuario(
                nome_completo="Usuário sem histórico",
                email=f"sem-historico-{suffix}@example.test",
                username=f"sem-historico-{suffix[:10]}",
                senha_hash=generate_password_hash("No-History-123!"),
                perfil="recepcionista",
                ativo=True,
            )
            db.session.add_all([specialty, room, patient, user])
            db.session.flush()
            service = Servico(
                nome=f"Serviço Excluir {suffix[:8]}",
                categoria="Consulta",
                valor=50.0,
                ativo=True,
                especialidade_id=specialty.id,
            )
            db.session.add(service)
            db.session.commit()
            ids = {
                "specialty": specialty.id,
                "room": room.id,
                "patient": patient.id,
                "user": user.id,
                "service": service.id,
            }

        pages = (
            ("/especialidades", f"/especialidades/{ids['specialty']}/excluir"),
            ("/medicos", f"/medicos/{self.doctor_id}/excluir"),
            ("/salas", f"/salas/{ids['room']}/excluir"),
            ("/servicos", f"/servicos/{ids['service']}/excluir"),
            ("/usuarios", f"/usuarios/{ids['user']}/excluir"),
        )
        for path, action in pages:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(action, response.get_data(as_text=True))
                self.assertIn("Excluir", response.get_data(as_text=True))

        self.assertEqual(self.client.post(f"/servicos/{ids['service']}/excluir").status_code, 302)
        self.assertEqual(
            self.client.post(f"/especialidades/{ids['specialty']}/excluir").status_code,
            302,
        )
        self.assertEqual(self.client.post(f"/salas/{ids['room']}/excluir").status_code, 302)
        self.assertEqual(self.client.post(f"/usuarios/{ids['user']}/excluir").status_code, 302)

        self._login_as_receptionist()
        patient_page = self.client.get("/pacientes")
        self.assertIn(f"/pacientes/{ids['patient']}/excluir", patient_page.get_data(as_text=True))
        deleted_patient = self.client.post(f"/pacientes/{ids['patient']}/excluir")
        self.assertEqual(deleted_patient.status_code, 302)

        with self.app.app_context():
            self.assertIsNone(db.session.get(Servico, ids["service"]))
            self.assertIsNone(db.session.get(Especialidade, ids["specialty"]))
            self.assertIsNone(db.session.get(Sala, ids["room"]))
            self.assertIsNone(db.session.get(Usuario, ids["user"]))
            self.assertIsNone(db.session.get(Paciente, ids["patient"]))
            self.assertEqual(
                RegistroAuditoria.query.filter_by(
                    entidade="servico",
                    entidade_id=ids["service"],
                    acao="excluir",
                ).count(),
                1,
            )

    def test_delete_is_blocked_for_linked_records_and_connected_admin(self):
        request_id = self._create_request(paid=True)
        with self.app.app_context():
            db.session.add(
                Agendamento(
                    solicitacao_id=request_id,
                    paciente_id=self.patient_id,
                    medico_id=self.doctor_id,
                    sala_id=self.room_id,
                    data_hora=datetime.now() + timedelta(days=1),
                    status="agendado",
                )
            )
            last_admin = Usuario.query.filter_by(username="admin").one()
            admin_id = last_admin.id
            db.session.commit()

        for path in (
            f"/servicos/{self.service_id}/excluir",
            f"/especialidades/{self.specialty_id}/excluir",
            f"/medicos/{self.doctor_id}/excluir",
            f"/salas/{self.room_id}/excluir",
            f"/usuarios/{self.doctor_user_id}/excluir",
        ):
            with self.subTest(path=path):
                response = self.client.post(path, follow_redirects=True)
                self.assertIn("preservar", response.get_data(as_text=True).lower())

        self._login_as_receptionist()
        patient_delete = self.client.post(
            f"/pacientes/{self.patient_id}/excluir",
            follow_redirects=True,
        )
        self.assertIn("preservar", patient_delete.get_data(as_text=True).lower())
        self.client.post("/logout")
        self.client.post(
            "/login",
            data={"identifier": "admin", "password": "Admin@123"},
        )

        self_delete = self.client.post(
            f"/usuarios/{admin_id}/excluir",
            follow_redirects=True,
        )
        self.assertIn(
            "própria conta conectada",
            self_delete.get_data(as_text=True),
        )
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Paciente, self.patient_id))
            self.assertIsNotNone(db.session.get(Servico, self.service_id))
            self.assertIsNotNone(db.session.get(Especialidade, self.specialty_id))
            self.assertIsNotNone(db.session.get(Medico, self.doctor_id))
            self.assertIsNotNone(db.session.get(Sala, self.room_id))
            self.assertIsNotNone(db.session.get(Usuario, self.doctor_user_id))
            self.assertIsNotNone(db.session.get(Usuario, admin_id))

    def test_patient_registration_normalizes_cpf_and_blocks_duplicates(self):
        self._login_as_receptionist()
        cpf = "987.654.321-00"
        response = self.client.post(
            "/pacientes/novo",
            data={
                "nome_completo": "Joana Teste",
                "cpf": cpf,
                "data_nascimento": "1985-04-03",
                "telefone": "11988887777",
                "endereco": "Avenida Central, 20",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            patient = Paciente.query.filter_by(cpf="98765432100").first()
            self.assertIsNotNone(patient)
            self.assertIsNone(patient.email)

        response = self.client.post(
            "/pacientes/novo",
            data={
                "nome_completo": "Outra Joana",
                "cpf": "98765432100",
                "data_nascimento": "1985-04-03",
                "telefone": "11988887777",
                "endereco": "Avenida Central, 20",
            },
            follow_redirects=True,
        )
        self.assertIn("Paciente já cadastrado", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Paciente.query.filter_by(cpf="98765432100").count(), 1)

    def test_patient_accesses_and_changes_are_audited_without_sensitive_payload(self):
        self._login_as_receptionist()
        with self.app.app_context():
            patient = db.session.get(Paciente, self.patient_id)
            patient.email = "legado@example.test"
            db.session.commit()

        response = self.client.get("/pacientes")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/pacientes/{self.patient_id}/editar")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="email"', response.get_data(as_text=True))
        response = self.client.post(
            f"/pacientes/{self.patient_id}/editar",
            data={
                "nome_completo": "Paciente Atualizado",
                "cpf": "12345678909",
                "data_nascimento": "1990-01-01",
                "telefone": "11999999999",
                "endereco": "Rua de Teste, 10",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            self.assertEqual(
                db.session.get(Paciente, self.patient_id).email,
                "legado@example.test",
            )
            events = RegistroAuditoria.query.filter_by(
                entidade="paciente",
                entidade_id=self.patient_id,
            ).all()
            actions = {event.acao for event in events}
            self.assertIn("consultar", actions)
            self.assertIn("alterar", actions)
            self.assertTrue(all(event.usuario_id is not None for event in events))
            self.assertTrue(all(event.detalhe is None for event in events))

    def test_service_catalog_parses_brazilian_currency(self):
        response = self.client.post(
            "/servicos/novo",
            data={
                "nome": "Exame de Teste",
                "categoria": "Exame",
                "valor": "1.234,56",
                "especialidade_id": str(self.specialty_id),
                "ativo": "on",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            service = Servico.query.filter_by(nome="Exame de Teste").one()
            self.assertAlmostEqual(service.valor, 1234.56)

    def test_service_catalog_is_admin_only_and_reception_sees_price_after_selection(self):
        self.assertIn("gerenciar_servicos", permissions_for_profile("administrador"))
        self.assertNotIn("consultar_servicos", permissions_for_profile("recepcionista"))
        self.assertNotIn("consultar_servicos", permissions_for_profile("medico"))
        self.assertEqual(self.client.get("/servicos").status_code, 200)

        self._login_as_receptionist()
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn('href="/servicos"', dashboard)
        for path in (
            "/servicos",
            "/servicos/novo",
            f"/servicos/{self.service_id}/editar",
        ):
            with self.subTest(profile="recepcionista", path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/dashboard")
        response = self.client.post(f"/servicos/{self.service_id}/toggle")
        self.assertEqual(response.status_code, 302)

        intake = self.client.get("/solicitacoes/nova")
        intake_body = intake.get_data(as_text=True)
        self.assertEqual(intake.status_code, 200)
        self.assertIn('data-valor="125.50"', intake_body)
        self.assertIn('id="servico-valor"', intake_body)
        self.assertIn("hidden", intake_body.split('id="servico-valor"', 1)[1].split(">", 1)[0])
        self.assertNotIn("R$ 125,50", intake_body)

        self.client.post("/logout")
        doctor_login = self.client.post(
            "/login",
            data={
                "identifier": self.doctor_username,
                "password": "Doctor-Core-Test-123!",
            },
        )
        self.assertEqual(doctor_login.status_code, 302)
        self.assertEqual(doctor_login.headers["Location"], "/dashboard")
        doctor_dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn('href="/servicos"', doctor_dashboard)
        for path in (
            "/servicos",
            "/servicos/novo",
            f"/servicos/{self.service_id}/editar",
        ):
            with self.subTest(profile="medico", path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/dashboard")
        response = self.client.post(f"/servicos/{self.service_id}/toggle")
        self.assertEqual(response.status_code, 302)

    def test_request_payment_confirmation_preserves_price_snapshot(self):
        self._login_as_receptionist()
        with self.app.app_context():
            service = db.session.get(Servico, self.service_id)
            service.valor = 200.00
            db.session.commit()

        response = self.client.post(
            "/solicitacoes/nova",
            data={
                "paciente_id": str(self.patient_id),
                "servico_id": str(self.service_id),
                "medico_id": str(self.doctor_id),
                "observacoes": "Solicitação para teste",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            request_record = Solicitacao.query.one()
            request_id = request_record.id
            self.assertEqual(request_record.status, "aguardando_pagamento")
            self.assertEqual(request_record.medico_id, self.doctor_id)
            self.assertAlmostEqual(request_record.valor_snapshot, 200.00)
            service = db.session.get(Servico, self.service_id)
            service.valor = 300.00
            db.session.commit()

        blocked_confirmation = self.client.post(
            f"/solicitacoes/{request_id}/confirmar-pagamento",
            data={
                "referencia_recibo": "REC-CORE-1",
                "responsavel": "Equipe Financeira",
                "data_confirmacao": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(blocked_confirmation.headers["Location"], "/dashboard")
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Solicitacao, request_id).status,
                "aguardando_pagamento",
            )
            self.assertIsNone(
                db.session.get(Solicitacao, request_id).validacao_pagamento
            )

        self._login_as_finance()
        response = self.client.post(
            f"/financeiro/solicitacoes/{request_id}/confirmar",
            data={
                "forma_pagamento": "Pix",
                "referencia": "REC-CORE-1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/financeiro")
        with self.app.app_context():
            request_record = db.session.get(Solicitacao, request_id)
            self.assertIn(request_record.status, {"confirmado", "agendado"})
            self.assertAlmostEqual(request_record.valor_snapshot, 200.00)
            self.assertEqual(
                request_record.validacao_pagamento.referencia_financeira,
                "Pix: REC-CORE-1",
            )
            self.assertEqual(
                request_record.validacao_pagamento.responsavel_financeiro,
                "Operador Financeiro",
            )

    def test_reception_cannot_manually_issue_same_day_ticket_after_payment(self):
        request_id = self._create_request(paid=True)
        with self.app.app_context():
            db.session.get(Medico, self.doctor_id).presenca_ativa = False
            db.session.commit()

        self._login_as_receptionist()
        page = self.client.get("/solicitacoes")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("Agendar atendimento", body)
        self.assertNotIn("Atendimento hoje / emitir senha", body)
        self.assertEqual(
            self.client.post(
                f"/solicitacoes/{request_id}/emitir-senha"
            ).status_code,
            404,
        )

        with self.app.app_context():
            request_record = db.session.get(Solicitacao, request_id)
            self.assertEqual(request_record.status, "confirmado")
            self.assertIsNone(request_record.agendamento)
            self.assertEqual(Senha.query.count(), 0)

    def test_future_booking_lists_and_accepts_doctor_without_presence_confirmation(self):
        request_id = self._create_request(paid=True)
        with self.app.app_context():
            db.session.get(Medico, self.doctor_id).presenca_ativa = False
            db.session.commit()

        self._login_as_receptionist()

        query = {
            "solicitacao_id": request_id,
            "data_hora": datetime.combine(
                datetime.now().date() + timedelta(days=1),
                time(9, 0),
            ).strftime("%Y-%m-%dT%H:%M"),
        }
        available = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string=query,
        )
        self.assertEqual(
            available.get_json()["medicos"],
            [{"id": self.doctor_id, "nome": "Médico de Teste", "sala": self.room.nome}],
        )

        doctor = self.app.test_client()
        login = doctor.post(
            "/login",
            data={
                "identifier": self.doctor_username,
                "password": "Doctor-Core-Test-123!",
            },
        )
        self.assertEqual(login.status_code, 302)
        doctor.post("/logout")
        with self.app.app_context():
            self.assertFalse(db.session.get(Medico, self.doctor_id).presenca_ativa)

        available_after_logout = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string=query,
        )
        self.assertEqual(
            available_after_logout.get_json()["medicos"],
            [{"id": self.doctor_id, "nome": "Médico de Teste", "sala": self.room.nome}],
        )

        booked = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(request_id),
                "medico_id": str(self.doctor_id),
                "data_hora": query["data_hora"],
            },
        )
        self.assertEqual(booked.status_code, 302)
        with self.app.app_context():
            self.assertFalse(db.session.get(Medico, self.doctor_id).presenca_ativa)
            appointment = Agendamento.query.filter_by(
                solicitacao_id=request_id
            ).one()
            self.assertEqual(appointment.medico_id, self.doctor_id)

    def test_finance_confirmation_auto_schedules_and_issues_ticket(self):
        request_id = self._create_request(paid=False)
        with self.app.app_context():
            db.session.add(
                DisponibilidadeMedica(
                    medico_id=self.doctor_id,
                    dia_semana=datetime.now().weekday(),
                    hora_inicio="00:00",
                    hora_fim="23:30",
                    ativo=True,
                )
            )
            db.session.commit()

        self._login_as_finance()
        confirmation = self.client.post(
            f"/financeiro/solicitacoes/{request_id}/confirmar",
            data={
                "forma_pagamento": "Pix",
                "referencia": "FIN-E2E-01",
            },
            follow_redirects=True,
        )
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Pagamento confirmado.", confirmation.get_data(as_text=True))
        self.assertIn("Senha N-", confirmation.get_data(as_text=True))

        with self.app.app_context():
            appointment = Agendamento.query.filter_by(
                solicitacao_id=request_id
            ).one()
            self.assertEqual(AgendamentoSenha.query.filter_by(
                agendamento_id=appointment.id
            ).count(), 1)

    def test_booking_ignores_weekly_hours_and_uses_the_doctors_assigned_room(self):
        appointment_date = datetime.now().date() + timedelta(days=7)
        with self.app.app_context():
            db.session.add(
                DisponibilidadeMedica(
                    medico_id=self.doctor_id,
                    dia_semana=appointment_date.weekday(),
                    hora_inicio="09:00",
                    hora_fim="12:00",
                    ativo=True,
                )
            )
            db.session.commit()
        request_id = self._create_request(paid=True)
        self._login_as_receptionist()
        with self.app.app_context():
            suffix = uuid4().hex
            completed_request = Solicitacao(
                codigo=f"DONE-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                valor_snapshot=125.50,
                status="concluido",
            )
            db.session.add(completed_request)
            db.session.flush()
            db.session.add(
                Agendamento(
                    solicitacao_id=completed_request.id,
                    paciente_id=self.patient_id,
                    medico_id=self.doctor_id,
                    sala_id=self.room_id,
                    data_hora=datetime.combine(
                        appointment_date,
                        time(9, 0),
                    ),
                    status="concluido",
                )
            )
            db.session.get(Sala, self.room_id).status = "ocupada"
            db.session.commit()

        scheduling_page = self.client.get("/agenda/agendar")
        self.assertEqual(scheduling_page.status_code, 200)
        scheduling_body = scheduling_page.get_data(as_text=True)
        self.assertIn("/agenda/medicos-disponiveis", scheduling_body)
        self.assertNotIn('name="sala_id"', scheduling_body)

        available = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string={
                "solicitacao_id": request_id,
                "data_hora": datetime.combine(
                    appointment_date,
                    time(9, 0),
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(available.status_code, 200)
        self.assertEqual(
            available.get_json()["medicos"],
            [{"id": self.doctor_id, "nome": "Médico de Teste", "sala": self.room.nome}],
        )
        with self.app.app_context():
            db.session.get(Sala, self.room_id).status = "indisponivel"
            db.session.commit()
        unavailable_room = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string={
                "solicitacao_id": request_id,
                "data_hora": datetime.combine(
                    appointment_date,
                    time(9, 0),
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(unavailable_room.get_json()["medicos"], [])
        with self.app.app_context():
            db.session.get(Sala, self.room_id).status = "ocupada"
            db.session.commit()

        outside_schedule = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string={
                "solicitacao_id": request_id,
                "data_hora": datetime.combine(
                    appointment_date,
                    time(12, 0),
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(
            outside_schedule.get_json()["medicos"],
            [{"id": self.doctor_id, "nome": "Médico de Teste", "sala": self.room.nome}],
        )

        booked = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.alternate_room_id),
                "data_hora": datetime.combine(
                    appointment_date,
                    time(10, 0),
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(booked.status_code, 302)
        with self.app.app_context():
            appointment = Agendamento.query.filter_by(
                solicitacao_id=request_id
            ).one()
            self.assertEqual(appointment.sala_id, self.room_id)

        with self.app.app_context():
            suffix = uuid4().hex
            other_user = Usuario(
                nome_completo="Outro Médico",
                email=f"outro-medico-{suffix}@example.test",
                username=f"outro-medico-{suffix[:12]}",
                senha_hash=generate_password_hash("Other-Doctor-123!"),
                perfil="medico",
                ativo=True,
            )
            db.session.add(other_user)
            db.session.flush()
            other_doctor = Medico(
                usuario_id=other_user.id,
                especialidade_id=self.specialty_id,
                crm=f"OUTRO-{suffix[:12]}",
                nome_exibicao="Outro Médico",
                ativo=True,
            )
            db.session.add(other_doctor)
            db.session.commit()
            other_doctor_id = other_doctor.id
        self.client.post("/logout")
        self.client.post(
            "/login",
            data={"identifier": "admin", "password": "Admin@123"},
        )
        room_change = self.client.post(
            f"/salas/{self.room_id}/editar",
            data={
                "nome": self.room.nome,
                "setor": self.room.setor,
                "medico_id": str(other_doctor_id),
                "status": "disponivel",
                "ativa": "on",
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Não é possível trocar o médico responsável enquanto houver agendamentos ativos",
            room_change.get_data(as_text=True),
        )
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Medico, self.doctor_id).sala_id,
                self.room_id,
            )
            self.assertIsNone(db.session.get(Medico, other_doctor_id).sala_id)

    def test_reception_intake_registers_patient_and_prints_financial_guide(self):
        with self.app.app_context():
            suffix = uuid4().hex
            receptionist = Usuario(
                nome_completo="Recepcionista de Teste",
                email=f"recepcao-intake-{suffix}@example.test",
                username=f"recepcao-intake-{suffix[:10]}",
                senha_hash=generate_password_hash("Reception-Intake-123!"),
                perfil="recepcionista",
                ativo=True,
            )
            db.session.add(receptionist)
            db.session.flush()
            receptionist.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "gerenciar_pacientes",
                        "consultar_servicos",
                        "gerenciar_solicitacoes",
                        "gerenciar_agenda",
                        "gerenciar_fila",
                    }
                )
            ).all()
            db.session.commit()
            username = receptionist.username

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={
                "identifier": username,
                "password": "Reception-Intake-123!",
            },
        )
        dashboard = self.client.get("/dashboard")
        dashboard_body = dashboard.get_data(as_text=True)
        self.assertIn("Novo atendimento", dashboard_body)
        self.assertNotIn('href="/agenda/ausencias"', dashboard_body)
        self.assertEqual(self.client.get("/solicitacoes/nova").status_code, 200)

        response = self.client.post(
            "/solicitacoes/nova",
            data={
                "paciente_id": "",
                "novo_nome_completo": "Paciente de Atendimento",
                "novo_cpf": "987.654.321-00",
                "novo_data_nascimento": "1985-04-03",
                "novo_telefone": "11988887777",
                "novo_endereco": "Rua Fictícia, 10",
                "novo_observacoes": "Cadastro de teste",
                "servico_id": str(self.service_id),
                "medico_id": str(self.doctor_id),
                "observacoes": "Consulta solicitada para teste",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/documento-financeiro", response.headers["Location"])

        with self.app.app_context():
            patient = Paciente.query.filter_by(cpf="98765432100").one()
            request_record = Solicitacao.query.filter_by(
                paciente_id=patient.id
            ).one()
            self.assertEqual(patient.nome_completo, "Paciente de Atendimento")
            self.assertEqual(patient.data_nascimento, date(1985, 4, 3))
            self.assertEqual(patient.telefone, "11988887777")
            self.assertEqual(patient.endereco, "Rua Fictícia, 10")
            self.assertIsNone(patient.email)
            self.assertEqual(patient.observacoes, "Cadastro de teste")
            self.assertEqual(request_record.status, "aguardando_pagamento")
            self.assertEqual(request_record.servico_id, self.service_id)
            self.assertEqual(request_record.medico_id, self.doctor_id)
            self.assertEqual(request_record.observacoes, "Consulta solicitada para teste")
            self.assertAlmostEqual(request_record.valor_snapshot, 125.50)
            self.assertIsNone(request_record.validacao_pagamento)
            self.assertIsNone(request_record.agendamento)
            request_id = request_record.id

        intake_page = self.client.get("/solicitacoes/nova").get_data(as_text=True)
        self.assertIn("Dados do paciente", intake_page)
        self.assertIn("Dados do atendimento", intake_page)
        self.assertIn("Médico responsável", intake_page)
        self.assertNotIn('name="novo_email"', intake_page)

        requests_page = self.client.get("/solicitacoes").get_data(as_text=True)
        self.assertIn("Médico de Teste", requests_page)

        document = self.client.get(
            f"/solicitacoes/{request_id}/documento-financeiro"
        )
        body = document.get_data(as_text=True)
        self.assertEqual(document.status_code, 200)
        self.assertIn("Paciente de Atendimento", body)
        self.assertIn("Consulta Core", body)
        self.assertIn("Médico de Teste", body)
        self.assertIn("125,50", body)
        self.assertIn("Não é comprovante de pagamento", body)
        self.assertNotIn("98765432100", body)
        self.assertNotIn("Rua Fictícia", body)

    def test_reception_cannot_register_request_without_responsible_doctor(self):
        self._login_as_receptionist()
        response = self.client.post(
            "/solicitacoes/nova",
            data={
                "paciente_id": str(self.patient_id),
                "servico_id": str(self.service_id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Selecione um médico ativo", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Solicitacao.query.count(), 0)

    def test_legacy_receipt_does_not_authorize_scheduling_or_reception_validation(self):
        self._login_as_receptionist()
        request_id = self._create_request(paid=False)
        with self.app.app_context():
            request_record = db.session.get(Solicitacao, request_id)
            request_record.status = "confirmado"
            db.session.add(
                ConfirmacaoPagamento(
                    solicitacao_id=request_id,
                    referencia_recibo="REC-LEGACY",
                    responsavel="Recepção",
                    origem_confirmacao="recepcao",
                )
            )
            appointment_date = datetime.now().date() + timedelta(days=3)
            db.session.add(
                DisponibilidadeMedica(
                    medico_id=self.doctor_id,
                    dia_semana=appointment_date.weekday(),
                    hora_inicio="09:00",
                    hora_fim="17:00",
                    ativo=True,
                )
            )
            db.session.commit()

        appointment_time = datetime.combine(appointment_date, time(12, 0))
        denied = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": appointment_time.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=True,
        )
        self.assertIn("validação financeira registrada", denied.get_data(as_text=True))

        confirmation_response = self.client.post(
            f"/solicitacoes/{request_id}/confirmar-pagamento",
            data={
                "referencia_recibo": "FIN-LEGACY-01",
                "responsavel": "Equipe Financeira",
            },
            follow_redirects=True,
        )
        self.assertEqual(
            confirmation_response.request.path,
            "/dashboard",
        )
        booked = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": appointment_time.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=True,
        )
        self.assertIn("validação financeira registrada", booked.get_data(as_text=True))
        with self.app.app_context():
            request_record = db.session.get(Solicitacao, request_id)
            self.assertEqual(
                request_record.confirmacao_pagamento.referencia_recibo,
                "REC-LEGACY",
            )
            self.assertIsNone(request_record.validacao_pagamento)
            self.assertEqual(
                Agendamento.query.filter_by(solicitacao_id=request_id).count(),
                0,
            )

    def test_agenda_requires_payment_and_rejects_overlapping_appointments(self):
        self._login_as_receptionist()
        unpaid_request_id = self._create_request(paid=False)
        date_to_book = datetime.now().date() + timedelta(days=2)
        start = datetime.combine(date_to_book, time(12, 0))
        with self.app.app_context():
            db.session.add(
                DisponibilidadeMedica(
                    medico_id=self.doctor_id,
                    dia_semana=date_to_book.weekday(),
                    hora_inicio="09:00",
                    hora_fim="17:00",
                    ativo=True,
                )
            )
            db.session.commit()

        unpaid_response = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(unpaid_request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": start.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=True,
        )
        self.assertIn("pagamento confirmado", unpaid_response.get_data(as_text=True))

        first_request_id = self._create_request(paid=True)
        second_request_id = self._create_request(paid=True)
        first_booking = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(first_request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": start.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=False,
        )
        self.assertEqual(first_booking.status_code, 302)
        overlapping_booking = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(second_request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": start.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=True,
        )
        self.assertIn("já está ocupado", overlapping_booking.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(
                Agendamento.query.filter_by(solicitacao_id=first_request_id).count(),
                1,
            )
            self.assertEqual(
                Agendamento.query.filter_by(solicitacao_id=second_request_id).count(),
                0,
            )

    def test_legacy_medical_absence_does_not_block_booking(self):
        date_to_book = datetime.now().date() + timedelta(days=4)
        start = datetime.combine(date_to_book, time(12, 0))
        with self.app.app_context():
            admin_id = Usuario.query.filter_by(username="admin").one().id
            db.session.add(
                AusenciaMedica(
                    medico_id=self.doctor_id,
                    inicio=datetime.combine(date_to_book, time(11, 0)),
                    fim=datetime.combine(date_to_book, time(14, 0)),
                    tipo="ferias",
                    ativa=True,
                    registrada_por_id=admin_id,
                )
            )
            db.session.commit()

        self._login_as_receptionist()
        request_id = self._create_request(paid=True)
        available_doctors = self.client.get(
            "/agenda/medicos-disponiveis",
            query_string={
                "solicitacao_id": request_id,
                "data_hora": start.strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(
            available_doctors.get_json()["medicos"],
            [{"id": self.doctor_id, "nome": "Médico de Teste", "sala": self.room.nome}],
        )
        booking = self.client.post(
            "/agenda/agendar",
            data={
                "solicitacao_id": str(request_id),
                "medico_id": str(self.doctor_id),
                "sala_id": str(self.room_id),
                "data_hora": start.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=False,
        )
        self.assertEqual(booking.status_code, 302)
        with self.app.app_context():
            self.assertEqual(AusenciaMedica.query.count(), 1)
            self.assertEqual(Agendamento.query.filter_by(solicitacao_id=request_id).count(), 1)

    def test_administrator_cannot_access_reception_queue_or_agenda_pages(self):
        from app import seed_default_admin_user

        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            admin.permissoes = Permissao.query.all()
            db.session.commit()
        stale_permission_response = self.client.get("/pacientes")
        self.assertEqual(stale_permission_response.status_code, 302)

        with self.app.app_context():
            seed_default_admin_user()

        dashboard = self.client.get("/dashboard")
        dashboard_body = dashboard.get_data(as_text=True)
        self.assertNotIn('href="/pacientes"', dashboard_body)
        self.assertNotIn('href="/solicitacoes"', dashboard_body)
        self.assertNotIn('href="/agenda"', dashboard_body)
        self.assertNotIn('href="/fila"', dashboard_body)
        self.assertNotIn('href="/agenda/disponibilidades"', dashboard_body)
        self.assertNotIn('href="/agenda/ausencias"', dashboard_body)
        self.assertNotIn('href="/pacientes"', self.client.get("/usuarios").get_data(as_text=True))

        for path in (
            "/pacientes",
            "/pacientes/novo",
            f"/pacientes/{self.patient_id}/editar",
            "/solicitacoes",
            "/solicitacoes/nova",
            "/agenda",
            "/agenda/agendar",
            "/fila",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/dashboard")

        for path, data in (
            (f"/pacientes/{self.patient_id}/editar", {"nome_completo": "Não autorizado"}),
            (f"/pacientes/{self.patient_id}/toggle", {}),
            ("/pacientes/novo", {"nome_completo": "Não autorizado"}),
        ):
            with self.subTest(path=path, method="POST"):
                response = self.client.post(path, data=data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/dashboard")

        availability = self.client.post(
            "/agenda/disponibilidades",
            data={
                "medico_id": str(self.doctor_id),
                "dia_semana": "0",
                "hora_inicio": "09:00",
                "hora_fim": "17:00",
                "observacao": "Horário administrativo de teste",
            },
        )
        self.assertEqual(availability.status_code, 302)
        with self.app.app_context():
            self.assertEqual(DisponibilidadeMedica.query.count(), 0)
        self.assertEqual(self.client.get("/agenda/ausencias").status_code, 404)
        response = self.client.post(f"/fila/emitir/{self.service_id}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")
        self.assertEqual(self.client.get("/prioridades/politica").status_code, 200)

        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            admin_permission_codes = {permission.codigo for permission in admin.permissoes}
            self.assertTrue(
                admin_permission_codes.isdisjoint(
                    {
                        "gerenciar_pacientes",
                        "gerenciar_solicitacoes",
                        "gerenciar_agenda",
                        "gerenciar_fila",
                    }
                )
            )

    def test_receptionist_can_operate_front_desk_but_not_admin_or_clinical_routes(self):
        with self.app.app_context():
            suffix = uuid4().hex
            receptionist = Usuario(
                nome_completo="Recepcionista Teste",
                email=f"recepcao-{suffix}@example.test",
                username=f"recepcao-{suffix[:12]}",
                senha_hash=generate_password_hash("Reception-Test-123!"),
                perfil="recepcionista",
                ativo=True,
            )
            db.session.add(receptionist)
            db.session.flush()
            receptionist.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "gerenciar_pacientes",
                        "consultar_servicos",
                        "gerenciar_solicitacoes",
                        "gerenciar_agenda",
                        "gerenciar_fila",
                    }
                )
            ).all()
            db.session.commit()
            username = receptionist.username

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={"identifier": username, "password": "Reception-Test-123!"},
        )
        self.assertEqual(self.client.get("/pacientes").status_code, 200)
        self.assertEqual(self.client.get("/servicos").status_code, 302)
        self.assertEqual(self.client.get("/solicitacoes").status_code, 200)
        self.assertEqual(self.client.get("/agenda").status_code, 200)
        self.assertEqual(self.client.get("/agenda/disponibilidades").status_code, 302)
        self.assertEqual(self.client.get("/agenda/ausencias").status_code, 404)
        self.assertEqual(
            self.client.post("/agenda/ausencias", data={}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post("/agenda/ausencias/1/toggle").status_code,
            404,
        )
        self.assertEqual(self.client.get("/fila").status_code, 200)
        self.assertEqual(self.client.get("/usuarios").status_code, 302)
        self.assertEqual(self.client.get("/atendimentos").status_code, 404)

        with self.app.app_context():
            original_active = db.session.get(Servico, self.service_id).ativo
            availability_count = DisponibilidadeMedica.query.count()
        denied_availability = self.client.post(
            "/agenda/disponibilidades",
            data={
                "medico_id": str(self.doctor_id),
                "dia_semana": "0",
                "hora_inicio": "09:00",
                "hora_fim": "17:00",
            },
        )
        self.assertEqual(denied_availability.status_code, 302)
        with self.app.app_context():
            self.assertEqual(DisponibilidadeMedica.query.count(), availability_count)
        denied_toggle = self.client.post(f"/servicos/{self.service_id}/toggle")
        self.assertEqual(denied_toggle.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Servico, self.service_id).ativo, original_active)

    def test_user_management_rejects_permissions_outside_selected_profile(self):
        with self.app.app_context():
            user_management_permission = Permissao.query.filter_by(
                codigo="gerenciar_usuarios"
            ).one()
            dashboard_permission = Permissao.query.filter_by(
                codigo="acessar_dashboard"
            ).one()

        response = self.client.post(
            "/usuarios/novo",
            data={
                "nome_completo": "Recepção Sem Escalada",
                "email": "recepcao-segura@example.test",
                "username": "recepcao-segura",
                "perfil": "recepcionista",
                "senha": "Reception-Safe-123!",
                "ativo": "on",
                "permissoes": [
                    str(user_management_permission.id),
                    str(dashboard_permission.id),
                ],
            },
            follow_redirects=True,
        )
        self.assertIn("permissões incompatíveis", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(
                Usuario.query.filter_by(username="recepcao-segura").first()
            )

    def test_admin_can_type_new_specialty_and_duplicate_error_keeps_form_values(self):
        response = self.client.get("/especialidades/nova")
        self.assertIn('name="nome"', response.get_data(as_text=True))
        self.assertIn("Ex.: Cardiologia", response.get_data(as_text=True))

        response = self.client.post(
            "/especialidades/nova",
            data={
                "nome": "Especialidade Digitada",
                "descricao": "Especialidade cadastrada pelo formulário.",
                "ativa": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            saved = Especialidade.query.filter_by(
                nome="Especialidade Digitada"
            ).one()
            specialty_id = saved.id

        duplicate = self.client.post(
            "/especialidades/nova",
            data={
                "nome": "Especialidade Digitada",
                "descricao": "Texto que deve permanecer após o erro.",
                "ativa": "on",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        body = duplicate.get_data(as_text=True)
        self.assertIn('value="Especialidade Digitada"', body)
        self.assertIn("Texto que deve permanecer após o erro.", body)
        with self.app.app_context():
            self.assertEqual(
                Especialidade.query.filter_by(nome="Especialidade Digitada").count(),
                1,
            )
            self.assertIsNotNone(db.session.get(Especialidade, specialty_id))

    def test_new_doctor_saves_typed_display_name_and_preserves_it_on_validation_error(self):
        suffix = uuid4().hex
        form = self.client.get("/medicos/novo").get_data(as_text=True)
        self.assertIn("Criar nova conta para este médico", form)
        self.assertIn('name="email"', form)
        self.assertIn('name="nome_exibicao"', form)

        with self.app.app_context():
            doctor_user = Usuario(
                nome_completo="Conta Médico Novo",
                email=f"novo-medico-{suffix}@example.test",
                username=f"novo-medico-{suffix[:12]}",
                senha_hash=generate_password_hash("New-Doctor-Test-123!"),
                perfil="medico",
                ativo=True,
            )
            db.session.add(doctor_user)
            db.session.flush()
            doctor_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {"acessar_dashboard", "gerenciar_agenda", "gerenciar_atendimento"}
                )
            ).all()
            db.session.commit()
            doctor_user_id = doctor_user.id

        response = self.client.post(
            "/medicos/novo",
            data={
                "usuario_id": str(doctor_user_id),
                "especialidade_id": str(self.specialty_id),
                "crm": f"CRM-{suffix[:12]}",
                "nome_exibicao": "Dra. Nome Digitado",
                "ativo": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            saved_doctor = Medico.query.filter_by(usuario_id=doctor_user_id).one()
            self.assertEqual(saved_doctor.nome_exibicao, "Dra. Nome Digitado")
            self.assertIsNone(saved_doctor.sala_id)

        invalid = self.client.post(
            "/medicos/novo",
            data={
                "usuario_id": "",
                "especialidade_id": str(self.specialty_id),
                "crm": f"CRM-INVALID-{suffix[:8]}",
                "nome_exibicao": "Nome Mantido Após Erro",
                "ativo": "on",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(
            'value="Nome Mantido Após Erro"',
            invalid.get_data(as_text=True),
        )

        new_username = f"medico-novo-{suffix[:10]}"
        new_email = f"medico-novo-{suffix}@example.test"
        created = self.client.post(
            "/medicos/novo",
            data={
                "usuario_id": "",
                "especialidade_id": str(self.specialty_id),
                "crm": f"CRM-INLINE-{suffix[:10]}",
                "nome_exibicao": "Dr. Criado no Mesmo Formulário",
                "email": new_email,
                "username": new_username,
                "senha": "Inline-Doctor-123!",
                "ativo": "on",
            },
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            new_user = Usuario.query.filter_by(username=new_username).one()
            new_doctor = Medico.query.filter_by(usuario_id=new_user.id).one()
            self.assertEqual(new_user.perfil, "medico")
            self.assertEqual(new_user.email, new_email)
            self.assertEqual(new_user.nome_completo, "Dr. Criado no Mesmo Formulário")
            self.assertEqual(new_doctor.nome_exibicao, "Dr. Criado no Mesmo Formulário")
            self.assertIsNone(new_doctor.sala_id)
            new_doctor_id = new_doctor.id
            self.assertTrue(
                {"acessar_dashboard", "gerenciar_atendimento"}.issubset(
                    {permission.codigo for permission in new_user.permissoes}
                )
            )

        room_response = self.client.post(
            "/salas/nova",
            data={
                "nome": f"Sala Inline {suffix[:8]}",
                "setor": "consulta",
                "medico_id": str(new_doctor_id),
                "status": "disponivel",
                "ativa": "on",
            },
        )
        self.assertEqual(room_response.status_code, 302)
        with self.app.app_context():
            saved_doctor = db.session.get(Medico, new_doctor_id)
            self.assertEqual(saved_doctor.sala.nome, f"Sala Inline {suffix[:8]}")
            assigned_room_id = saved_doctor.sala.id
        room_list = self.client.get("/salas").get_data(as_text=True)
        self.assertIn("Dr. Criado no Mesmo Formulário", room_list)
        room_edit = self.client.get(f"/salas/{assigned_room_id}/editar")
        self.assertEqual(room_edit.status_code, 200)
        self.assertIn("Médico responsável", room_edit.get_data(as_text=True))

        duplicate_assignment = self.client.post(
            "/salas/nova",
            data={
                "nome": f"Sala Duplicada {suffix[:8]}",
                "setor": "consulta",
                "medico_id": str(new_doctor_id),
                "status": "disponivel",
                "ativa": "on",
            },
        )
        self.assertEqual(duplicate_assignment.status_code, 200)
        self.assertIn("ainda não seja responsável", duplicate_assignment.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(
                Sala.query.filter_by(nome=f"Sala Duplicada {suffix[:8]}").count(),
                0,
            )

        self.client.post("/logout")
        login = self.client.post(
            "/login",
            data={"identifier": new_username, "password": "Inline-Doctor-123!"},
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_editing_unassigned_room_explains_when_no_doctor_is_unassigned(self):
        with self.app.app_context():
            room = Sala(
                nome=f"Sala Vazia {uuid4().hex[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            db.session.add(room)
            db.session.commit()
            room_id = room.id

        response = self.client.get(f"/salas/{room_id}/editar")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(
            "Não há médicos ativos sem sala atribuída para selecionar.",
            body,
        )
        self.assertIn('href="/medicos/novo">Adicionar médico</a>', body)
        self.assertIn('<option value="">Selecione...</option>', body)

    def test_clinic_management_rejects_unknown_doctor_and_room_statuses(self):
        response = self.client.post(
            f"/medicos/{self.doctor_id}/editar",
            data={
                "usuario_id": str(self.doctor_user_id),
                "especialidade_id": str(self.specialty_id),
                "crm": "CORE-STATUS-TEST",
                "nome_exibicao": "Médico de Teste",
                "status": "ausente",
                "ativo": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Medico, self.doctor_id).status, "disponivel")

        response = self.client.post(
            f"/salas/{self.room_id}/editar",
            data={
                "nome": "Sala Core Segura",
                "setor": "consulta",
                "status": "injetado",
                "ativa": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Sala, self.room_id).status, "disponivel")
            self.assertTrue(db.session.get(Sala, self.room_id).ativa)
        deactivated = self.client.post(
            f"/salas/{self.room_id}/toggle",
            follow_redirects=True,
        )
        self.assertEqual(deactivated.status_code, 200)
        with self.app.app_context():
            self.assertFalse(db.session.get(Sala, self.room_id).ativa)

    def test_absence_workflows_are_removed_without_deleting_legacy_records(self):
        with self.app.app_context():
            admin_id = Usuario.query.filter_by(username="admin").one().id
            absence = AusenciaMedica(
                medico_id=self.doctor_id,
                inicio=datetime.now() - timedelta(hours=1),
                fim=datetime.now() + timedelta(hours=1),
                tipo="ausencia",
                ativa=True,
                registrada_por_id=admin_id,
            )
            db.session.add(absence)
            db.session.flush()
            justification = JustificativaAusenciaMedica(
                ausencia_id=absence.id,
                categoria="saude",
                motivo="Registro histórico de teste",
                atestado_conteudo=b"%PDF-1.4 legacy",
                atestado_extensao="pdf",
                registrada_por_id=admin_id,
            )
            db.session.add(justification)
            db.session.commit()
            absence_id = absence.id

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={
                "identifier": self.doctor_username,
                "password": "Doctor-Core-Test-123!",
            },
        )
        presence_page = self.client.get("/agenda/minha-disponibilidade")
        self.assertEqual(presence_page.status_code, 200)
        presence_body = presence_page.get_data(as_text=True)
        self.assertIn("Presença confirmada", presence_body)
        self.assertNotIn("ausência", presence_body.lower())
        self.assertNotIn("atestado", presence_body.lower())
        self.assertEqual(
            self.client.post(
                "/agenda/minha-disponibilidade/ausencia",
                data={"motivo": "Este fluxo foi removido."},
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get("/agenda/ausencias").status_code, 404)

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={"identifier": "admin", "password": "Admin@123"},
        )
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("Férias e ausências", dashboard)
        self.assertNotIn("/agenda/ausencias", dashboard)
        doctors_page = self.client.get("/medicos").get_data(as_text=True)
        self.assertNotIn("Ausente", doctors_page)
        self.assertEqual(self.client.get("/agenda/ausencias").status_code, 404)
        self.assertEqual(self.client.post("/agenda/ausencias").status_code, 404)
        self.assertEqual(
            self.client.post(f"/agenda/ausencias/{absence_id}/toggle").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/agenda/ausencias/{absence_id}/atestado").status_code,
            404,
        )
        with self.app.app_context():
            self.assertEqual(AusenciaMedica.query.count(), 1)
            self.assertEqual(JustificativaAusenciaMedica.query.count(), 1)
            preserved = JustificativaAusenciaMedica.query.one()
            self.assertEqual(preserved.atestado_conteudo, b"%PDF-1.4 legacy")

    def test_doctor_agenda_is_scoped_to_the_linked_doctor(self):
        with self.app.app_context():
            doctor_user = db.session.get(Usuario, self.doctor_user_id)
            doctor_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_({"acessar_dashboard", "gerenciar_agenda"})
            ).all()

            other_patient = Paciente(
                nome_completo="Paciente de Outro Médico",
                cpf="11122233344",
                data_nascimento=date(1988, 2, 2),
                telefone="11988887777",
                endereco="Rua de Teste, 22",
                ativo=True,
            )
            suffix = uuid4().hex
            other_user = Usuario(
                nome_completo="Outro Médico",
                email=f"outro-{suffix}@example.test",
                username=f"outro-{suffix[:12]}",
                senha_hash=generate_password_hash("Other-Doctor-Core-123!"),
                perfil="medico",
                ativo=True,
            )
            db.session.add_all([other_patient, other_user])
            db.session.flush()
            other_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_({"acessar_dashboard", "gerenciar_agenda"})
            ).all()
            other_doctor = Medico(
                usuario_id=other_user.id,
                especialidade_id=self.specialty_id,
                crm=f"OTHER-{suffix[:10]}",
                nome_exibicao="Outro Médico",
                ativo=True,
                status="disponivel",
            )
            db.session.add(other_doctor)
            db.session.flush()

            for patient_id, doctor_id, code in (
                (self.patient_id, self.doctor_id, f"OWN-{suffix[:8]}"),
                (other_patient.id, other_doctor.id, f"OTHER-{suffix[:8]}"),
            ):
                request_record = Solicitacao(
                    codigo=code,
                    paciente_id=patient_id,
                    servico_id=self.service_id,
                    especialidade_id=self.specialty_id,
                    medico_id=doctor_id,
                    valor_snapshot=125.50,
                    status="agendado",
                )
                db.session.add(request_record)
                db.session.flush()
                db.session.add(
                    Agendamento(
                        solicitacao_id=request_record.id,
                        paciente_id=patient_id,
                        medico_id=doctor_id,
                        sala_id=self.room_id,
                        data_hora=datetime.combine(datetime.now().date(), time(12, 0)),
                        status="agendado",
                    )
                )
            db.session.commit()

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={
                "identifier": self.doctor_username,
                "password": "Doctor-Core-Test-123!",
            },
        )
        self.assertEqual(self.client.get("/agenda/ausencias").status_code, 404)
        response = self.client.get(
            f"/agenda?data={datetime.now().date().isoformat()}"
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Paciente de Teste", body)
        self.assertNotIn("Paciente de Outro Médico", body)


if __name__ == "__main__":
    unittest.main()
