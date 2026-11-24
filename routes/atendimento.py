from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import (
    Atendimento,
    HistoricoChamada,
    HistoricoStatus,
    Prontuario,
    Senha,
)
from services.auditoria import (
    registrar_consulta_auditoria,
    registrar_evento_auditoria,
)
from services.permissions import has_profile_permission
from services.senhas import concluir_fluxo_fila

atendimento_bp = Blueprint("atendimento", __name__, template_folder="../templates")

PRONTUARIO_FIELDS = (
    "queixa_principal",
    "sintomas",
    "diagnostico",
    "prescricao",
    "exames_solicitados",
    "condutas",
    "orientacoes",
)


def _medico_autorizado():
    medico = current_user.medico
    if (
        not has_profile_permission(
            current_user,
            "medico",
            "gerenciar_atendimento",
        )
        or not current_user.ativo
        or medico is None
        or not medico.ativo
    ):
        abort(403)
    return medico


def _historico_prontuarios(atendimento):
    return (
        Prontuario.query.join(Atendimento)
        .filter(
            Atendimento.paciente_id == atendimento.paciente_id,
            Atendimento.id != atendimento.id,
            Atendimento.status.in_({"finalizado", "concluido"}),
        )
        .order_by(Atendimento.data_fim.desc(), Prontuario.criado_em.desc())
        .all()
    )


def _render_prontuario(atendimento, prontuario, form_data):
    historico = _historico_prontuarios(atendimento)
    registrar_evento_auditoria(
        "atendimento",
        atendimento.id,
        "consultar_prontuario",
    )
    if prontuario:
        registrar_evento_auditoria("prontuario", prontuario.id, "consultar")
    for registro in historico:
        registrar_evento_auditoria("prontuario", registro.id, "consultar")
    db.session.commit()
    return render_template(
        "atendimento/prontuario.html",
        atendimento=atendimento,
        prontuario=prontuario,
        historico_prontuarios=historico,
        form_data=form_data,
        registro_retroativo=bool(
            atendimento.senha
            and atendimento.senha.status == "atendido"
            and prontuario is None
        ),
    )


@atendimento_bp.route(
    "/atendimento/<int:atendimento_id>",
    methods=["GET", "POST"],
)
@login_required
def prontuario(atendimento_id):
    medico = _medico_autorizado()
    atendimento = Atendimento.query.get_or_404(atendimento_id)
    if atendimento.medico_id != medico.id:
        abort(403)

    prontuario = atendimento.prontuario
    if atendimento.status not in {"em_andamento", "finalizado", "concluido"}:
        abort(404)
    senha_status = atendimento.senha.status if atendimento.senha else None
    registro_retroativo = senha_status == "atendido" and prontuario is None
    if (
        atendimento.status in {"finalizado", "concluido"}
        and not prontuario
        and not registro_retroativo
    ):
        abort(404)
    if request.method == "POST":
        if atendimento.status != "em_andamento" and not registro_retroativo:
            abort(409)
        if senha_status not in {None, "chamada", "em_atendimento", "atendido"}:
            flash(
                "A senha não está mais em atendimento; o prontuário não foi alterado.",
                "error",
            )
            return redirect(url_for("fila.listar"))

        form_data = {
            field: request.form.get(field, "").strip()
            for field in PRONTUARIO_FIELDS
        }
        if not form_data["queixa_principal"] or not form_data["diagnostico"]:
            flash("Queixa principal e diagnóstico são obrigatórios.", "error")
            return _render_prontuario(atendimento, prontuario, form_data)

        criando = prontuario is None
        if criando:
            prontuario = Prontuario(atendimento_id=atendimento.id)
        for field in PRONTUARIO_FIELDS:
            setattr(prontuario, field, form_data[field] or None)
        if criando:
            db.session.add(prontuario)
            db.session.flush()

        if atendimento.status == "em_andamento":
            status_anterior = atendimento.status
            atendimento.status = "finalizado"
            atendimento.data_fim = datetime.utcnow()
            db.session.add(
                HistoricoStatus(
                    entidade="atendimento",
                    entidade_id=atendimento.id,
                    status_anterior=status_anterior,
                    status_novo=atendimento.status,
                    alterado_por_id=current_user.id,
                )
            )
        registrar_evento_auditoria(
            "prontuario",
            prontuario.id,
            (
                "criar_prontuario_retrospectivo"
                if registro_retroativo and criando
                else "criar_prontuario"
                if criando
                else "alterar_prontuario"
            ),
        )
        registrar_evento_auditoria(
            "atendimento",
            atendimento.id,
            (
                "registrar_prontuario_atendimento_concluido"
                if registro_retroativo
                else "finalizar_atendimento"
            ),
        )
        if atendimento.senha and senha_status != "atendido":
            concluir_fluxo_fila(atendimento.senha, current_user.id)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            current_app.logger.exception(
                "Unable to finalize medical record for attendance %s.",
                atendimento_id,
            )
            flash(
                "Não foi possível salvar o prontuário. Atualize a tela e tente novamente.",
                "error",
            )
            return redirect(url_for("fila.listar"))

        flash(
            "Prontuário registrado para o atendimento já concluído."
            if registro_retroativo
            else "Prontuário salvo e atendimento finalizado.",
            "info",
        )
        return redirect(
            url_for("atendimento.prontuario", atendimento_id=atendimento.id)
        )

    form_data = {
        field: getattr(prontuario, field, None) or ""
        for field in PRONTUARIO_FIELDS
    }
    return _render_prontuario(atendimento, prontuario, form_data)


