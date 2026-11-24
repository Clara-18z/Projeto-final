from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from database import db
from database.models import (
    Agendamento,
    Especialidade,
    Medico,
    Permissao,
    Sala,
    Usuario,
)
from services.auditoria import registrar_evento_auditoria
from services.disponibilidade import medico_presente
from services.deletions import delete_unlinked_record
from services.permissions import has_profile_permission, permissions_for_profile

clinica_bp = Blueprint("clinica", __name__, template_folder="../templates")

STATUS_SALA = {"disponivel", "ocupada", "indisponivel"}


def _medicos_disponiveis_para_sala(sala=None):
    query = (
        Medico.query.join(Usuario)
        .filter(
            Medico.ativo.is_(True),
            Usuario.ativo.is_(True),
            Usuario.perfil == "medico",
        )
    )
    if sala:
        query = query.filter(
            db.or_(Medico.sala_id.is_(None), Medico.sala_id == sala.id)
        )
    else:
        query = query.filter(Medico.sala_id.is_(None))
    medicos = query.order_by(Medico.nome_exibicao.asc()).all()
    if sala:
        medico_atual = Medico.query.filter_by(sala_id=sala.id).first()
        if medico_atual and medico_atual not in medicos:
            medicos.append(medico_atual)
            medicos.sort(key=lambda medico: medico.nome_exibicao.casefold())
    return medicos


def _require_permission():
    if not has_profile_permission(
        current_user,
        "administrador",
        "gerenciar_medicos",
    ):
        flash("Você não tem permissão para gerenciar clínica.", "error")
        return False
    return True


@clinica_bp.route("/especialidades")
@login_required
def especialidades():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    especialidades = Especialidade.query.order_by(Especialidade.nome.asc()).all()
    return render_template("clinica/especialidades.html", especialidades=especialidades)


@clinica_bp.route("/especialidades/nova", methods=["GET", "POST"])
@login_required
def especialidade_nova():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        descricao = request.form.get("descricao", "").strip()
        ativa = request.form.get("ativa") == "on"

        if not nome:
            flash("Informe o nome da especialidade.", "error")
            return render_template("clinica/especialidades_form.html", especialidade=None)

        if Especialidade.query.filter_by(nome=nome).first():
            flash("Especialidade já cadastrada.", "error")
            return render_template("clinica/especialidades_form.html", especialidade=None)

        especialidade = Especialidade(nome=nome, descricao=descricao or None, ativa=ativa)
        db.session.add(especialidade)
        db.session.flush()
        registrar_evento_auditoria("especialidade", especialidade.id, "criar")
        db.session.commit()
        flash("Especialidade cadastrada com sucesso.", "info")
        return redirect(url_for("clinica.especialidades"))

    return render_template("clinica/especialidades_form.html", especialidade=None)


