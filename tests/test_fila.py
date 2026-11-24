from datetime import date, datetime, time, timedelta
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
    Atendimento,
    Especialidade,
    HistoricoChamada,
    HistoricoStatus,
    Medico,
    Paciente,
    Permissao,
    PoliticaPrioridade,
    PrioridadeAgendamento,
    Prontuario,
    RegistroAuditoria,
    Sala,
    Servico,
    Senha,
    Solicitacao,
    Usuario,
    ValidacaoPagamentoFinanceiro,
)


class FilaWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "test.db").replace("\\", "/")
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
            admin_id = Usuario.query.filter_by(username="admin").one().id
            especialidade = Especialidade(nome=f"Teste {suffix[:10]}", ativa=True)
            paciente = Paciente(
                nome_completo="Paciente Teste",
                cpf=f"{suffix[:11]}",
                data_nascimento=datetime(1990, 1, 1).date(),
                telefone="11999999999",
                endereco="Endereço de teste",
                ativo=True,
            )
            usuario = Usuario(
                nome_completo="Médico Teste",
                email=f"medico-{suffix}@example.test",
                username=f"medico-{suffix[:12]}",
                senha_hash=generate_password_hash("Doctor-Test-123!"),
                perfil="medico",
                ativo=True,
            )
            receptionist = Usuario(
                nome_completo="Recepcionista Teste",
                email=f"recepcao-{suffix}@example.test",
                username=f"recepcao-{suffix[:12]}",
                senha_hash=generate_password_hash("Reception-Test-123!"),
                perfil="recepcionista",
                ativo=True,
            )
            finance_user = Usuario(
                nome_completo="Financeiro Teste",
                email=f"financeiro-{suffix}@example.test",
                username=f"financeiro-{suffix[:12]}",
                senha_hash=generate_password_hash("Finance-Test-123!"),
                perfil="financeiro",
                ativo=True,
            )
            db.session.add_all(
                [especialidade, paciente, usuario, receptionist, finance_user]
            )
            db.session.flush()
            usuario.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "gerenciar_atendimento",
                        "gerenciar_agenda",
                        "consultar_servicos",
                    }
                )
            ).all()
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
            finance_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {
                        "acessar_dashboard",
                        "gerenciar_financeiro",
                        "consultar_servicos",
                    }
                )
            ).all()

            self.doctor = Medico(
                usuario_id=usuario.id,
                especialidade_id=especialidade.id,
                crm=f"TEST-{suffix[:12]}",
                nome_exibicao="Médico Teste",
                ativo=True,
                status="disponivel",
                presenca_ativa=True,
            )
            self.room = Sala(
                nome=f"Sala Teste {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            db.session.add_all([self.doctor, self.room])
            db.session.flush()
            service = Servico(
                nome=f"Consulta Teste {suffix[:8]}",
                categoria="Consulta",
                valor=100.0,
                ativo=True,
                especialidade_id=especialidade.id,
            )
            db.session.add(service)
            db.session.flush()
            self.request_record = Solicitacao(
                codigo=f"TEST-{suffix[:16]}",
                paciente_id=paciente.id,
                servico_id=service.id,
                especialidade_id=especialidade.id,
                medico_id=self.doctor.id,
                valor_snapshot=service.valor,
                status="agendado",
            )
            db.session.add(self.request_record)
            db.session.flush()
            db.session.add(
                ValidacaoPagamentoFinanceiro(
                    solicitacao_id=self.request_record.id,
                    referencia_financeira=f"REC-{suffix[:10]}",
                    responsavel_financeiro="Equipe Financeira",
                    data_confirmacao=datetime.now(),
                    registrada_por_id=admin_id,
                )
            )
            self.appointment = Agendamento(
                solicitacao_id=self.request_record.id,
                paciente_id=paciente.id,
                medico_id=self.doctor.id,
                sala_id=self.room.id,
                data_hora=datetime.combine(datetime.now().date(), time(12, 0)),
                status="agendado",
                prioridade=True,
            )
            db.session.add(self.appointment)
            db.session.commit()
            self.appointment_id = self.appointment.id
            self.request_id = self.request_record.id
            self.patient_id = paciente.id
            self.doctor_id = self.doctor.id
            self.specialty_id = especialidade.id
            self.room_id = self.room.id
            self.service_id = service.id
            self.doctor_username = usuario.username
            self.receptionist_username = receptionist.username
            self.finance_username = finance_user.username

        response = self.client.post(
            "/login",
            data={
                "identifier": self.receptionist_username,
                "password": "Reception-Test-123!",
            },
        )
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _login_as(self, username, password):
        self.client.post("/logout")
        response = self.client.post(
            "/login",
            data={"identifier": username, "password": password},
        )
        self.assertEqual(response.status_code, 302)

    def _validate_request_payment(self, request_record):
        admin_id = Usuario.query.filter_by(username="admin").one().id
        db.session.add(
            ValidacaoPagamentoFinanceiro(
                solicitacao_id=request_record.id,
                referencia_financeira=f"TEST-{uuid4().hex[:12]}",
                responsavel_financeiro="Financeiro Teste",
                data_confirmacao=datetime.now(),
                registrada_por_id=admin_id,
            )
        )

    def _emit_ticket_as_finance(self, agendamento_id, data=None, follow_redirects=False):
        self._login_as(self.finance_username, "Finance-Test-123!")
        response = self.client.post(
            f"/fila/emitir/{agendamento_id}",
            data=data or {},
            follow_redirects=follow_redirects,
        )
        self._login_as(self.receptionist_username, "Reception-Test-123!")
        return response

    def test_issue_call_and_record_no_show(self):
        response = self.client.get("/fila")
        self.assertEqual(response.status_code, 200)

        response = self._emit_ticket_as_finance(self.appointment_id)
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            link = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one()
            ticket_id = link.senha_id
            ticket = db.session.get(Senha, ticket_id)
            self.assertEqual(ticket.status, "aguardando")
            self.assertFalse(ticket.prioridade)
            self.assertEqual(ticket.tipo, "normal")
            self.assertEqual(ticket.codigo_exibicao, "N-001")
            self.assertRegex(ticket.codigo_exibicao, r"^[A-Z]-\d{3}$")

        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            self.assertEqual(
                AgendamentoSenha.query.filter_by(
                    agendamento_id=self.appointment_id
                ).count(),
                1,
            )

        self.client.post(f"/fila/{ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "aguardando")

        self._login_as(self.receptionist_username, "Reception-Test-123!")
        self.client.post(f"/fila/{ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "aguardando")

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{ticket_id}/chamar")
        with self.app.app_context():
            ticket = db.session.get(Senha, ticket_id)
            self.assertEqual(ticket.status, "chamada")
            self.assertEqual(
                HistoricoChamada.query.filter_by(
                    senha_id=ticket_id,
                    status="chamada",
                ).count(),
                1,
            )

        self._login_as(self.receptionist_username, "Reception-Test-123!")
        self.client.post(f"/fila/{ticket_id}/nao-compareceu")
        with self.app.app_context():
            ticket = db.session.get(Senha, ticket_id)
            self.assertEqual(ticket.status, "nao_compareceu")
            self.assertEqual(
                HistoricoChamada.query.filter_by(
                    senha_id=ticket_id,
                    status="nao_compareceu",
                ).count(),
                1,
            )

    def test_doctor_login_automatically_confirms_presence_before_calling(self):
        response = self._emit_ticket_as_finance(self.appointment_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
            db.session.get(Medico, self.doctor_id).presenca_ativa = False
            db.session.commit()

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        with self.app.app_context():
            self.assertTrue(db.session.get(Medico, self.doctor_id).presenca_ativa)
        response = self.client.post(f"/fila/{ticket_id}/chamar")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "chamada")

    def test_only_finance_can_emit_and_reception_has_no_emission_action(self):
        reception_page = self.client.get("/fila")
        reception_body = reception_page.get_data(as_text=True)
        self.assertNotIn("Confirmar chegada e emitir senha", reception_body)
        self.assertNotIn('action="/fila/emitir/', reception_body)

        denied = self.client.post(f"/fila/emitir/{self.appointment_id}")
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(denied.headers["Location"], "/dashboard")
        with self.app.app_context():
            self.assertEqual(Senha.query.count(), 0)

        self._login_as(self.finance_username, "Finance-Test-123!")
        finance_page = self.client.get("/financeiro")
        self.assertEqual(finance_page.status_code, 200)
        self.assertIn(
            "Agendamentos aguardando emissão de senha",
            finance_page.get_data(as_text=True),
        )
        emitted = self.client.post(
            f"/fila/emitir/{self.appointment_id}",
            follow_redirects=True,
        )
        self.assertEqual(emitted.status_code, 200)
        self.assertIn("Senha N-001 emitida", emitted.get_data(as_text=True))
        self.assertIn("N-001", emitted.get_data(as_text=True))
        self.assertIn("Imprimir senha", emitted.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(
                AgendamentoSenha.query.filter_by(
                    agendamento_id=self.appointment_id
                ).count(),
                1,
            )

    def test_reception_cannot_emit_a_ticket_before_financial_validation(self):
        with self.app.app_context():
            request_record = db.session.get(Solicitacao, self.request_id)
            request_record.status = "aguardando_pagamento"
            db.session.delete(request_record.validacao_pagamento)
            db.session.commit()

        requests_page = self.client.get("/solicitacoes")
        self.assertEqual(requests_page.status_code, 200)
        body = requests_page.get_data(as_text=True)
        self.assertNotIn("emitir-senha", body)
        self.assertNotIn("Atendimento hoje / emitir senha", body)
        self.assertEqual(
            self.client.get(
                f"/solicitacoes/{self.request_id}/emitir-senha"
            ).status_code,
            404,
        )

        response = self._emit_ticket_as_finance(self.appointment_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Senha.query.count(), 0)

    def test_reception_can_issue_scheduled_ticket_when_doctor_is_offline(self):
        with self.app.app_context():
            db.session.get(Medico, self.doctor_id).presenca_ativa = False
            db.session.commit()

        response = self._emit_ticket_as_finance(
            self.appointment_id,
            follow_redirects=True,
        )
        self.assertIn("Senha", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(
                AgendamentoSenha.query.filter_by(
                    agendamento_id=self.appointment_id
                ).count(),
                1,
            )

    def test_public_panel_shows_patient_name_room_and_ticket_without_login(self):
        response = self._emit_ticket_as_finance(self.appointment_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id

        public_client = self.app.test_client()
        pending_call = public_client.get("/api/painel")
        self.assertEqual(pending_call.status_code, 200)
        self.assertEqual(pending_call.get_json()["chamadas"], [])

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        call_clicked_at = datetime.now()
        response = self.client.post(f"/fila/{ticket_id}/chamar")
        self.assertEqual(response.status_code, 302)

        panel_response = public_client.get("/painel")
        self.assertEqual(panel_response.status_code, 200)
        panel_body = panel_response.get_data(as_text=True)
        self.assertIn("call.paciente", panel_body)
        self.assertNotIn("Médico Teste", panel_body)
        self.assertNotIn("panel-clock", panel_body)
        self.assertIn("SpeechSynthesisUtterance", panel_body)
        self.assertIn("call.hora", panel_body)

        api_response = public_client.get("/api/painel")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.headers["Cache-Control"], "no-store")
        call = api_response.get_json()["chamadas"][0]
        self.assertRegex(call["codigo"], r"^[A-Z]-\d{3}$")
        self.assertEqual(call["codigo"], "N-001")
        self.assertEqual(call["paciente"], "Paciente Teste")
        self.assertEqual(call["sala"].split()[0], "Sala")
        self.assertRegex(call["hora"], r"^\d{2}:\d{2}:\d{2}$")
        self.assertEqual(set(call), {"codigo", "paciente", "sala", "hora"})
        with self.app.app_context():
            history = HistoricoChamada.query.filter_by(
                senha_id=ticket_id,
                status="chamada",
            ).one()
            self.assertGreaterEqual(history.data_hora, call_clicked_at)
            self.assertLessEqual(history.data_hora, datetime.now())
            self.assertEqual(call["hora"], history.data_hora.strftime("%H:%M:%S"))

    def test_printed_ticket_instructs_patient_to_wait_for_doctor_call(self):
        response = self._emit_ticket_as_finance(self.appointment_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id

        response = self.client.get(f"/fila/{ticket_id}/imprimir")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Dirija-se à sala somente depois de ser chamado.",
            response.get_data(as_text=True),
        )

    def test_prontuario_finalizes_attendance_and_preserves_queue_flow(self):
        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
            suffix = uuid4().hex
            request_record = Solicitacao(
                codigo=f"NEXT-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=self.doctor_id,
                valor_snapshot=100.0,
                status="agendado",
            )
            db.session.add(request_record)
            db.session.flush()
            self._validate_request_payment(request_record)
            next_appointment = Agendamento(
                solicitacao_id=request_record.id,
                paciente_id=request_record.paciente_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                data_hora=datetime.combine(datetime.now().date(), time(12, 30)),
                status="agendado",
            )
            db.session.add(next_appointment)
            db.session.commit()
            next_appointment_id = next_appointment.id

        self._emit_ticket_as_finance(next_appointment_id)
        with self.app.app_context():
            next_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=next_appointment_id
            ).one().senha_id

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{ticket_id}/chamar")
        with self.app.app_context():
            attendance = Atendimento.query.filter_by(senha_id=ticket_id).one()
            attendance_id = attendance.id
            self.assertEqual(attendance.status, "em_andamento")

        queue_page = self.client.get("/fila").get_data(as_text=True)
        self.assertIn("Fazer prontuário", queue_page)
        form_page = self.client.post(
            f"/fila/{ticket_id}/concluir-manual",
            follow_redirects=True,
        ).get_data(as_text=True)
        self.assertIn("Queixa Principal", form_page)
        self.assertIn("Histórico de Prontuários Anteriores", form_page)

        missing_required = self.client.post(
            f"/atendimento/{attendance_id}",
            data={"queixa_principal": "", "diagnostico": ""},
        )
        self.assertEqual(missing_required.status_code, 200)
        self.assertIn(
            "Queixa principal e diagnóstico são obrigatórios.",
            missing_required.get_data(as_text=True),
        )
        with self.app.app_context():
            attendance = db.session.get(Atendimento, attendance_id)
            self.assertEqual(attendance.status, "em_andamento")
            self.assertIsNone(attendance.prontuario)

        response = self.client.post(
            f"/atendimento/{attendance_id}",
            data={
                "queixa_principal": "Dor de cabeça há dois dias.",
                "sintomas": "Fotofobia leve.",
                "diagnostico": "Avaliação clínica registrada.",
                "prescricao": "Prescrição de teste.",
                "exames_solicitados": "Hemograma.",
                "condutas": "Acompanhar evolução.",
                "orientacoes": "Retornar se houver piora.",
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Prontuário salvo e atendimento finalizado.",
            response.get_data(as_text=True),
        )
        self.assertIn("Imprimir Receita / Prontuário", response.get_data(as_text=True))

        print_page = self.client.get(
            f"/atendimento/{attendance_id}/imprimir"
        )
        print_body = print_page.get_data(as_text=True)
        self.assertEqual(print_page.status_code, 200)
        self.assertIn("Clínica Nexo", print_body)
        self.assertIn("Prescrição de teste.", print_body)
        self.assertIn("Exames Solicitados", print_body)
        self.assertIn("CRM:", print_body)
        self.assertIn("window.print()", print_body)

        locked = self.client.post(
            f"/atendimento/{attendance_id}",
            data={
                "queixa_principal": "Alteração não permitida.",
                "diagnostico": "Alteração não permitida.",
            },
        )
        self.assertEqual(locked.status_code, 409)

        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "atendido")
            self.assertEqual(
                db.session.get(Agendamento, self.appointment_id).status,
                "concluido",
            )
            self.assertEqual(
                db.session.get(Solicitacao, self.request_id).status,
                "concluido",
            )
            attendance = db.session.get(Atendimento, attendance_id)
            self.assertEqual(attendance.status, "finalizado")
            self.assertIsNotNone(attendance.data_fim)
            self.assertEqual(Prontuario.query.filter_by(
                atendimento_id=attendance_id
            ).count(), 1)
            prontuario = attendance.prontuario
            self.assertEqual(
                prontuario.queixa_principal,
                "Dor de cabeça há dois dias.",
            )
            self.assertEqual(prontuario.diagnostico, "Avaliação clínica registrada.")
            self.assertEqual(
                HistoricoStatus.query.filter_by(
                    entidade="senha",
                    entidade_id=ticket_id,
                    status_novo="atendido",
                ).count(),
                1,
            )
            self.assertTrue(
                RegistroAuditoria.query.filter_by(
                    entidade="prontuario",
                    entidade_id=prontuario.id,
                    acao="criar_prontuario",
                ).first()
            )
            self.assertTrue(
                RegistroAuditoria.query.filter_by(
                    entidade="prontuario",
                    entidade_id=prontuario.id,
                    acao="imprimir_prontuario",
                ).first()
            )
            audit_actions = {
                event.acao
                for event in RegistroAuditoria.query.filter_by(
                    entidade="senha",
                    entidade_id=ticket_id,
                ).all()
            }
            self.assertIn("concluir_atendimento_manual", audit_actions)

        queue_page = self.client.get("/fila").get_data(as_text=True)
        self.assertIn("Abrir prontuário", queue_page)

        response = self.client.post(f"/fila/{next_ticket_id}/chamar")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, next_ticket_id).status, "chamada")

    def test_doctor_can_create_prontuario_for_completed_ticket_without_record(self):
        call_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        with self.app.app_context():
            ticket = Senha(
                codigo=f"LEGACY-{uuid4().hex[:12]}",
                paciente_id=self.patient_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                status="atendido",
                data_hora=call_time,
                numero_ordem=900,
            )
            db.session.add(ticket)
            db.session.flush()
            db.session.add(
                HistoricoChamada(
                    senha_id=ticket.id,
                    paciente_id=self.patient_id,
                    medico_id=self.doctor_id,
                    sala_id=self.room_id,
                    status="chamada",
                    data_hora=call_time,
                )
            )
            ticket_id = ticket.id
            db.session.commit()

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        list_page = self.client.get("/prontuarios").get_data(as_text=True)
        self.assertIn("Fazer prontuário", list_page)
        self.assertIn(f"/atendimento/senha/{ticket_id}/prontuario", list_page)

        form_page = self.client.get(
            f"/atendimento/senha/{ticket_id}/prontuario",
            follow_redirects=True,
        )
        self.assertEqual(form_page.status_code, 200)
        self.assertIn("Este atendimento já foi concluído.", form_page.get_data(as_text=True))

        with self.app.app_context():
            attendance = Atendimento.query.filter_by(senha_id=ticket_id).one()
            attendance_id = attendance.id
            self.assertEqual(attendance.data_inicio, call_time)

        response = self.client.post(
            f"/atendimento/{attendance_id}",
            data={
                "queixa_principal": "Consulta anterior registrada pelo médico.",
                "diagnostico": "Registro clínico realizado.",
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Prontuário registrado para o atendimento já concluído.",
            response.get_data(as_text=True),
        )
        with self.app.app_context():
            ticket = db.session.get(Senha, ticket_id)
            attendance = db.session.get(Atendimento, attendance_id)
            self.assertEqual(ticket.status, "atendido")
            self.assertEqual(attendance.status, "finalizado")
            self.assertEqual(
                attendance.prontuario.diagnostico,
                "Registro clínico realizado.",
            )
        queue_page = self.client.get("/fila").get_data(as_text=True)
        self.assertIn("Abrir prontuário", queue_page)

    def test_legacy_clinical_record_routes_remain_unavailable(self):
        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.assertEqual(self.client.get("/atendimentos").status_code, 404)
        self.assertEqual(self.client.get("/atendimentos/1").status_code, 404)
        self.assertEqual(
            self.client.post("/atendimentos/iniciar/1").status_code,
            404,
        )
        self.assertEqual(self.client.get("/atendimento/999999").status_code, 404)
        self.assertEqual(
            self.client.get("/atendimento/999999/imprimir").status_code,
            404,
        )

    def test_doctor_can_open_own_prontuario_list_from_navigation(self):
        with self.app.app_context():
            attendance = Atendimento(
                paciente_id=self.patient_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                status="em_andamento",
                data_inicio=datetime.now(),
            )
            db.session.add(attendance)
            db.session.commit()

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        queue_page = self.client.get("/fila").get_data(as_text=True)
        self.assertIn('href="/prontuarios"', queue_page)

        response = self.client.get("/prontuarios")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Paciente Teste", response.get_data(as_text=True))
        self.assertIn("Fazer prontuário", response.get_data(as_text=True))

        self._login_as(self.receptionist_username, "Reception-Test-123!")
        self.assertEqual(self.client.get("/prontuarios").status_code, 403)

    def test_non_medical_profiles_cannot_view_or_print_prontuarios(self):
        with self.app.app_context():
            attendance = Atendimento(
                paciente_id=self.patient_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                status="finalizado",
                data_inicio=datetime.utcnow(),
                data_fim=datetime.utcnow(),
            )
            db.session.add(attendance)
            db.session.flush()
            prontuario = Prontuario(
                atendimento_id=attendance.id,
                queixa_principal="Conteúdo clínico reservado.",
                diagnostico="Diagnóstico reservado.",
            )
            db.session.add(prontuario)
            suffix = uuid4().hex
            finance_user = Usuario(
                nome_completo="Financeiro Teste",
                email=f"financeiro-prontuario-{suffix}@example.test",
                username=f"financeiro-prontuario-{suffix[:10]}",
                senha_hash=generate_password_hash("Finance-Record-123!"),
                perfil="financeiro",
                ativo=True,
            )
            db.session.add(finance_user)
            db.session.flush()
            finance_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {"acessar_dashboard", "gerenciar_financeiro"}
                )
            ).all()
            db.session.commit()
            attendance_id = attendance.id
            finance_username = finance_user.username

        for username, password in (
            ("admin", "Admin@123"),
            (self.receptionist_username, "Reception-Test-123!"),
            (finance_username, "Finance-Record-123!"),
        ):
            with self.subTest(profile=username):
                self._login_as(username, password)
                for path in (
                    f"/atendimento/{attendance_id}",
                    f"/atendimento/{attendance_id}/imprimir",
                ):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn(
                        "Diagnóstico reservado.",
                        response.get_data(as_text=True),
                    )

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        authorized = self.client.get(f"/atendimento/{attendance_id}")
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("Diagnóstico reservado.", authorized.get_data(as_text=True))

    def test_patient_history_is_scoped_and_previous_record_can_be_printed(self):
        with self.app.app_context():
            suffix = uuid4().hex
            previous_doctor_user = Usuario(
                nome_completo="Médica do Histórico",
                email=f"historico-{suffix}@example.test",
                username=f"historico-{suffix[:10]}",
                senha_hash=generate_password_hash("History-Doctor-123!"),
                perfil="medico",
                ativo=True,
            )
            other_patient = Paciente(
                nome_completo="Paciente Fora do Histórico",
                cpf="99999999999",
                data_nascimento=datetime(1988, 1, 1).date(),
                telefone="11999999999",
                endereco="Endereço de teste",
                ativo=True,
            )
            db.session.add_all([previous_doctor_user, other_patient])
            db.session.flush()
            previous_doctor_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {"acessar_dashboard", "gerenciar_atendimento"}
                )
            ).all()
            previous_doctor = Medico(
                usuario_id=previous_doctor_user.id,
                especialidade_id=self.specialty_id,
                crm=f"HISTORY-{suffix[:10]}",
                nome_exibicao="Médica do Histórico",
                ativo=True,
                status="disponivel",
            )
            db.session.add(previous_doctor)
            db.session.flush()
            previous_attendance = Atendimento(
                paciente_id=self.patient_id,
                medico_id=previous_doctor.id,
                sala_id=self.room_id,
                status="finalizado",
                data_inicio=datetime(2026, 1, 1, 9, 0),
                data_fim=datetime(2026, 1, 1, 9, 30),
            )
            unrelated_attendance = Atendimento(
                paciente_id=other_patient.id,
                medico_id=previous_doctor.id,
                sala_id=self.room_id,
                status="finalizado",
                data_inicio=datetime(2026, 1, 2, 9, 0),
                data_fim=datetime(2026, 1, 2, 9, 30),
            )
            db.session.add_all([previous_attendance, unrelated_attendance])
            db.session.flush()
            db.session.add_all(
                [
                    Prontuario(
                        atendimento_id=previous_attendance.id,
                        queixa_principal="Queixa histórica.",
                        diagnostico="Diagnóstico histórico de outro profissional.",
                    ),
                    Prontuario(
                        atendimento_id=unrelated_attendance.id,
                        queixa_principal="Queixa de outro paciente.",
                        diagnostico="Diagnóstico que não deve aparecer.",
                    ),
                ]
            )
            db.session.commit()
            previous_attendance_id = previous_attendance.id

        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{ticket_id}/chamar")
        with self.app.app_context():
            current_attendance_id = Atendimento.query.filter_by(
                senha_id=ticket_id
            ).one().id

        history_page = self.client.get(
            f"/atendimento/{current_attendance_id}"
        )
        history_body = history_page.get_data(as_text=True)
        self.assertEqual(history_page.status_code, 200)
        self.assertIn("Diagnóstico histórico de outro profissional.", history_body)
        self.assertIn("Médica do Histórico", history_body)
        self.assertNotIn("Diagnóstico que não deve aparecer.", history_body)
        self.assertIn(
            f"contexto={current_attendance_id}",
            history_body,
        )
        self.assertEqual(
            self.client.get(f"/atendimento/{previous_attendance_id}").status_code,
            403,
        )

        previous_print = self.client.get(
            f"/atendimento/{previous_attendance_id}/imprimir"
            f"?contexto={current_attendance_id}"
        )
        self.assertEqual(previous_print.status_code, 200)
        self.assertIn(
            "Diagnóstico histórico de outro profissional.",
            previous_print.get_data(as_text=True),
        )

    def test_receptionist_cannot_complete_a_called_ticket(self):
        with self.app.app_context():
            ticket = Senha(
                codigo=f"RECEP-{uuid4().hex[:12]}",
                paciente_id=self.patient_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                status="chamada",
                data_hora=datetime.now(),
                numero_ordem=999,
            )
            db.session.add(ticket)
            db.session.commit()
            ticket_id = ticket.id

        self._login_as(self.receptionist_username, "Reception-Test-123!")
        response = self.client.post(f"/fila/{ticket_id}/concluir-manual")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "chamada")

    def test_only_the_assigned_doctor_can_call_the_next_ticket(self):
        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            first_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
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
            other_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {"acessar_dashboard", "gerenciar_atendimento"}
                )
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
            other_request = Solicitacao(
                codigo=f"OTHER-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=other_doctor.id,
                valor_snapshot=100.0,
                status="agendado",
            )
            db.session.add(other_request)
            db.session.flush()
            self._validate_request_payment(other_request)
            other_appointment = Agendamento(
                solicitacao_id=other_request.id,
                paciente_id=other_request.paciente_id,
                medico_id=other_doctor.id,
                sala_id=self.room_id,
                data_hora=datetime.combine(datetime.now().date(), time(12, 30)),
                status="agendado",
            )
            db.session.add(other_appointment)
            db.session.commit()
            other_appointment_id = other_appointment.id
            other_username = other_user.username

        self._emit_ticket_as_finance(other_appointment_id)
        with self.app.app_context():
            other_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=other_appointment_id
            ).one().senha_id

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{other_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, other_ticket_id).status, "aguardando")

        self._login_as(other_username, "Other-Doctor-123!")
        self.client.post(f"/fila/{first_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, first_ticket_id).status, "aguardando")

    def test_doctor_cannot_skip_next_ticket_in_own_queue(self):
        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            first_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
            suffix = uuid4().hex
            request_record = Solicitacao(
                codigo=f"NEXT-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=self.doctor_id,
                valor_snapshot=100.0,
                status="agendado",
            )
            db.session.add(request_record)
            db.session.flush()
            self._validate_request_payment(request_record)
            appointment = Agendamento(
                solicitacao_id=request_record.id,
                paciente_id=request_record.paciente_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                data_hora=datetime.combine(datetime.now().date(), time(12, 30)),
                status="agendado",
            )
            db.session.add(appointment)
            db.session.commit()
            second_appointment_id = appointment.id

        self._emit_ticket_as_finance(second_appointment_id)
        with self.app.app_context():
            second_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=second_appointment_id
            ).one().senha_id

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{second_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, second_ticket_id).status, "aguardando")
        self.client.post(f"/fila/{first_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, first_ticket_id).status, "chamada")
        self.client.post(f"/fila/{second_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Senha, second_ticket_id).status,
                "aguardando",
            )

    def test_doctor_cannot_complete_another_doctors_ticket(self):
        with self.app.app_context():
            suffix = uuid4().hex
            other_user = Usuario(
                nome_completo="Outro Médico",
                email=f"prontuario-{suffix}@example.test",
                username=f"prontuario-{suffix[:12]}",
                senha_hash=generate_password_hash("Other-Doctor-Record-123!"),
                perfil="medico",
                ativo=True,
            )
            db.session.add(other_user)
            db.session.flush()
            other_user.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(
                    {"acessar_dashboard", "gerenciar_atendimento"}
                )
            ).all()
            other_doctor = Medico(
                usuario_id=other_user.id,
                especialidade_id=self.specialty_id,
                crm=f"RECORD-{suffix[:10]}",
                nome_exibicao="Outro Médico",
                ativo=True,
                status="disponivel",
            )
            db.session.add(other_doctor)
            db.session.flush()
            ticket = Senha(
                codigo=f"OTHER-{suffix[:12]}",
                paciente_id=self.patient_id,
                medico_id=other_doctor.id,
                sala_id=self.room_id,
                status="chamada",
                data_hora=datetime.now(),
                numero_ordem=999,
            )
            db.session.add(ticket)
            db.session.commit()
            ticket_id = ticket.id

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        response = self.client.post(f"/fila/{ticket_id}/concluir-manual")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, ticket_id).status, "chamada")

    def test_priority_requires_approved_policy_and_blood_donor_proof_is_bounded(self):
        response = self._emit_ticket_as_finance(
            self.appointment_id,
            data={
                "categoria_prioridade": "idoso_60_mais",
                "comprovacao_conferida": "on",
            },
            follow_redirects=True,
        )
        self.assertIn("ainda não está aprovada", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Senha.query.count(), 0)

        self._login_as("admin", "Admin@123")
        policy_response = self.client.post(
            "/prioridades/politica",
            data={
                "categorias_habilitadas": ["doador_de_sangue", "idoso_60_mais"],
                "aprovada": "on",
                "referencia_aprovacao": "ATA-TESTE-001",
            },
        )
        self.assertEqual(policy_response.status_code, 302)
        self._login_as(self.receptionist_username, "Reception-Test-123!")
        too_old = date.today() - timedelta(days=121)
        response = self._emit_ticket_as_finance(
            self.appointment_id,
            data={
                "categoria_prioridade": "doador_de_sangue",
                "comprovacao_conferida": "on",
                "data_doacao": too_old.isoformat(),
            },
            follow_redirects=True,
        )
        self.assertIn("no máximo 120 dias", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Senha.query.count(), 0)
            self.assertTrue(db.session.get(PoliticaPrioridade, 1).aprovada)

        valid_donation = date.today() - timedelta(days=120)
        self._emit_ticket_as_finance(
            self.appointment_id,
            data={
                "categoria_prioridade": "doador_de_sangue",
                "comprovacao_conferida": "on",
                "data_doacao": valid_donation.isoformat(),
            },
        )
        with self.app.app_context():
            donor_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
            suffix = uuid4().hex
            request_record = Solicitacao(
                codigo=f"PRIO-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=self.doctor_id,
                valor_snapshot=100.0,
                status="agendado",
            )
            db.session.add(request_record)
            db.session.flush()
            self._validate_request_payment(request_record)
            appointment = Agendamento(
                solicitacao_id=request_record.id,
                paciente_id=request_record.paciente_id,
                medico_id=self.doctor_id,
                sala_id=self.room_id,
                data_hora=datetime.combine(datetime.now().date(), time(12, 30)),
                status="agendado",
            )
            db.session.add(appointment)
            db.session.commit()
            second_appointment_id = appointment.id

        self._emit_ticket_as_finance(
            second_appointment_id,
            data={
                "categoria_prioridade": "idoso_60_mais",
                "comprovacao_conferida": "on",
            },
        )
        with self.app.app_context():
            priority = PrioridadeAgendamento.query.filter_by(
                agendamento_id=self.appointment_id
            ).one()
            self.assertEqual(priority.categoria, "doador_de_sangue")
            self.assertEqual(priority.data_doacao, valid_donation)
            donor_ticket = db.session.get(Senha, donor_ticket_id)
            self.assertRegex(donor_ticket.codigo_exibicao, r"^P-\d{3}$")
            other_priority_ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=second_appointment_id
            ).one().senha_id

        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{donor_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, donor_ticket_id).status, "aguardando")
        self.client.post(f"/fila/{other_priority_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Senha, other_priority_ticket_id).status,
                "chamada",
            )
        self._login_as(self.receptionist_username, "Reception-Test-123!")
        self.client.post(f"/fila/{other_priority_ticket_id}/nao-compareceu")
        self._login_as(self.doctor_username, "Doctor-Test-123!")
        self.client.post(f"/fila/{donor_ticket_id}/chamar")
        with self.app.app_context():
            self.assertEqual(db.session.get(Senha, donor_ticket_id).status, "chamada")

    def test_printed_ticket_contains_no_patient_name(self):
        self._emit_ticket_as_finance(self.appointment_id)
        with self.app.app_context():
            ticket_id = AgendamentoSenha.query.filter_by(
                agendamento_id=self.appointment_id
            ).one().senha_id
            ticket = db.session.get(Senha, ticket_id)
            codigo = ticket.codigo_exibicao
            nome_medico = ticket.medico.nome_exibicao
            data_hora = ticket.data_hora.strftime("%d/%m/%Y %H:%M")
        response = self.client.get(f"/fila/{ticket_id}/imprimir")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(codigo, body)
        self.assertRegex(codigo, r"^[A-Z]-\d{3}$")
        self.assertIn('class="room-label">Sala:</span>', body)
        self.assertNotIn(nome_medico, body)
        self.assertNotIn(data_hora, body)
        self.assertNotIn("Paciente Teste", body)

    def test_operational_reports_filter_period_and_export_aggregates(self):
        self._login_as("admin", "Admin@123")
        with self.app.app_context():
            db.session.add(
                Senha(
                    codigo=f"REPORT-{uuid4().hex[:12]}",
                    tipo="normal",
                    paciente_id=self.appointment.paciente_id,
                    medico_id=self.appointment.medico_id,
                    sala_id=self.appointment.sala_id,
                    status="atendido",
                    data_hora=datetime.now(),
                    numero_ordem=999,
                )
            )
            db.session.commit()

        hoje = datetime.now().date().isoformat()
        response = self.client.get(f"/relatorios?inicio={hoje}&fim={hoje}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Relatórios e Indicadores", body)
        self.assertIn("Produtividade por médico", body)
        self.assertIn("Atendimentos realizados", body)
        self.assertIn("Valores recebidos", body)
        self.assertIn("Faturamento recebido hoje", body)
        self.assertIn("Horários de maior movimento", body)
        self.assertIn("Gráfico de faltas e status das senhas", body)
        self.assertNotIn("Paciente Teste", body)

        response = self.client.get(
            f"/relatorios/exportar.csv?inicio={hoje}&fim={hoje}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        csv_body = response.get_data(as_text=True)
        self.assertIn("Agendamentos", csv_body)
        self.assertIn("Valores recebidos", csv_body)
        self.assertIn("Faturamento recebido hoje", csv_body)
        self.assertIn("Faturamento recebido hoje,100.00", csv_body)
        self.assertIn("Médico Teste", csv_body)
        self.assertNotIn("Paciente Teste", csv_body)

    def test_reports_filter_by_doctor_and_support_period_presets(self):
        self._login_as("admin", "Admin@123")
        now = datetime.now()
        today = now.date()
        with self.app.app_context():
            admin_id = Usuario.query.filter_by(username="admin").one().id
            suffix = uuid4().hex
            doctor_user = Usuario(
                nome_completo="Médico Secundário",
                email=f"medico-secundario-{suffix}@example.test",
                username=f"medico-secundario-{suffix[:12]}",
                senha_hash=generate_password_hash("Doctor-Test-123!"),
                perfil="medico",
                ativo=True,
            )
            room = Sala(
                nome=f"Sala Secundária {suffix[:8]}",
                setor="consulta",
                status="disponivel",
                ativa=True,
            )
            db.session.add_all([doctor_user, room])
            db.session.flush()
            doctor = Medico(
                usuario_id=doctor_user.id,
                especialidade_id=self.specialty_id,
                sala_id=room.id,
                crm=f"TEST-{suffix[:12]}",
                nome_exibicao="Médico Secundário",
                ativo=True,
                status="disponivel",
                presenca_ativa=True,
            )
            db.session.add(doctor)
            db.session.flush()

            scheduled_request = Solicitacao(
                codigo=f"REP-S-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=doctor.id,
                valor_snapshot=250.0,
                status="agendado",
                data_solicitacao=now,
            )
            canceled_request = Solicitacao(
                codigo=f"REP-C-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=doctor.id,
                valor_snapshot=75.0,
                status="agendado",
                data_solicitacao=now,
            )
            pending_request = Solicitacao(
                codigo=f"REP-P-{suffix[:12]}",
                paciente_id=self.patient_id,
                servico_id=self.service_id,
                especialidade_id=self.specialty_id,
                medico_id=doctor.id,
                valor_snapshot=50.0,
                status="aguardando_pagamento",
                data_solicitacao=now,
            )
            db.session.add_all([scheduled_request, canceled_request, pending_request])
            db.session.flush()
            db.session.add_all(
                [
                    ValidacaoPagamentoFinanceiro(
                        solicitacao_id=scheduled_request.id,
                        referencia_financeira=f"REC-S-{suffix[:8]}",
                        responsavel_financeiro="Equipe Financeira",
                        data_confirmacao=now,
                        registrada_por_id=admin_id,
                    ),
                    ValidacaoPagamentoFinanceiro(
                        solicitacao_id=canceled_request.id,
                        referencia_financeira=f"REC-C-{suffix[:8]}",
                        responsavel_financeiro="Equipe Financeira",
                        data_confirmacao=now,
                        registrada_por_id=admin_id,
                    ),
                    Agendamento(
                        solicitacao_id=scheduled_request.id,
                        paciente_id=self.patient_id,
                        medico_id=doctor.id,
                        sala_id=room.id,
                        data_hora=datetime.combine(today, time(14, 0)),
                        status="agendado",
                    ),
                    Agendamento(
                        solicitacao_id=canceled_request.id,
                        paciente_id=self.patient_id,
                        medico_id=doctor.id,
                        sala_id=room.id,
                        data_hora=datetime.combine(today, time(15, 0)),
                        status="cancelado",
                    ),
                    Senha(
                        codigo=f"REPORT-ATT-{suffix[:8]}",
                        tipo="normal",
                        paciente_id=self.patient_id,
                        medico_id=doctor.id,
                        sala_id=room.id,
                        status="atendido",
                        data_hora=now,
                        numero_ordem=1001,
                    ),
                    Senha(
                        codigo=f"REPORT-ABS-{suffix[:8]}",
                        tipo="normal",
                        paciente_id=self.patient_id,
                        medico_id=doctor.id,
                        sala_id=room.id,
                        status="nao_compareceu",
                        data_hora=now,
                        numero_ordem=1002,
                    ),
                ]
            )
            db.session.commit()
            other_doctor_id = doctor.id

        daily = self.client.get(
            f"/relatorios?periodo=diario&data={today.isoformat()}"
        )
        self.assertEqual(daily.status_code, 200)
        daily_body = daily.get_data(as_text=True)
        self.assertIn("R$ 425,00", daily_body)
        self.assertIn("R$ 50,00", daily_body)
        self.assertIn("Faltas", daily_body)
        self.assertIn("Cancelamentos", daily_body)

        doctor_report = self.client.get(
            f"/relatorios?periodo=diario&data={today.isoformat()}"
            f"&medico_id={other_doctor_id}"
        )
        self.assertEqual(doctor_report.status_code, 200)
        doctor_body = doctor_report.get_data(as_text=True)
        self.assertIn("Médico Secundário", doctor_body)
        self.assertNotIn("<td>Médico Teste</td>", doctor_body)
        self.assertIn("R$ 325,00", doctor_body)
        self.assertIn("R$ 50,00", doctor_body)

        doctor_csv = self.client.get(
            f"/relatorios/exportar.csv?periodo=diario&data={today.isoformat()}"
            f"&medico_id={other_doctor_id}"
        )
        self.assertEqual(doctor_csv.status_code, 200)
        doctor_csv_body = doctor_csv.get_data(as_text=True)
        self.assertIn("Médico Secundário", doctor_csv_body)
        self.assertNotIn("Médico Teste", doctor_csv_body)
        self.assertIn("325.00", doctor_csv_body)
        self.assertIn("50.00", doctor_csv_body)

        month_start = today.replace(day=1)
        next_month = (
            today.replace(year=today.year + 1, month=1, day=1)
            if today.month == 12
            else today.replace(month=today.month + 1, day=1)
        )
        month_end = next_month - timedelta(days=1)
        yearly_start = today.replace(month=1, day=1)
        yearly_end = today.replace(month=12, day=31)
        period_ranges = [
            ("mensal", month_start, month_end),
            ("anual", yearly_start, yearly_end),
        ]
        for period, start, end in period_ranges:
            response = self.client.get(
                f"/relatorios?periodo={period}&data={today.isoformat()}"
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                f"<strong>{start.isoformat()}</strong> a "
                f"<strong>{end.isoformat()}</strong>",
                response.get_data(as_text=True),
            )

        custom_start = today - timedelta(days=2)
        custom = self.client.get(
            f"/relatorios?periodo=personalizado&inicio={custom_start.isoformat()}"
            f"&fim={today.isoformat()}"
        )
        self.assertEqual(custom.status_code, 200)
        self.assertIn(
            f"<strong>{custom_start.isoformat()}</strong> a "
            f"<strong>{today.isoformat()}</strong>",
            custom.get_data(as_text=True),
        )

        empty_period = self.client.get(
            "/relatorios?periodo=personalizado&inicio=2001-01-01&fim=2001-01-02"
        )
        self.assertEqual(empty_period.status_code, 200)
        empty_body = empty_period.get_data(as_text=True)
        self.assertIn("Sem registros no período.", empty_body)
        self.assertIn("Sem agendamentos no período.", empty_body)
        self.assertIn("R$ 0,00", empty_body)

    def test_operational_reports_reject_invalid_period(self):
        self._login_as("admin", "Admin@123")
        response = self.client.get(
            "/relatorios?inicio=2026-11-15&fim=2026-11-10",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("período válido", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
