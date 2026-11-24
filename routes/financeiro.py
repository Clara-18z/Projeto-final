from datetime import datetime, time, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import (
    Agendamento,
    AgendamentoSenha,
    ConfirmacaoPagamento,
    HistoricoStatus,
    PoliticaPrioridade,
    Senha,
    Solicitacao,
    ValidacaoPagamentoFinanceiro,
)
from services.auditoria import registrar_consulta_auditoria, registrar_evento_auditoria
from services.disponibilidade import medicos_disponiveis_para_atendimento
from services.permissions import has_profile_permission
from services.prioridades import PRIORITY_CATEGORIES
from services.senhas import criar_senha_para_agendamento

financeiro_bp = Blueprint("financeiro", __name__, template_folder="../templates")

PAYMENT_METHODS = ("Pix", "Dinheiro", "Cartão", "Convênio")


def _require_permission():
    if not has_profile_permission(
        current_user,
        "financeiro",
        "gerenciar_financeiro",
    ):
        flash("Você não tem permissão para operar o financeiro.", "error")
        return False
    return True


@financeiro_bp.route("/financeiro")
@login_required
def index():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    inicio = datetime.combine(datetime.now().date(), time.min)
    fim = inicio + timedelta(days=1)
    total_recebido_hoje = (
        db.session.query(func.coalesce(func.sum(Solicitacao.valor_snapshot), 0))
        .join(
            ValidacaoPagamentoFinanceiro,
            ValidacaoPagamentoFinanceiro.solicitacao_id == Solicitacao.id,
        )
        .filter(
            ValidacaoPagamentoFinanceiro.data_confirmacao >= inicio,
            ValidacaoPagamentoFinanceiro.data_confirmacao < fim,
        )
        .scalar()
    )
    solicitacoes_pendentes = (
        Solicitacao.query.filter_by(status="aguardando_pagamento")
        .order_by(Solicitacao.data_solicitacao.asc(), Solicitacao.id.asc())
        .all()
    )
    agendamentos_aguardando_senha = (
        Agendamento.query.join(Solicitacao)
        .filter(
            Agendamento.data_hora >= inicio,
            Agendamento.data_hora < fim,
            Agendamento.status == "agendado",
            Solicitacao.status.in_({"confirmado", "agendado"}),
            Solicitacao.validacao_pagamento.has(),
            ~Agendamento.senha_vinculo.has(),
        )
        .order_by(Agendamento.data_hora.asc(), Agendamento.id.asc())
        .all()
    )
    senhas_emitidas_hoje = (
        Senha.query.join(AgendamentoSenha, AgendamentoSenha.senha_id == Senha.id)
        .join(Agendamento, Agendamento.id == AgendamentoSenha.agendamento_id)
        .join(Solicitacao, Solicitacao.id == Agendamento.solicitacao_id)
        .join(
            ValidacaoPagamentoFinanceiro,
            ValidacaoPagamentoFinanceiro.solicitacao_id == Solicitacao.id,
        )
        .filter(
            Senha.data_hora >= inicio,
            Senha.data_hora < fim,
        )
        .order_by(
            Senha.data_hora.desc(),
            Senha.numero_ordem.desc(),
        )
        .all()
    )
    registrar_consulta_auditoria("solicitacao", solicitacoes_pendentes)
    registrar_consulta_auditoria("agendamento", agendamentos_aguardando_senha)
    registrar_consulta_auditoria("senha", senhas_emitidas_hoje)
    return render_template(
        "financeiro/index.html",
        total_recebido_hoje=float(total_recebido_hoje or 0),
        total_pendentes=len(solicitacoes_pendentes),
        solicitacoes=solicitacoes_pendentes,
        agendamentos_aguardando_senha=agendamentos_aguardando_senha,
        senhas_emitidas_hoje=senhas_emitidas_hoje,
        formas_pagamento=PAYMENT_METHODS,
        politica_prioridade=db.session.get(PoliticaPrioridade, 1),
        categorias_prioridade=PRIORITY_CATEGORIES,
    )


