from datetime import datetime, time, timedelta

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from database import db
from database.models import (
    Agendamento,
    Medico,
    Solicitacao,
    Usuario,
)
from services.auditoria import registrar_consulta_auditoria, registrar_evento_auditoria
from services.disponibilidade import (
    erro_disponibilidade_agendamento,
    medicos_disponiveis_para_solicitacao,
)
from services.permissions import has_profile_permission

agenda_bp = Blueprint("agenda", __name__, template_folder="../templates")


def _require_doctor_access():
    if not (
        current_user.perfil == "medico"
        and current_user.medico is not None
        and current_user.medico.ativo
        and has_profile_permission(
            current_user,
            "medico",
            {"gerenciar_agenda", "acessar_dashboard"},
        )
    ):
        flash("Somente médicos vinculados podem consultar a própria presença.", "error")
        return False
    return True


def _require_agenda_access():
    if current_user.perfil == "medico":
        allowed = (
            current_user.medico is not None
            and has_profile_permission(
                current_user,
                "medico",
                {"gerenciar_agenda", "acessar_dashboard"},
            )
        )
    else:
        allowed = has_profile_permission(
            current_user,
            "recepcionista",
            {"gerenciar_agenda", "acessar_dashboard"},
        )
    if not allowed:
        flash("Você não tem permissão para gerenciar a agenda.", "error")
        return False
    return True


def _require_agenda_management():
    if not has_profile_permission(
        current_user,
        "recepcionista",
        {"gerenciar_agenda", "acessar_dashboard"},
    ):
        flash("Você não tem permissão para alterar agendamentos.", "error")
        return False
    return True


@agenda_bp.route("/agenda")
@login_required
def listar():
    if not _require_agenda_access():
        return redirect(url_for("auth.dashboard"))

    data = request.args.get("data", "").strip()
    try:
        dia = datetime.strptime(data, "%Y-%m-%d").date() if data else datetime.now().date()
    except ValueError:
        flash("Data inválida. Selecione uma data válida.", "error")
        return redirect(url_for("agenda.listar"))

    inicio = datetime.combine(dia, time.min)
    fim = inicio + timedelta(days=1)
    query = Agendamento.query.filter(
            Agendamento.data_hora >= inicio,
            Agendamento.data_hora < fim,
            Agendamento.status != "cancelado",
        )
    if current_user.perfil == "medico":
        query = query.filter(Agendamento.medico_id == current_user.medico.id)
    agendamentos = query.order_by(Agendamento.data_hora.asc()).all()
    registrar_consulta_auditoria("agendamento", agendamentos)
    return render_template(
        "agenda/lista.html",
        agendamentos=agendamentos,
        data_selecionada=dia.isoformat(),
    )


@agenda_bp.route("/agenda/disponibilidades", methods=["GET", "POST"])
@login_required
def disponibilidades():
    flash(
        "A configuração de horários semanais foi removida. A presença médica é controlada pelo login.",
        "info",
    )
    return redirect(url_for("auth.dashboard"))


@agenda_bp.route("/agenda/minha-disponibilidade")
@login_required
def presenca_medica():
    if not _require_doctor_access():
        return redirect(url_for("auth.dashboard"))

    medico = current_user.medico
    return render_template(
        "agenda/presenca_medica.html",
        presenca_ativa=medico.presenca_ativa,
        sala=medico.sala,
    )


