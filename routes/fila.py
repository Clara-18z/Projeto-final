from datetime import datetime, time, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import case

from database import db
from database.models import (
    Agendamento,
    AgendamentoSenha,
    Atendimento,
    HistoricoChamada,
    HistoricoStatus,
    PoliticaPrioridade,
    PrioridadeAgendamento,
    Senha,
)
from services.auditoria import registrar_consulta_auditoria, registrar_evento_auditoria
from services.disponibilidade import medico_presente
from services.permissions import has_profile_permission
from services.prioridades import (
    PRIORITY_CATEGORIES,
    validate_priority_registration,
)
from services.senhas import criar_senha_para_agendamento

fila_bp = Blueprint("fila", __name__, template_folder="../templates")


def _require_permission():
    if current_user.perfil == "medico":
        allowed = (
            current_user.medico is not None
            and has_profile_permission(
                current_user,
                "medico",
                {"gerenciar_atendimento", "acessar_dashboard"},
            )
        )
    else:
        allowed = has_profile_permission(
            current_user,
            "recepcionista",
            {"gerenciar_fila", "acessar_dashboard"},
        )
    if not allowed:
        flash("Você não tem permissão para acompanhar a fila.", "error")
        return False
    return True


def _require_reception_operation():
    if not has_profile_permission(
        current_user,
        "recepcionista",
        {"gerenciar_fila", "acessar_dashboard"},
    ):
        flash("Somente a recepção pode registrar não comparecimento.", "error")
        return False
    return True


def _require_finance_operation():
    if not has_profile_permission(
        current_user,
        "financeiro",
        "gerenciar_financeiro",
    ):
        flash("Somente o financeiro pode emitir senhas.", "error")
        return False
    return True


def _ordered_ticket_query():
    priority_rank = case(
        (
            db.and_(
                Senha.prioridade.is_(True),
                PrioridadeAgendamento.id.is_not(None),
                PrioridadeAgendamento.categoria != "doador_de_sangue",
            ),
            0,
        ),
        (
            db.and_(
                Senha.prioridade.is_(True),
                PrioridadeAgendamento.categoria == "doador_de_sangue",
            ),
            1,
        ),
        else_=2,
    )
    return (
        Senha.query.outerjoin(
            AgendamentoSenha,
            AgendamentoSenha.senha_id == Senha.id,
        )
        .outerjoin(
            PrioridadeAgendamento,
            PrioridadeAgendamento.agendamento_id == AgendamentoSenha.agendamento_id,
        )
        .order_by(priority_rank, Senha.numero_ordem.asc())
    )


def _policy():
    return db.session.get(PoliticaPrioridade, 1)


def _today_range():
    inicio = datetime.combine(datetime.now().date(), time.min)
    return inicio, inicio + timedelta(days=1)


def _painel_publico_payload():
    inicio, fim = _today_range()
    chamadas = (
        HistoricoChamada.query.join(Senha)
        .filter(
            HistoricoChamada.data_hora >= inicio,
            HistoricoChamada.data_hora < fim,
            HistoricoChamada.status == "chamada",
        )
        .order_by(HistoricoChamada.data_hora.desc(), HistoricoChamada.id.desc())
        .limit(5)
        .all()
    )
    return {
        "chamadas": [
            {
                "codigo": chamada.senha.codigo_exibicao,
                "paciente": chamada.senha.paciente.nome_completo,
                "sala": chamada.senha.sala.nome,
                "hora": chamada.data_hora.strftime("%H:%M:%S"),
            }
            for chamada in chamadas
        ]
    }


@fila_bp.route("/painel")
def painel_publico():
    return render_template("fila/painel_publico.html")


@fila_bp.route("/api/painel")
def api_painel_publico():
    response = jsonify(_painel_publico_payload())
    response.headers["Cache-Control"] = "no-store"
    return response


@fila_bp.route("/fila")
@login_required
def listar():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    inicio, fim = _today_range()
    senha_query = _ordered_ticket_query().filter(
        Senha.data_hora >= inicio,
        Senha.data_hora < fim,
    )
    if current_user.perfil == "medico":
        senha_query = senha_query.filter(Senha.medico_id == current_user.medico.id)
        proxima_senha = (
            _ordered_ticket_query()
            .filter(
                Senha.medico_id == current_user.medico.id,
                Senha.status == "aguardando",
                Senha.data_hora >= inicio,
                Senha.data_hora < fim,
            )
            .first()
        )
    else:
        proxima_senha = None
    senhas = senha_query.all()
    atendimentos_por_senha = {}
    if current_user.perfil == "medico" and senhas:
        atendimentos = Atendimento.query.filter(
            Atendimento.medico_id == current_user.medico.id,
            Atendimento.senha_id.in_([senha.id for senha in senhas]),
        ).all()
        atendimentos_por_senha = {
            atendimento.senha_id: atendimento for atendimento in atendimentos
        }
    registrar_consulta_auditoria("senha", senhas)
    return render_template(
        "fila/lista.html",
        senhas=senhas,
        atendimentos_por_senha=atendimentos_por_senha,
        data_atual=inicio.date(),
        pode_operar_recepcao=current_user.perfil == "recepcionista",
        pode_chamar=has_profile_permission(
            current_user,
            "medico",
            "gerenciar_atendimento",
        ),
        pode_registrar_politica=has_profile_permission(
            current_user,
            "administrador",
            "gerenciar_medicos",
        ),
        proxima_senha_id=proxima_senha.id if proxima_senha else None,
    )