@financeiro_bp.route(
    "/financeiro/solicitacoes/<int:solicitacao_id>/confirmar",
    methods=["POST"],
)
@login_required
def confirmar_pagamento(solicitacao_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    forma_pagamento = request.form.get("forma_pagamento", "").strip()
    referencia = request.form.get("referencia", "").strip()
    observacao = request.form.get("observacao", "").strip()

    if forma_pagamento not in PAYMENT_METHODS:
        flash("Selecione uma forma de pagamento válida.", "error")
        return redirect(url_for("financeiro.index"))
    if len(referencia) > 80:
        flash("A referência deve ter no máximo 80 caracteres.", "error")
        return redirect(url_for("financeiro.index"))
    if solicitacao.status != "aguardando_pagamento" or solicitacao.validacao_pagamento:
        flash("Esta solicitação não está mais aguardando validação financeira.", "error")
        return redirect(url_for("financeiro.index"))

    agora = datetime.now()
    referencia_registrada = (
        f"{forma_pagamento}: {referencia}" if referencia else forma_pagamento
    )
    db.session.add(
        ValidacaoPagamentoFinanceiro(
            solicitacao_id=solicitacao.id,
            referencia_financeira=referencia_registrada,
            responsavel_financeiro=current_user.nome_completo,
            data_confirmacao=agora,
            registrada_por_id=current_user.id,
        )
    )
    detalhe_pagamento = f"Forma de pagamento: {forma_pagamento}."
    if observacao:
        detalhe_pagamento = f"{detalhe_pagamento} {observacao}"
    if solicitacao.confirmacao_pagamento:
        notas_existentes = solicitacao.confirmacao_pagamento.observacao or ""
        solicitacao.confirmacao_pagamento.observacao = "\n".join(
            value for value in (notas_existentes, detalhe_pagamento) if value
        )
    else:
        db.session.add(
            ConfirmacaoPagamento(
                solicitacao_id=solicitacao.id,
                referencia_recibo=referencia or forma_pagamento,
                responsavel=current_user.nome_completo,
                data_confirmacao=agora,
                origem_confirmacao="financeiro",
                observacao=detalhe_pagamento,
            )
        )

    status_anterior = solicitacao.status
    solicitacao.status = "confirmado"
    db.session.add(
        HistoricoStatus(
            entidade="solicitacao",
            entidade_id=solicitacao.id,
            status_anterior=status_anterior,
            status_novo=solicitacao.status,
            alterado_por_id=current_user.id,
            solicitacao_id=solicitacao.id,
        )
    )
    registrar_evento_auditoria(
        "solicitacao",
        solicitacao.id,
        "validar_pagamento_financeiro",
    )

    horario_atendimento, medicos = medicos_disponiveis_para_atendimento(
        solicitacao,
        agora,
        medico_id=solicitacao.medico_id,
    )
    senha = None
    medico = medicos[0] if medicos else None
    if horario_atendimento and medico:
        agendamento = Agendamento(
            solicitacao_id=solicitacao.id,
            paciente_id=solicitacao.paciente_id,
            medico_id=medico.id,
            sala_id=medico.sala_id,
            data_hora=horario_atendimento,
            status="agendado",
        )
        db.session.add(agendamento)
        db.session.flush()
        solicitacao.medico_id = medico.id
        solicitacao.status = "agendado"
        db.session.add(
            HistoricoStatus(
                entidade="solicitacao",
                entidade_id=solicitacao.id,
                status_anterior="confirmado",
                status_novo="agendado",
                alterado_por_id=current_user.id,
                solicitacao_id=solicitacao.id,
                agendamento_id=agendamento.id,
            )
        )
        db.session.add(
            HistoricoStatus(
                entidade="agendamento",
                entidade_id=agendamento.id,
                status_anterior=None,
                status_novo="agendado",
                alterado_por_id=current_user.id,
                solicitacao_id=solicitacao.id,
                agendamento_id=agendamento.id,
            )
        )
        senha = criar_senha_para_agendamento(
            agendamento,
            prioridade=agendamento.prioridade,
            agora=agora,
        )
        registrar_evento_auditoria(
            "agendamento",
            agendamento.id,
            "criar_atendimento_apos_pagamento",
        )
        registrar_evento_auditoria("senha", senha.id, "emitir")
        registrar_evento_auditoria(
            "solicitacao",
            solicitacao.id,
            "liberar_para_atendimento",
        )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception(
            "Unable to finalize financial confirmation for request %s.",
            solicitacao_id,
        )
        flash(
            "Não foi possível salvar a confirmação por um conflito de dados. "
            "Atualize a tela e confira o status da solicitação antes de tentar novamente.",
            "error",
        )
        return redirect(url_for("financeiro.index"))

    if senha:
        current_app.extensions["socketio"].emit(
            "fila_atualizada",
            {
                "medico_id": medico.id,
                "senha_id": senha.id,
            },
        )
        flash(
            f"Pagamento confirmado. Senha {senha.codigo_exibicao} emitida para "
            f"{medico.nome_exibicao}, {medico.sala.nome}.",
            "info",
        )
    else:
        flash(
            "Pagamento confirmado. Não foi possível emitir uma senha agora; "
            "a solicitação está liberada para agendamento.",
            "info",
        )
    return redirect(url_for("financeiro.index"))