@atendimento_bp.route("/atendimento/senha/<int:senha_id>/prontuario")
@login_required
def iniciar_para_senha(senha_id):
    medico = _medico_autorizado()
    senha = Senha.query.get_or_404(senha_id)
    if senha.medico_id != medico.id:
        abort(403)
    if senha.status != "atendido":
        flash(
            "O prontuário é iniciado durante o atendimento, antes de concluí-lo.",
            "error",
        )
        return redirect(url_for("fila.listar"))
    if not senha.sala_id:
        flash(
            "Esta senha não possui sala registrada; não foi possível iniciar o prontuário.",
            "error",
        )
        return redirect(url_for("atendimento.listar"))

    atendimento = Atendimento.query.filter_by(senha_id=senha.id).one_or_none()
    if atendimento:
        if atendimento.medico_id != medico.id:
            abort(403)
        if atendimento.prontuario or atendimento.status == "em_andamento":
            return redirect(
                url_for("atendimento.prontuario", atendimento_id=atendimento.id)
            )
        if atendimento.status in {"finalizado", "concluido"}:
            return redirect(
                url_for("atendimento.prontuario", atendimento_id=atendimento.id)
            )
        abort(409)

    chamada = (
        HistoricoChamada.query.filter_by(senha_id=senha.id, status="chamada")
        .order_by(HistoricoChamada.data_hora.desc(), HistoricoChamada.id.desc())
        .first()
    )
    atendimento = Atendimento(
        paciente_id=senha.paciente_id,
        medico_id=medico.id,
        sala_id=senha.sala_id,
        senha_id=senha.id,
        status="em_andamento",
        data_inicio=chamada.data_hora if chamada else senha.data_hora,
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
        "iniciar_prontuario_atendimento_concluido",
    )
    registrar_evento_auditoria(
        "senha",
        senha.id,
        "iniciar_prontuario_atendimento_concluido",
    )
    db.session.commit()
    return redirect(
        url_for("atendimento.prontuario", atendimento_id=atendimento.id)
    )


@atendimento_bp.route("/prontuarios")
@login_required
def listar():
    medico = _medico_autorizado()
    atendimentos = (
        Atendimento.query.filter_by(medico_id=medico.id)
        .order_by(Atendimento.data_inicio.desc())
        .all()
    )
    senhas_sem_atendimento = (
        Senha.query.outerjoin(Atendimento, Atendimento.senha_id == Senha.id)
        .filter(
            Senha.medico_id == medico.id,
            Senha.status == "atendido",
            Atendimento.id.is_(None),
        )
        .order_by(Senha.data_hora.desc(), Senha.id.desc())
        .all()
    )
    registrar_consulta_auditoria("atendimento", atendimentos)
    registrar_consulta_auditoria("senha", senhas_sem_atendimento)
    return render_template(
        "atendimento/lista.html",
        atendimentos=atendimentos,
        senhas_sem_atendimento=senhas_sem_atendimento,
    )


@atendimento_bp.route("/atendimento/<int:atendimento_id>/imprimir")
@login_required
def imprimir(atendimento_id):
    medico = _medico_autorizado()
    atendimento = Atendimento.query.get_or_404(atendimento_id)
    prontuario = atendimento.prontuario
    if not prontuario:
        abort(404)

    if atendimento.medico_id != medico.id:
        contexto_id = request.args.get("contexto", type=int)
        contexto = (
            db.session.get(Atendimento, contexto_id)
            if contexto_id
            else None
        )
        if (
            not contexto
            or contexto.paciente_id != atendimento.paciente_id
            or contexto.medico_id != medico.id
            or contexto.status not in {"em_andamento", "finalizado", "concluido"}
        ):
            abort(403)

    registrar_evento_auditoria("prontuario", prontuario.id, "imprimir_prontuario")
    db.session.commit()
    return render_template(
        "atendimento/imprimir.html",
        atendimento=atendimento,
        prontuario=prontuario,
        data_emissao=datetime.now(),
    )