@fila_bp.route("/fila/emitir/<int:agendamento_id>", methods=["POST"])
@login_required
def emitir(agendamento_id):
    if not _require_finance_operation():
        return redirect(url_for("auth.dashboard"))

    agendamento = Agendamento.query.get_or_404(agendamento_id)
    inicio, fim = _today_range()
    if agendamento.data_hora < inicio or agendamento.data_hora >= fim:
        flash("Só é possível emitir senha para agendamento de hoje.", "error")
        return redirect(url_for("financeiro.index"))
    if agendamento.status != "agendado":
        flash("Este agendamento não está ativo.", "error")
        return redirect(url_for("financeiro.index"))
    if (
        not agendamento.solicitacao.validacao_pagamento
        or agendamento.solicitacao.status not in {"confirmado", "agendado"}
    ):
        flash(
            "A senha só pode ser emitida após a validação do pagamento.",
            "error",
        )
        return redirect(url_for("financeiro.index"))
    if (
        not agendamento.medico.ativo
        or not agendamento.medico.usuario.ativo
        or agendamento.medico.usuario.perfil != "medico"
        or not agendamento.sala.ativa
    ):
        flash(
            "O médico ou a sala do agendamento não está disponível. Solicite revisão administrativa.",
            "error",
        )
        return redirect(url_for("financeiro.index"))
    if agendamento.senha_vinculo:
        flash("Este agendamento já possui uma senha emitida.", "error")
        return redirect(url_for("financeiro.index"))

    categoria = request.form.get("categoria_prioridade", "").strip()
    prioridade = bool(categoria)
    prioridade_validada = None
    data_doacao = None
    if prioridade:
        policy = _policy()
        if (
            policy is None
            or not policy.aprovada
            or categoria not in (policy.categorias_habilitadas or [])
        ):
            flash(
                "A política ou a categoria de prioridade ainda não está aprovada pela direção.",
                "error",
            )
            return redirect(url_for("financeiro.index"))
        data_doacao_texto = request.form.get("data_doacao", "").strip()
        if data_doacao_texto:
            try:
                data_doacao = datetime.strptime(data_doacao_texto, "%Y-%m-%d").date()
            except ValueError:
                data_doacao = None
        erro_prioridade = validate_priority_registration(
            categoria,
            request.form.get("comprovacao_conferida") == "on",
            data_doacao,
        )
        if erro_prioridade:
            flash(erro_prioridade, "error")
            return redirect(url_for("financeiro.index"))
        prioridade_validada = PrioridadeAgendamento(
            agendamento_id=agendamento.id,
            categoria=categoria,
            comprovacao_conferida=True,
            data_doacao=data_doacao,
            registrada_por_id=current_user.id,
        )

    senha = criar_senha_para_agendamento(
        agendamento,
        prioridade=prioridade,
        agora=datetime.now(),
    )
    if prioridade_validada:
        db.session.add(prioridade_validada)
        agendamento.prioridade = True
    registrar_evento_auditoria("senha", senha.id, "emitir")
    if prioridade:
        registrar_evento_auditoria(
            "prioridade_agendamento",
            agendamento.id,
            "registrar",
        )
    db.session.commit()
    current_app.extensions["socketio"].emit(
        "fila_atualizada",
        {
            "medico_id": agendamento.medico_id,
            "senha_id": senha.id,
        },
    )
    flash(
        f"Senha {senha.codigo_exibicao} emitida para {agendamento.paciente.nome_completo}.",
        "info",
    )
    return redirect(url_for("financeiro.index"))