@clinica_bp.route("/especialidades/<int:especialidade_id>/editar", methods=["GET", "POST"])
@login_required
def especialidade_editar(especialidade_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    especialidade = Especialidade.query.get_or_404(especialidade_id)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        descricao = request.form.get("descricao", "").strip()
        ativa = request.form.get("ativa") == "on"

        if not nome:
            flash("Informe o nome da especialidade.", "error")
            return render_template("clinica/especialidades_form.html", especialidade=especialidade)

        existing = Especialidade.query.filter(Especialidade.nome == nome, Especialidade.id != especialidade.id).first()
        if existing:
            flash("Já existe outra especialidade com este nome.", "error")
            return render_template("clinica/especialidades_form.html", especialidade=especialidade)

        especialidade.nome = nome
        especialidade.descricao = descricao or None
        especialidade.ativa = ativa
        registrar_evento_auditoria("especialidade", especialidade.id, "alterar")
        db.session.commit()
        flash("Especialidade atualizada com sucesso.", "info")
        return redirect(url_for("clinica.especialidades"))

    return render_template("clinica/especialidades_form.html", especialidade=especialidade)


@clinica_bp.route("/especialidades/<int:especialidade_id>/toggle", methods=["POST"])
@login_required
def especialidade_toggle(especialidade_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    especialidade = Especialidade.query.get_or_404(especialidade_id)
    especialidade.ativa = not especialidade.ativa
    registrar_evento_auditoria(
        "especialidade",
        especialidade.id,
        "ativar" if especialidade.ativa else "inativar",
    )
    db.session.commit()
    status = "ativada" if especialidade.ativa else "inativada"
    flash(f"Especialidade {status} com sucesso.", "info")
    return redirect(url_for("clinica.especialidades"))


@clinica_bp.route("/especialidades/<int:especialidade_id>/excluir", methods=["POST"])
@login_required
def especialidade_excluir(especialidade_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    especialidade = Especialidade.query.get_or_404(especialidade_id)
    if not delete_unlinked_record(especialidade, "especialidade"):
        flash(
            "Não é possível excluir: há registros vinculados. Inative a especialidade para preservar o histórico.",
            "error",
        )
    else:
        flash("Especialidade excluída com sucesso.", "info")
    return redirect(url_for("clinica.especialidades"))


@clinica_bp.route("/medicos")
@login_required
def medicos():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    medicos = Medico.query.order_by(Medico.nome_exibicao.asc()).all()
    status_presencas = {}
    for medico in medicos:
        if not medico.ativo or not medico.usuario.ativo:
            status_presencas[medico.id] = "Inativo"
        elif medico_presente(medico.id):
            status_presencas[medico.id] = "Presença confirmada"
        else:
            status_presencas[medico.id] = "Presença não confirmada"
    return render_template(
        "clinica/medicos.html",
        medicos=medicos,
        status_presencas=status_presencas,
    )


@clinica_bp.route("/medicos/novo", methods=["GET", "POST"])
@login_required
def medico_novo():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    usuarios_query = (
        Usuario.query.filter_by(ativo=True, perfil="medico")
        .order_by(Usuario.nome_completo.asc())
        .all()
    )
    usuarios = [usuario for usuario in usuarios_query if usuario.medico is None]
    especialidades = Especialidade.query.filter_by(ativa=True).order_by(Especialidade.nome.asc()).all()
    if request.method == "POST":
        usuario_id = request.form.get("usuario_id", type=int)
        especialidade_id = request.form.get("especialidade_id", type=int)
        crm = request.form.get("crm", "").strip()
        nome_exibicao = request.form.get("nome_exibicao", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")
        ativo = request.form.get("ativo") == "on"

        if not especialidade_id or not crm or not nome_exibicao:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=None,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        especialidade = db.session.get(Especialidade, especialidade_id)
        if not especialidade or not especialidade.ativa:
            flash("Selecione uma especialidade ativa.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=None,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        if Medico.query.filter_by(crm=crm).first():
            flash("CRM já cadastrado.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=None,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        if usuario_id:
            usuario = db.session.get(Usuario, usuario_id)
            if (
                not usuario
                or usuario.perfil != "medico"
                or not usuario.ativo
                or usuario.medico is not None
            ):
                flash("Selecione uma conta médica ativa e ainda não vinculada.", "error")
                return render_template(
                    "clinica/medicos_form.html",
                    medico=None,
                    usuarios=usuarios,
                    especialidades=especialidades,
                )
        else:
            if not email or not username or not senha:
                flash(
                    "Para criar a conta do novo médico, informe e-mail, nome de usuário e senha inicial.",
                    "error",
                )
                return render_template(
                    "clinica/medicos_form.html",
                    medico=None,
                    usuarios=usuarios,
                    especialidades=especialidades,
                )
            if Usuario.query.filter(
                (Usuario.email == email) | (Usuario.username == username)
            ).first():
                flash("E-mail ou nome de usuário já cadastrado.", "error")
                return render_template(
                    "clinica/medicos_form.html",
                    medico=None,
                    usuarios=usuarios,
                    especialidades=especialidades,
                )

            usuario = Usuario(
                nome_completo=nome_exibicao,
                email=email,
                username=username,
                senha_hash=generate_password_hash(senha),
                perfil="medico",
                ativo=True,
            )
            usuario.permissoes = Permissao.query.filter(
                Permissao.codigo.in_(permissions_for_profile("medico"))
            ).all()
            db.session.add(usuario)
            db.session.flush()
            registrar_evento_auditoria("usuario", usuario.id, "criar")

        medico = Medico(
            usuario_id=usuario.id,
            especialidade_id=especialidade_id,
            crm=crm,
            nome_exibicao=nome_exibicao,
            status="indisponivel",
            ativo=ativo,
        )
        db.session.add(medico)
        db.session.flush()
        registrar_evento_auditoria("medico", medico.id, "criar")
        db.session.commit()
        flash("Médico cadastrado com sucesso.", "info")
        return redirect(url_for("clinica.medicos"))

    return render_template(
        "clinica/medicos_form.html",
        medico=None,
        usuarios=usuarios,
        especialidades=especialidades,
    )


@clinica_bp.route("/medicos/<int:medico_id>/editar", methods=["GET", "POST"])
@login_required
def medico_editar(medico_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    medico = Medico.query.get_or_404(medico_id)
    usuarios = (
        Usuario.query.filter_by(ativo=True, perfil="medico")
        .order_by(Usuario.nome_completo.asc())
        .all()
    )
    especialidades = Especialidade.query.filter_by(ativa=True).order_by(Especialidade.nome.asc()).all()
    if request.method == "POST":
        usuario_id = request.form.get("usuario_id", type=int)
        especialidade_id = request.form.get("especialidade_id", type=int)
        crm = request.form.get("crm", "").strip()
        nome_exibicao = request.form.get("nome_exibicao", "").strip()
        ativo = request.form.get("ativo") == "on"

        if not usuario_id or not especialidade_id or not crm or not nome_exibicao:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=medico,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        usuario = db.session.get(Usuario, usuario_id)
        especialidade = db.session.get(Especialidade, especialidade_id)
        if not usuario or usuario.perfil != "medico" or not usuario.ativo:
            flash("Selecione uma conta ativa com perfil médico.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=medico,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        if not especialidade or not especialidade.ativa:
            flash("Selecione uma especialidade ativa.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=medico,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        existing_by_user = Medico.query.filter(Medico.usuario_id == usuario_id, Medico.id != medico.id).first()
        if existing_by_user:
            flash("Este usuário já está vinculado a outro médico.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=medico,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        existing_by_crm = Medico.query.filter(Medico.crm == crm, Medico.id != medico.id).first()
        if existing_by_crm:
            flash("CRM já cadastrado por outro profissional.", "error")
            return render_template(
                "clinica/medicos_form.html",
                medico=medico,
                usuarios=usuarios,
                especialidades=especialidades,
            )

        medico.usuario_id = usuario_id
        medico.especialidade_id = especialidade_id
        medico.crm = crm
        medico.nome_exibicao = nome_exibicao
        medico.ativo = ativo
        registrar_evento_auditoria("medico", medico.id, "alterar")
        db.session.commit()
        flash("Médico atualizado com sucesso.", "info")
        return redirect(url_for("clinica.medicos"))

    return render_template(
        "clinica/medicos_form.html",
        medico=medico,
        usuarios=usuarios,
        especialidades=especialidades,
    )


@clinica_bp.route("/medicos/<int:medico_id>/toggle", methods=["POST"])
@login_required
def medico_toggle(medico_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    medico = Medico.query.get_or_404(medico_id)
    medico.ativo = not medico.ativo
    registrar_evento_auditoria(
        "medico",
        medico.id,
        "ativar" if medico.ativo else "inativar",
    )
    db.session.commit()
    status = "ativado" if medico.ativo else "inativado"
    flash(f"Médico {status} com sucesso.", "info")
    return redirect(url_for("clinica.medicos"))


@clinica_bp.route("/medicos/<int:medico_id>/excluir", methods=["POST"])
@login_required
def medico_excluir(medico_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    medico = Medico.query.get_or_404(medico_id)
    if not delete_unlinked_record(medico, "medico"):
        flash(
            "Não é possível excluir: há registros vinculados. Inative o médico para preservar o histórico.",
            "error",
        )
    else:
        flash(
            "Cadastro médico excluído. A conta de usuário vinculada permanece na lista de usuários.",
            "info",
        )
    return redirect(url_for("clinica.medicos"))


@clinica_bp.route("/salas")
@login_required
def salas():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    salas = Sala.query.order_by(Sala.nome.asc()).all()
    return render_template("clinica/salas.html", salas=salas)


@clinica_bp.route("/salas/nova", methods=["GET", "POST"])
@login_required
def sala_nova():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    medicos = _medicos_disponiveis_para_sala()
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        setor = request.form.get("setor", "consulta").strip()
        status = request.form.get("status", "disponivel")
        ativa = request.form.get("ativa") == "on"
        medico_id = request.form.get("medico_id", type=int)

        if status not in STATUS_SALA or not nome or not medico_id:
            flash("Informe nome, médico responsável e um status válido para a sala.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=None,
                medicos=medicos,
            )

        if Sala.query.filter_by(nome=nome).first():
            flash("Sala já cadastrada.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=None,
                medicos=medicos,
            )

        medico = db.session.get(Medico, medico_id)
        if (
            not medico
            or not medico.ativo
            or not medico.usuario.ativo
            or medico.usuario.perfil != "medico"
            or medico.sala_id is not None
        ):
            flash("Selecione um médico ativo que ainda não seja responsável por outra sala.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=None,
                medicos=medicos,
            )

        sala = Sala(nome=nome, setor=setor or "consulta", status=status, ativa=ativa)
        db.session.add(sala)
        db.session.flush()
        medico.sala_id = sala.id
        registrar_evento_auditoria("sala", sala.id, "criar")
        registrar_evento_auditoria("medico", medico.id, "atribuir_sala")
        db.session.commit()
        flash("Sala cadastrada com sucesso.", "info")
        return redirect(url_for("clinica.salas"))

    return render_template(
        "clinica/salas_form.html",
        sala=None,
        medicos=medicos,
    )


@clinica_bp.route("/salas/<int:sala_id>/editar", methods=["GET", "POST"])
@login_required
def sala_editar(sala_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    sala = Sala.query.get_or_404(sala_id)
    medico_atual = Medico.query.filter_by(sala_id=sala.id).first()
    medicos = _medicos_disponiveis_para_sala(sala)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        setor = request.form.get("setor", "consulta").strip()
        status = request.form.get("status", sala.status)
        ativa = request.form.get("ativa") == "on"
        medico_id = request.form.get("medico_id", type=int)

        if status not in STATUS_SALA or not nome or not medico_id:
            flash("Informe nome, médico responsável e um status válido para a sala.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=sala,
                medicos=medicos,
            )

        existing = Sala.query.filter(Sala.nome == nome, Sala.id != sala.id).first()
        if existing:
            flash("Já existe outra sala com este nome.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=sala,
                medicos=medicos,
            )

        medico = db.session.get(Medico, medico_id)
        is_current_responsible = medico_atual and medico and medico.id == medico_atual.id
        if not medico or (
            not is_current_responsible
            and (
                not medico.ativo
                or not medico.usuario.ativo
                or medico.usuario.perfil != "medico"
                or medico.sala_id is not None
            )
        ):
            flash("Selecione um médico ativo sem outra sala atribuída.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=sala,
                medicos=medicos,
            )

        if (
            medico_atual
            and medico_atual.id != medico.id
            and Agendamento.query.filter(
                Agendamento.status.in_({"agendado", "em_atendimento"}),
                db.or_(
                    Agendamento.sala_id == sala.id,
                    Agendamento.medico_id.in_({medico_atual.id, medico.id}),
                ),
            ).first()
        ):
            flash(
                "Não é possível trocar o médico responsável enquanto houver agendamentos ativos para a sala ou para os médicos.",
                "error",
            )
            return render_template(
                "clinica/salas_form.html",
                sala=sala,
                medicos=medicos,
            )

        if (
            sala.ativa
            and not ativa
            and Agendamento.query.filter(
                Agendamento.sala_id == sala.id,
                Agendamento.status.in_({"agendado", "em_atendimento"}),
            ).first()
        ):
            flash("Não é possível inativar uma sala com agendamentos ativos.", "error")
            return render_template(
                "clinica/salas_form.html",
                sala=sala,
                medicos=medicos,
            )

        sala.nome = nome
        sala.setor = setor or "consulta"
        sala.status = status
        sala.ativa = ativa
        if medico_atual and medico_atual.id != medico.id:
            medico_atual.sala_id = None
            registrar_evento_auditoria(
                "medico",
                medico_atual.id,
                "remover_responsabilidade_sala",
            )
        if medico_atual is None or medico_atual.id != medico.id:
            medico.sala_id = sala.id
            registrar_evento_auditoria("medico", medico.id, "atribuir_sala")
        registrar_evento_auditoria("sala", sala.id, "alterar")
        db.session.commit()
        flash("Sala atualizada com sucesso.", "info")
        return redirect(url_for("clinica.salas"))

    return render_template(
        "clinica/salas_form.html",
        sala=sala,
        medicos=medicos,
    )


@clinica_bp.route("/salas/<int:sala_id>/toggle", methods=["POST"])
@login_required
def sala_toggle(sala_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    sala = Sala.query.get_or_404(sala_id)
    if sala.ativa and Agendamento.query.filter(
        Agendamento.sala_id == sala.id,
        Agendamento.status.in_({"agendado", "em_atendimento"}),
    ).first():
        flash("Não é possível inativar uma sala com agendamentos ativos.", "error")
        return redirect(url_for("clinica.salas"))
    sala.ativa = not sala.ativa
    registrar_evento_auditoria(
        "sala",
        sala.id,
        "ativar" if sala.ativa else "inativar",
    )
    db.session.commit()
    status = "ativada" if sala.ativa else "inativada"
    flash(f"Sala {status} com sucesso.", "info")
    return redirect(url_for("clinica.salas"))


@clinica_bp.route("/salas/<int:sala_id>/excluir", methods=["POST"])
@login_required
def sala_excluir(sala_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    sala = Sala.query.get_or_404(sala_id)
    if not delete_unlinked_record(sala, "sala"):
        flash(
            "Não é possível excluir: há médicos ou registros vinculados. Inative a sala para preservar o histórico.",
            "error",
        )
    else:
        flash("Sala excluída com sucesso.", "info")
    return redirect(url_for("clinica.salas"))
