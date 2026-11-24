import argparse
import os
from datetime import date, datetime, time, timedelta

from werkzeug.security import generate_password_hash


DEMO_PASSWORD = "123456"


def _arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Apaga os dados operacionais do banco local e recria uma massa "
            "fictícia para demonstração."
        )
    )
    parser.add_argument(
        "--confirm-clear",
        action="store_true",
        help="confirma a remoção dos dados operacionais existentes",
    )
    return parser


def _cpf_from_base(base):
    if len(base) != 9 or not base.isdigit() or len(set(base)) == 1:
        raise ValueError("A base do CPF deve conter nove dígitos não repetidos.")

    first_sum = sum(int(digit) * weight for digit, weight in zip(base, range(10, 1, -1)))
    first_digit = 0 if first_sum % 11 < 2 else 11 - first_sum % 11
    first_nine = f"{base}{first_digit}"
    second_sum = sum(
        int(digit) * weight
        for digit, weight in zip(first_nine, range(11, 1, -1))
    )
    second_digit = 0 if second_sum % 11 < 2 else 11 - second_sum % 11
    return f"{first_nine}{second_digit}"


def _create_user(Usuario, Permissao, permissions_for_profile, data):
    user = Usuario(
        nome_completo=data["nome"],
        email=data["email"],
        username=data["username"],
        senha_hash=generate_password_hash(DEMO_PASSWORD),
        perfil=data["perfil"],
        ativo=True,
    )
    user.permissoes = Permissao.query.filter(
        Permissao.codigo.in_(permissions_for_profile(data["perfil"]))
    ).all()
    return user