@fila_bp.route("/fila/<int:senha_id>/chamar", methods=["POST"])
@login_required
def chamar(senha_id):
    if not (
        current_user.perfil == "medico"
        and current_user.medico is not None
        and current_user.medico.ativo
        and has_profile_permission(
            current_user,
            "medico",
            "gerenciar_atendimento",
        )
    ):
        flash("Somente o médico responsável pode chamar pacientes da própria fila.", "error")
        return redirect(url_for("auth.dashboard"))

    senha = Senha.query.get_or_404(senha_id)
    if senha.medico_id != current_user.medico.id:
        flash("Você só pode chamar pacientes da sua própria fila.", "error")
        return redirect(url_for("fila.listar"))
    if not medico_presente(current_user.medico.id):
        flash(
            "Sua presença está inativa. Saia e entre novamente no sistema antes de chamar pacientes.",
            "error",
        )
        return redirect(url_for("fila.listar"))
    if senha.status != "aguardando":
        flash("Somente senhas aguardando podem ser chamadas.", "error")
        return redirect(url_for("fila.listar"))
    if Senha.query.filter(
        Senha.medico_id == current_user.medico.id,
        Senha.status.in_({"chamada", "em_atendimento"}),
    ).first():
        flash("Finalize ou encerre a chamada atual antes de chamar outro paciente.", "error")
        return redirect(url_for("fila.listar"))
    if not senha.medico_id or not senha.sala_id:
        flash("A senha não possui médico e sala associados; verifique o agendamento.", "error")
        return redirect(url_for("fila.listar"))
    inicio, fim = _today_range()
    proxima_senha = (
        _ordered_ticket_query()
        .filter(
            Senha.medico_id == current_user.medico.id,
            Senha.status == "aguardando",
            Senha.data_hora >= inicio,
            Senha.data_hora < fim,
        )
        .first()
    )
    if proxima_senha is None or proxima_senha.id != senha.id:
        flash("Chame primeiro a próxima senha da sua fila.", "error")
        return redirect(url_for("fila.listar"))
    atendimento = Atendimento.query.filter_by(senha_id=senha.id).one_or_none()
    if atendimento and (
        atendimento.medico_id != current_user.medico.id
        or atendimento.status != "em_andamento"
    ):
        flash("Este atendimento não pode ser chamado novamente por este médico.", "error")
        return redirect(url_for("fila.listar"))

    hora_chamada = datetime.now()
    senha.status = "chamada"
    db.session.add(
        HistoricoChamada(
            senha_id=senha.id,
            paciente_id=senha.paciente_id,
            medico_id=senha.medico_id,
            sala_id=senha.sala_id,
            status="chamada",
            data_hora=hora_chamada,
        )
    )
    if atendimento is None:
        atendimento = Atendimento(
            paciente_id=senha.paciente_id,
            medico_id=senha.medico_id,
            sala_id=senha.sala_id,
            senha_id=senha.id,
            status="em_andamento",
            data_inicio=datetime.utcnow(),
        )
        db.session.add(atendimento)
        db.session.flush()
        db.session.add(
            HistoricoStatus(
                entidade="atendimento",
                entidade_id=atendimento.id,
                status_anterior=None,
                status_novo="em_andamento",
                alterado_por_id=current_user.id,
            )
        )
        registrar_evento_auditoria(
            "atendimento",
            atendimento.id,
            "iniciar_atendimento",
        )
    registrar_evento_auditoria("senha", senha.id, "chamar")
    db.session.commit()
    flash(f"Senha {senha.codigo_exibicao} chamada para atendimento.", "info")
    return redirect(url_for("fila.listar"))


@fila_bp.route("/fila/<int:senha_id>/concluir-manual", methods=["POST"])
@login_required
def concluir_manual(senha_id):
    if not (
        current_user.perfil == "medico"
        and current_user.medico is not None
        and current_user.medico.ativo
        and has_profile_permission(
            current_user,
            "medico",
            "gerenciar_atendimento",
        )
    ):
        flash("Somente o médico responsável pode concluir o atendimento.", "error")
        return redirect(url_for("auth.dashboard"))

    senha = Senha.query.get_or_404(senha_id)
    if senha.medico_id != current_user.medico.id:
        flash("Você só pode concluir atendimentos da sua própria fila.", "error")
        return redirect(url_for("fila.listar"))
    if senha.status not in {"chamada", "em_atendimento"}:
        flash("Somente uma senha chamada ou em atendimento pode ser concluída.", "error")
        return redirect(url_for("fila.listar"))

    atendimento = Atendimento.query.filter_by(senha_id=senha.id).one_or_none()
    if atendimento and atendimento.medico_id != current_user.medico.id:
        flash("O prontuário pertence a outro médico responsável.", "error")
        return redirect(url_for("fila.listar"))
    if atendimento is None:
        if not senha.sala_id:
            flash(
                "A senha não possui sala associada; não foi possível iniciar o prontuário.",
                "error",
            )
            return redirect(url_for("fila.listar"))
        atendimento = Atendimento(
            paciente_id=senha.paciente_id,
            medico_id=senha.medico_id,
            sala_id=senha.sala_id,
            senha_id=senha.id,
            status="em_andamento",
            data_inicio=datetime.utcnow(),
        )
        db.session.add(atendimento)
        db.session.flush()
        db.session.add(
            HistoricoStatus(
                entidade="atendimento",
                entidade_id=atendimento.id,
                status_anterior=None,
                status_novo="em_andamento",
                alterado_por_id=current_user.id,
            )
        )
        registrar_evento_auditoria("atendimento", atendimento.id, "iniciar_atendimento")
        db.session.commit()

    if atendimento.status == "em_andamento":
        return redirect(
            url_for("atendimento.prontuario", atendimento_id=atendimento.id)
        )
    if atendimento.status in {"finalizado", "concluido"} and atendimento.prontuario:
        return redirect(
            url_for("atendimento.imprimir", atendimento_id=atendimento.id)
        )
    flash("Este atendimento não pode ser editado.", "error")
    return redirect(url_for("fila.listar"))


