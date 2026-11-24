from datetime import datetime, time, timedelta

from sqlalchemy import func

from database import db
from database.models import AgendamentoSenha, HistoricoStatus, Senha
from services.auditoria import registrar_evento_auditoria


def criar_senha_para_agendamento(agendamento, prioridade=False, agora=None):
    agora = agora or datetime.now()
    inicio = datetime.combine(agora.date(), time.min)
    fim = inicio + timedelta(days=1)
    ultimo_numero = (
        db.session.query(func.max(Senha.numero_ordem))
        .filter(Senha.data_hora >= inicio, Senha.data_hora < fim)
        .scalar()
    ) or 0
    numero_ordem = ultimo_numero + 1
    prefixo = "P" if prioridade else "N"
    codigo = f"{prefixo}-{inicio:%Y%m%d}-{numero_ordem:03d}"
    senha = Senha(
        codigo=codigo,
        tipo="preferencial" if prioridade else "normal",
        paciente_id=agendamento.paciente_id,
        medico_id=agendamento.medico_id,
        sala_id=agendamento.sala_id,
        status="aguardando",
        prioridade=prioridade,
        data_hora=agora,
        numero_ordem=numero_ordem,
    )
    db.session.add(senha)
    db.session.flush()
    db.session.add(
        AgendamentoSenha(
            agendamento_id=agendamento.id,
            senha_id=senha.id,
        )
    )
    return senha


def concluir_fluxo_fila(senha, usuario_id):
    status_anterior = senha.status
    senha.status = "atendido"
    agendamento = (
        senha.vinculo_agendamento.agendamento
        if senha.vinculo_agendamento
        else None
    )
    solicitacao = agendamento.solicitacao if agendamento else None
    if agendamento:
        status_agendamento_anterior = agendamento.status
        agendamento.status = "concluido"
        if solicitacao:
            solicitacao.status = "concluido"
        db.session.add(
            HistoricoStatus(
                entidade="agendamento",
                entidade_id=agendamento.id,
                status_anterior=status_agendamento_anterior,
                status_novo="concluido",
                alterado_por_id=usuario_id,
                solicitacao_id=solicitacao.id if solicitacao else None,
                agendamento_id=agendamento.id,
            )
        )
        registrar_evento_auditoria(
            "agendamento",
            agendamento.id,
            "concluir_atendimento_manual",
        )
        if solicitacao:
            registrar_evento_auditoria(
                "solicitacao",
                solicitacao.id,
                "concluir_atendimento_manual",
            )
    db.session.add(
        HistoricoStatus(
            entidade="senha",
            entidade_id=senha.id,
            status_anterior=status_anterior,
            status_novo="atendido",
            alterado_por_id=usuario_id,
            solicitacao_id=solicitacao.id if solicitacao else None,
            agendamento_id=agendamento.id if agendamento else None,
        )
    )
    registrar_evento_auditoria("senha", senha.id, "concluir_atendimento_manual")
    return agendamento, solicitacao