@agenda_bp.route("/agenda/agendar", methods=["GET", "POST"])
@login_required
def agendar():
    if not _require_agenda_management():
        return redirect(url_for("auth.dashboard"))

    solicitacoes = (
        Solicitacao.query.filter(
            Solicitacao.status == "confirmado",
            Solicitacao.validacao_pagamento.has(),
            ~Solicitacao.agendamento.has(Agendamento.status != "cancelado"),
        )
        .order_by(Solicitacao.data_solicitacao.asc())
        .all()
    )
    if request.method == "GET":
        registrar_consulta_auditoria("solicitacao", solicitacoes)

    if request.method == "POST":
        solicitacao_id = request.form.get("solicitacao_id", type=int)
        medico_id = request.form.get("medico_id", type=int)
        data_hora_texto = request.form.get("data_hora", "").strip()

        try:
            data_hora = datetime.strptime(data_hora_texto, "%Y-%m-%dT%H:%M")
        except ValueError:
            data_hora = None

        solicitacao = db.session.get(Solicitacao, solicitacao_id) if solicitacao_id else None
        medico = db.session.get(Medico, medico_id) if medico_id else None

        erro = None
        if (
            not solicitacao
            or solicitacao.status != "confirmado"
            or not solicitacao.validacao_pagamento
        ):
            erro = "Selecione uma solicitação com validação financeira registrada."
        elif solicitacao.agendamento and solicitacao.agendamento.status != "cancelado":
            erro = "Esta solicitação já possui um agendamento ativo."
        elif not data_hora or data_hora <= datetime.now():
            erro = "Informe uma data e horário futuros válidos."
        elif data_hora.minute not in (0, 30):
            erro = "Os horários devem iniciar na hora cheia ou na meia hora."
        elif (
            not medico
            or not medico.ativo
            or not medico.usuario.ativo
            or medico.usuario.perfil != "medico"
            or medico.especialidade_id != solicitacao.especialidade_id
        ):
            erro = "Selecione um médico ativo da especialidade do serviço."
        else:
            erro = erro_disponibilidade_agendamento(medico, data_hora)

        if erro:
            flash(erro, "error")
            return render_template(
                "agenda/agendar.html",
                solicitacoes=solicitacoes,
                form_data=request.form,
            )

        agendamento = Agendamento(
            solicitacao_id=solicitacao.id,
            paciente_id=solicitacao.paciente_id,
            medico_id=medico.id,
            sala_id=medico.sala_id,
            data_hora=data_hora,
            status="agendado",
        )
        db.session.add(agendamento)
        db.session.flush()
        registrar_evento_auditoria("agendamento", agendamento.id, "criar")
        solicitacao.medico_id = medico.id
        solicitacao.status = "agendado"
        db.session.commit()
        flash("Agendamento criado com sucesso.", "info")
        return redirect(url_for("agenda.listar", data=data_hora.date().isoformat()))

    return render_template(
        "agenda/agendar.html",
        solicitacoes=solicitacoes,
        form_data={},
    )


@agenda_bp.route("/agenda/medicos-disponiveis")
@login_required
def medicos_disponiveis():
    if not has_profile_permission(
        current_user,
        "recepcionista",
        {"gerenciar_agenda", "acessar_dashboard"},
    ):
        return jsonify(error="Acesso não autorizado."), 403

    solicitacao_id = request.args.get("solicitacao_id", type=int)
    data_hora_texto = request.args.get("data_hora", "").strip()
    solicitacao = (
        db.session.get(Solicitacao, solicitacao_id) if solicitacao_id else None
    )
    try:
        data_hora = datetime.strptime(data_hora_texto, "%Y-%m-%dT%H:%M")
    except ValueError:
        data_hora = None

    if (
        not solicitacao
        or solicitacao.status != "confirmado"
        or not solicitacao.validacao_pagamento
        or (solicitacao.agendamento and solicitacao.agendamento.status != "cancelado")
        or not data_hora
        or data_hora <= datetime.now()
        or data_hora.minute not in (0, 30)
    ):
        return jsonify(medicos=[])

    medicos = medicos_disponiveis_para_solicitacao(solicitacao, data_hora)
    return jsonify(
        medicos=[
            {
                "id": medico.id,
                "nome": medico.nome_exibicao,
                "sala": medico.sala.nome,
            }
            for medico in medicos
        ]
    )


@agenda_bp.route("/agenda/<int:agendamento_id>/cancelar", methods=["POST"])
@login_required
def cancelar(agendamento_id):
    if not _require_agenda_management():
        return redirect(url_for("auth.dashboard"))

    agendamento = Agendamento.query.get_or_404(agendamento_id)
    if agendamento.status != "agendado" or agendamento.senha_vinculo:
        flash(
            "Só é possível cancelar agendamentos ativos que ainda não tenham senha emitida.",
            "error",
        )
        return redirect(url_for("agenda.listar", data=agendamento.data_hora.date().isoformat()))

    agendamento.status = "cancelado"
    agendamento.solicitacao.status = "confirmado"
    registrar_evento_auditoria("agendamento", agendamento.id, "cancelar")
    db.session.commit()
    flash("Agendamento cancelado. A solicitação voltou a ficar disponível para agendamento.", "info")
    return redirect(url_for("agenda.listar", data=agendamento.data_hora.date().isoformat()))