def _completed_visit_times(now):
    start_of_day = datetime.combine(now.date(), time.min)
    latest_slot = now.replace(
        minute=(now.minute // 30) * 30,
        second=0,
        microsecond=0,
    ) - timedelta(minutes=30)
    times = [
        latest_slot - timedelta(minutes=60),
        latest_slot - timedelta(minutes=30),
        latest_slot,
    ]
    if times[0] < start_of_day:
        latest_past_minute = max(start_of_day, now - timedelta(minutes=1))
        times = [
            max(start_of_day, latest_past_minute - timedelta(minutes=2)),
            max(start_of_day, latest_past_minute - timedelta(minutes=1)),
            latest_past_minute,
        ]
    return times


def _clear_operational_data(
    db,
    models,
    usuario_permissoes,
    admin,
):
    deletion_order = (
        models.HistoricoStatus,
        models.RegistroAuditoria,
        models.HistoricoChamada,
        models.AgendamentoSenha,
        models.PrioridadeAgendamento,
        models.Exame,
        models.Receita,
        models.Prontuario,
        models.Atendimento,
        models.Senha,
        models.Agendamento,
        models.ValidacaoPagamentoFinanceiro,
        models.ConfirmacaoPagamento,
        models.DocumentoSolicitacao,
        models.ConfirmacaoPresencaMedica,
        models.JustificativaAusenciaMedica,
        models.DisponibilidadeMedica,
        models.AusenciaMedica,
        models.Solicitacao,
        models.Medico,
        models.Sala,
        models.Servico,
        models.Especialidade,
        models.Paciente,
    )
    for model in deletion_order:
        db.session.query(model).delete(synchronize_session=False)

    for policy in models.PoliticaPrioridade.query.filter(
        models.PoliticaPrioridade.aprovada_por_id.isnot(None),
        models.PoliticaPrioridade.aprovada_por_id != admin.id,
    ):
        policy.aprovada_por_id = None

    db.session.execute(
        usuario_permissoes.delete().where(
            usuario_permissoes.c.usuario_id != admin.id
        )
    )
    models.Usuario.query.filter(
        models.Usuario.username != "admin"
    ).delete(synchronize_session=False)


def _seed_demo_data(db, models, permissions_for_profile):
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    start_of_day = datetime.combine(today, time.min)

    admin = models.Usuario.query.filter_by(username="admin").one_or_none()
    if admin is None:
        raise RuntimeError(
            "O usuário admin não foi encontrado; a massa não foi alterada."
        )

    _clear_operational_data(db, models, models.usuario_permissoes, admin)

    reception_user = _create_user(
        models.Usuario,
        models.Permissao,
        permissions_for_profile,
        {
            "nome": "Mariana Souza Ribeiro",
            "email": "recepcao@example.test",
            "username": "recepcao",
            "perfil": "recepcionista",
        },
    )
    finance_user = _create_user(
        models.Usuario,
        models.Permissao,
        permissions_for_profile,
        {
            "nome": "Paulo Henrique Martins",
            "email": "financeiro@example.test",
            "username": "financeiro",
            "perfil": "financeiro",
        },
    )
    db.session.add_all([reception_user, finance_user])
    db.session.flush()

    specialties = [
        models.Especialidade(nome="Clínica Geral", descricao="Atendimento clínico geral."),
        models.Especialidade(nome="Cardiologia", descricao="Atendimento cardiológico."),
        models.Especialidade(nome="Pediatria", descricao="Atendimento pediátrico."),
    ]
    rooms = [
        models.Sala(
            nome=f"Consultório {number:02d}",
            setor="consulta",
            status="disponivel",
            ativa=True,
        )
        for number in range(1, 4)
    ]
    db.session.add_all(specialties + rooms)
    db.session.flush()

    doctor_definitions = (
        (
            "Dr. Carlos Henrique Almeida",
            "dr.carlos",
            "carlos@example.test",
            "CRM-SP 100001",
            specialties[0],
            rooms[0],
        ),
        (
            "Dra. Fernanda Martins Costa",
            "dra.fernanda",
            "fernanda@example.test",
            "CRM-SP 100002",
            specialties[1],
            rooms[1],
        ),
        (
            "Dr. Rafael Oliveira Souza",
            "dr.rafael",
            "rafael@example.test",
            "CRM-SP 100003",
            specialties[2],
            rooms[2],
        ),
    )
    doctors = []
    for name, username, email, crm, specialty, room in doctor_definitions:
        user = _create_user(
            models.Usuario,
            models.Permissao,
            permissions_for_profile,
            {
                "nome": name,
                "email": email,
                "username": username,
                "perfil": "medico",
            },
        )
        db.session.add(user)
        db.session.flush()
        doctor = models.Medico(
            usuario_id=user.id,
            especialidade_id=specialty.id,
            sala_id=room.id,
            crm=crm,
            nome_exibicao=name,
            ativo=True,
            status="disponivel",
            presenca_ativa=True,
        )
        db.session.add(doctor)
        doctors.append(doctor)
    db.session.flush()

    service_definitions = (
        ("Consulta Clínica Geral", "Consulta", 150.00, specialties[0]),
        ("Consulta Cardiológica", "Consulta", 250.00, specialties[1]),
        ("Eletrocardiograma", "Exame", 120.00, specialties[1]),
        ("Consulta Pediátrica", "Consulta", 180.00, specialties[2]),
    )
    services = [
        models.Servico(
            nome=name,
            categoria=category,
            descricao=f"Serviço demonstrativo: {name.lower()}.",
            valor=value,
            ativo=True,
            especialidade_id=specialty.id,
        )
        for name, category, value, specialty in service_definitions
    ]
    db.session.add_all(services)
    db.session.flush()

    patient_definitions = (
        (
            "Ana Beatriz Carvalho",
            "123456789",
            date(1987, 4, 12),
            "11990001001",
            "Rua das Acácias, 123 - São Paulo/SP",
        ),
        (
            "Bruno Eduardo Ferreira",
            "987654321",
            date(1979, 9, 3),
            "11990001002",
            "Avenida do Ipê, 245 - São Paulo/SP",
        ),
        (
            "Camila Rodrigues Nogueira",
            "314159265",
            date(1994, 2, 27),
            "11990001003",
            "Rua das Palmeiras, 78 - São Paulo/SP",
        ),
        (
            "Daniel Augusto Barros",
            "271828182",
            date(1968, 11, 19),
            "11990001004",
            "Rua do Bosque, 410 - São Paulo/SP",
        ),
        (
            "Eduarda Lima Monteiro",
            "456789123",
            date(2001, 6, 8),
            "11990001005",
            "Alameda das Flores, 56 - São Paulo/SP",
        ),
        (
            "Felipe Moraes Teixeira",
            "741852963",
            date(1983, 1, 30),
            "11990001006",
            "Rua Horizonte Azul, 91 - São Paulo/SP",
        ),
        (
            "Gabriela Pinto Azevedo",
            "159357246",
            date(1990, 7, 14),
            "11990001007",
            "Avenida Central, 302 - São Paulo/SP",
        ),
        (
            "Heitor Costa Figueiredo",
            "852741369",
            date(2014, 5, 22),
            "11990001008",
            "Rua das Andorinhas, 37 - São Paulo/SP",
        ),
    )
    patients = [
        models.Paciente(
            nome_completo=name,
            cpf=_cpf_from_base(cpf_base),
            data_nascimento=birth_date,
            telefone=phone,
            endereco=address,
            ativo=True,
        )
        for name, cpf_base, birth_date, phone, address in patient_definitions
    ]
    db.session.add_all(patients)
    db.session.flush()

    visit_times = _completed_visit_times(now)
    completed_visits = (
        (0, 0, 0, "Pix"),
        (1, 1, 1, "Cartão"),
        (2, 3, 2, "Convênio"),
    )
    for ordinal, (patient_index, service_index, doctor_index, payment_method) in enumerate(
        completed_visits,
        start=1,
    ):
        visit_time = visit_times[ordinal - 1]
        payment_time = max(start_of_day, visit_time - timedelta(minutes=10))
        request_time = max(start_of_day, payment_time - timedelta(minutes=5))
        patient = patients[patient_index]
        service = services[service_index]
        doctor = doctors[doctor_index]
        request_code = f"DEMO-{today:%Y%m%d}-{ordinal:03d}"
        financial_reference = f"DEMO-REC-{today:%Y%m%d}-{ordinal:03d}"
        request_record = models.Solicitacao(
            codigo=request_code,
            paciente_id=patient.id,
            servico_id=service.id,
            especialidade_id=service.especialidade_id,
            medico_id=doctor.id,
            valor_snapshot=service.valor,
            status="concluido",
            data_solicitacao=request_time,
            observacoes="Registro fictício para demonstração.",
        )
        db.session.add(request_record)
        db.session.flush()

        validation = models.ValidacaoPagamentoFinanceiro(
            solicitacao_id=request_record.id,
            referencia_financeira=financial_reference,
            responsavel_financeiro=finance_user.nome_completo,
            data_confirmacao=payment_time,
            registrada_por_id=finance_user.id,
        )
        confirmation = models.ConfirmacaoPagamento(
            solicitacao_id=request_record.id,
            referencia_recibo=financial_reference,
            data_confirmacao=payment_time,
            responsavel=finance_user.nome_completo,
            origem_confirmacao="financeiro",
            observacao=f"Forma de pagamento: {payment_method}. Massa fictícia de demonstração.",
        )
        appointment = models.Agendamento(
            solicitacao_id=request_record.id,
            paciente_id=patient.id,
            medico_id=doctor.id,
            sala_id=doctor.sala_id,
            data_hora=visit_time,
            status="concluido",
            created_at=request_time,
        )
        db.session.add_all([validation, confirmation, appointment])
        db.session.flush()

        ticket = models.Senha(
            codigo=f"DEMO-{today:%Y%m%d}-{ordinal:03d}",
            tipo="normal",
            paciente_id=patient.id,
            medico_id=doctor.id,
            sala_id=doctor.sala_id,
            status="atendido",
            prioridade=False,
            data_hora=visit_time,
            numero_ordem=ordinal,
            criado_em=visit_time,
        )
        db.session.add(ticket)
        db.session.flush()
        db.session.add(
            models.AgendamentoSenha(
                agendamento_id=appointment.id,
                senha_id=ticket.id,
            )
        )

        visit_end = min(visit_time + timedelta(minutes=30), now)
        db.session.add(
            models.Atendimento(
                paciente_id=patient.id,
                medico_id=doctor.id,
                sala_id=doctor.sala_id,
                senha_id=ticket.id,
                status="concluido",
                data_inicio=visit_time,
                data_fim=visit_end,
            )
        )

        status_events = (
            (
                "solicitacao",
                request_record.id,
                "aguardando_pagamento",
                "confirmado",
                payment_time,
                None,
            ),
            (
                "solicitacao",
                request_record.id,
                "confirmado",
                "agendado",
                visit_time,
                appointment.id,
            ),
            (
                "solicitacao",
                request_record.id,
                "agendado",
                "concluido",
                visit_end,
                appointment.id,
            ),
            (
                "agendamento",
                appointment.id,
                None,
                "agendado",
                visit_time,
                appointment.id,
            ),
            (
                "agendamento",
                appointment.id,
                "agendado",
                "concluido",
                visit_end,
                appointment.id,
            ),
            (
                "senha",
                ticket.id,
                None,
                "aguardando",
                visit_time,
                appointment.id,
            ),
            (
                "senha",
                ticket.id,
                "aguardando",
                "atendido",
                visit_end,
                appointment.id,
            ),
        )
        for entity, entity_id, old_status, new_status, changed_at, appointment_id in status_events:
            db.session.add(
                models.HistoricoStatus(
                    entidade=entity,
                    entidade_id=entity_id,
                    status_anterior=old_status,
                    status_novo=new_status,
                    alterado_por_id=finance_user.id,
                    solicitacao_id=request_record.id,
                    agendamento_id=appointment_id,
                    criado_em=changed_at,
                )
            )

        audit_events = (
            ("solicitacao", request_record.id, "validar_pagamento_financeiro"),
            ("solicitacao", request_record.id, "liberar_para_atendimento"),
            ("agendamento", appointment.id, "criar_atendimento_demonstrativo"),
            ("senha", ticket.id, "emitir"),
            ("senha", ticket.id, "concluir_atendimento_manual"),
        )
        for entity, entity_id, action in audit_events:
            db.session.add(
                models.RegistroAuditoria(
                    usuario_id=finance_user.id,
                    entidade=entity,
                    entidade_id=entity_id,
                    acao=action,
                    detalhe="Massa fictícia de demonstração.",
                    ip="127.0.0.1",
                    criado_em=visit_end,
                )
            )

    pending_requests = (
        (6, 2, 1, "Atendimento pendente de pagamento no financeiro."),
        (7, 3, 2, "Consulta pediátrica pendente de pagamento."),
    )
    for ordinal, (patient_index, service_index, doctor_index, note) in enumerate(
        pending_requests,
        start=1,
    ):
        request_record = models.Solicitacao(
            codigo=f"DEMO-PEND-{today:%Y%m%d}-{ordinal:02d}",
            paciente_id=patients[patient_index].id,
            servico_id=services[service_index].id,
            especialidade_id=services[service_index].especialidade_id,
            medico_id=doctors[doctor_index].id,
            valor_snapshot=services[service_index].valor,
            status="aguardando_pagamento",
            data_solicitacao=max(start_of_day, now - timedelta(minutes=ordinal * 3)),
            observacoes=note,
        )
        db.session.add(request_record)

    db.session.flush()
    return {
        "usuarios_operacionais": models.Usuario.query.filter(
            models.Usuario.username != "admin"
        ).count(),
        "especialidades": models.Especialidade.query.count(),
        "salas": models.Sala.query.count(),
        "medicos": models.Medico.query.count(),
        "servicos": models.Servico.query.count(),
        "pacientes": models.Paciente.query.count(),
        "atendimentos_concluidos_hoje": models.Atendimento.query.filter(
            models.Atendimento.status == "concluido",
            models.Atendimento.data_inicio >= start_of_day,
        ).count(),
        "solicitacoes_aguardando_pagamento": models.Solicitacao.query.filter_by(
            status="aguardando_pagamento"
        ).count(),
    }


def main():
    parser = _arguments()
    args = parser.parse_args()
    if not args.confirm_clear:
        parser.error("este script apaga dados; execute novamente com --confirm-clear.")

    if os.environ.get("APP_ENV", "development").lower() == "production":
        parser.error("seed_demo.py não pode ser executado com APP_ENV=production.")

    from config import Config

    if not Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"):
        parser.error(
            "seed_demo.py só pode operar em banco SQLite local; confira DATABASE_URL."
        )
    if ":memory:" in Config.SQLALCHEMY_DATABASE_URI:
        parser.error("configure um arquivo SQLite persistente para a massa de demonstração.")

    from app import app
    from database import db
    from database import models
    from services.permissions import permissions_for_profile

    with app.app_context():
        with db.session.begin():
            summary = _seed_demo_data(db, models, permissions_for_profile)

    print("Massa fictícia de demonstração criada com sucesso.")
    for label, count in summary.items():
        print(f"{label}: {count}")
    print(f"Senha padrão das contas de demonstração: {DEMO_PASSWORD}")
    print("Contas: recepcao, financeiro, dr.carlos, dra.fernanda, dr.rafael")
    print("O usuário admin e as permissões existentes foram preservados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