@fila_bp.route("/fila/<int:senha_id>/nao-compareceu", methods=["POST"])
@login_required
def nao_compareceu(senha_id):
    if not _require_reception_operation():
        return redirect(url_for("auth.dashboard"))

    senha = Senha.query.get_or_404(senha_id)
    if senha.status not in {"aguardando", "chamada"}:
        flash("Esta senha não pode ser marcada como não comparecimento.", "error")
        return redirect(url_for("fila.listar"))
    if not senha.medico_id or not senha.sala_id:
        flash("A senha não possui médico e sala associados; verifique o agendamento.", "error")
        return redirect(url_for("fila.listar"))

    senha.status = "nao_compareceu"
    db.session.add(
        HistoricoChamada(
            senha_id=senha.id,
            paciente_id=senha.paciente_id,
            medico_id=senha.medico_id,
            sala_id=senha.sala_id,
            status="nao_compareceu",
        )
    )
    registrar_evento_auditoria("senha", senha.id, "nao_compareceu")
    db.session.commit()
    flash(f"Senha {senha.codigo_exibicao} marcada como não comparecimento.", "info")
    return redirect(url_for("fila.listar"))


@fila_bp.route("/fila/<int:senha_id>/imprimir")
@login_required
def imprimir(senha_id):
    if current_user.perfil == "financeiro":
        if not has_profile_permission(
            current_user,
            "financeiro",
            "gerenciar_financeiro",
        ):
            flash("Você não tem permissão para imprimir senhas.", "error")
            return redirect(url_for("auth.dashboard"))
    elif not _require_reception_operation():
        return redirect(url_for("auth.dashboard"))

    senha = Senha.query.get_or_404(senha_id)
    if (
        current_user.perfil == "financeiro"
        and (
            not senha.vinculo_agendamento
            or not senha.vinculo_agendamento.agendamento.solicitacao.validacao_pagamento
        )
    ):
        flash("A senha não está vinculada a um pagamento validado.", "error")
        return redirect(url_for("financeiro.index"))
    registrar_evento_auditoria("senha", senha.id, "imprimir")
    db.session.commit()
    return render_template("fila/imprimir_senha.html", senha=senha)


@fila_bp.route("/prioridades/politica", methods=["GET", "POST"])
@login_required
def politica_prioridade():
    if not has_profile_permission(
        current_user,
        "administrador",
        "gerenciar_medicos",
    ):
        flash("Somente administradores podem configurar a política de prioridade.", "error")
        return redirect(url_for("auth.dashboard"))

    policy = _policy()
    if request.method == "POST":
        categories = request.form.getlist("categorias_habilitadas")
        approval_reference = request.form.get("referencia_aprovacao", "").strip()
        if set(categories) - set(PRIORITY_CATEGORIES):
            flash("A política contém categorias inválidas.", "error")
        else:
            approved = request.form.get("aprovada") == "on"
            if approved and not categories:
                flash("Selecione ao menos uma categoria antes de aprovar a política.", "error")
            elif approved and not approval_reference:
                flash(
                    "Informe a referência do registro formal de aprovação da direção.",
                    "error",
                )
            else:
                if policy is None:
                    policy = PoliticaPrioridade(id=1)
                    db.session.add(policy)
                policy.aprovada = approved
                policy.categorias_habilitadas = categories
                policy.referencia_aprovacao = approval_reference or policy.referencia_aprovacao
                policy.atualizada_em = datetime.now()
                if approved:
                    policy.aprovada_por_id = current_user.id
                    policy.aprovada_em = datetime.now()
                registrar_evento_auditoria(
                    "politica_prioridade",
                    1,
                    "aprovar" if approved else "desativar",
                )
                db.session.commit()
                flash(
                    "Política de prioridade atualizada. A alteração foi registrada na auditoria.",
                    "info",
                )
                return redirect(url_for("fila.politica_prioridade"))

    return render_template(
        "fila/politica_prioridade.html",
        politica=policy,
        categorias=PRIORITY_CATEGORIES,
    )
