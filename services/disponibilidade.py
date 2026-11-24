from datetime import datetime, time, timedelta

from database import db
from database.models import (
    Agendamento,
    Medico,
    Usuario,
)


def erro_disponibilidade_agendamento(medico, inicio):
    sala = medico.sala
    if not sala or not sala.ativa:
        return "O médico ainda não possui uma sala ativa atribuída pelo administrador."
    if sala.status == "indisponivel":
        return "A sala atribuída ao médico não está disponível."

    fim = inicio + timedelta(minutes=30)
    conflito = Agendamento.query.filter(
        Agendamento.status.in_({"agendado", "em_atendimento"}),
        Agendamento.data_hora < fim,
        Agendamento.data_hora > inicio - timedelta(minutes=30),
        db.or_(
            Agendamento.medico_id == medico.id,
            Agendamento.sala_id == sala.id,
        ),
    ).first()
    if conflito:
        return "O médico ou a sala já está ocupado nesse horário."
    return None


def medicos_disponiveis_para_solicitacao(solicitacao, inicio):
    medicos = (
        Medico.query.join(Usuario)
        .filter(
            Medico.ativo.is_(True),
            Usuario.ativo.is_(True),
            Usuario.perfil == "medico",
            Medico.especialidade_id == solicitacao.especialidade_id,
        )
        .order_by(Medico.nome_exibicao.asc())
        .all()
    )
    return [
        medico
        for medico in medicos
        if not erro_disponibilidade_agendamento(medico, inicio)
    ]


def proximo_horario_atendimento(agora):
    minutos_do_dia = agora.hour * 60 + agora.minute
    proximo_bloco = ((minutos_do_dia // 30) + 1) * 30
    if proximo_bloco > 23 * 60:
        return None
    return datetime.combine(
        agora.date(),
        time(proximo_bloco // 60, proximo_bloco % 60),
    )


def medicos_disponiveis_para_atendimento(solicitacao, agora, medico_id=None):
    horario = proximo_horario_atendimento(agora)
    while horario is not None:
        medicos = medicos_disponiveis_para_solicitacao(solicitacao, horario)
        if medico_id is not None:
            medicos = [medico for medico in medicos if medico.id == medico_id]
        if medicos:
            return horario, medicos
        proximo_bloco = horario.hour * 60 + horario.minute + 30
        if proximo_bloco > 23 * 60:
            break
        horario = datetime.combine(
            agora.date(),
            time(proximo_bloco // 60, proximo_bloco % 60),
        )
    return None, []


def medico_presente(medico_id):
    medico = db.session.get(Medico, medico_id)
    return bool(medico and medico.presenca_ativa)
