from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import db
from database.models import Paciente
from services.auditoria import (
    registrar_consulta_auditoria,
    registrar_evento_auditoria,
)
from services.deletions import delete_unlinked_record
from services.permissions import has_profile_permission

pacientes_bp = Blueprint("pacientes", __name__, template_folder="../templates")


def _require_permission():
    if not has_profile_permission(
        current_user,
        "recepcionista",
        {"gerenciar_pacientes", "acessar_dashboard"},
    ):
        flash("Você não tem permissão para gerenciar pacientes.", "error")
        return False
    return True


def _cpf_limpo(cpf):
    return ''.join(ch for ch in cpf if ch.isdigit()) if cpf else ""


def _parse_date(value):
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@pacientes_bp.route("/pacientes")
@login_required
def listar():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    pacientes = Paciente.query.order_by(Paciente.nome_completo.asc()).all()
    registrar_consulta_auditoria("paciente", pacientes)
    return render_template("pacientes/lista.html", pacientes=pacientes)


@pacientes_bp.route("/pacientes/novo", methods=["GET", "POST"])
@login_required
def novo():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    if request.method == "POST":
        nome = request.form.get("nome_completo", "").strip()
        cpf = _cpf_limpo(request.form.get("cpf", ""))
        data_nascimento = _parse_date(request.form.get("data_nascimento", ""))
        telefone = request.form.get("telefone", "").strip()
        endereco = request.form.get("endereco", "").strip()
        observacoes = request.form.get("observacoes", "").strip()

        if not nome or not cpf or not data_nascimento or not telefone or not endereco:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template("pacientes/form.html", paciente=None)

        if len(cpf) != 11 or not cpf.isdigit():
            flash("CPF inválido. Informe 11 dígitos numéricos.", "error")
            return render_template("pacientes/form.html", paciente=None)

        if Paciente.query.filter_by(cpf=cpf).first():
            flash("Paciente já cadastrado com este CPF.", "error")
            return render_template("pacientes/form.html", paciente=None)

        paciente = Paciente(
            nome_completo=nome,
            cpf=cpf,
            data_nascimento=data_nascimento,
            telefone=telefone,
            endereco=endereco,
            observacoes=observacoes or None,
            ativo=True,
        )

        db.session.add(paciente)
        db.session.flush()
        registrar_evento_auditoria("paciente", paciente.id, "criar")
        db.session.commit()
        flash("Paciente cadastrado com sucesso.", "info")
        return redirect(url_for("pacientes.listar"))

    return render_template("pacientes/form.html", paciente=None)


@pacientes_bp.route("/pacientes/<int:paciente_id>/editar", methods=["GET", "POST"])
@login_required
def editar(paciente_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    paciente = Paciente.query.get_or_404(paciente_id)

    if request.method == "POST":
        nome = request.form.get("nome_completo", "").strip()
        cpf = _cpf_limpo(request.form.get("cpf", ""))
        data_nascimento = _parse_date(request.form.get("data_nascimento", ""))
        telefone = request.form.get("telefone", "").strip()
        endereco = request.form.get("endereco", "").strip()
        observacoes = request.form.get("observacoes", "").strip()

        if not nome or not cpf or not data_nascimento or not telefone or not endereco:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template("pacientes/form.html", paciente=paciente)

        if len(cpf) != 11 or not cpf.isdigit():
            flash("CPF inválido. Informe 11 dígitos numéricos.", "error")
            return render_template("pacientes/form.html", paciente=paciente)

        existing = Paciente.query.filter(Paciente.cpf == cpf, Paciente.id != paciente.id).first()
        if existing:
            flash("Já existe outro paciente com este CPF.", "error")
            return render_template("pacientes/form.html", paciente=paciente)

        paciente.nome_completo = nome
        paciente.cpf = cpf
        paciente.data_nascimento = data_nascimento
        paciente.telefone = telefone
        paciente.endereco = endereco
        paciente.observacoes = observacoes or None

        registrar_evento_auditoria("paciente", paciente.id, "alterar")
        db.session.commit()
        flash("Paciente atualizado com sucesso.", "info")
        return redirect(url_for("pacientes.listar"))

    registrar_evento_auditoria("paciente", paciente.id, "consultar")
    db.session.commit()
    return render_template("pacientes/form.html", paciente=paciente)


@pacientes_bp.route("/pacientes/<int:paciente_id>/toggle", methods=["POST"])
@login_required
def toggle(paciente_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    paciente = Paciente.query.get_or_404(paciente_id)
    paciente.ativo = not paciente.ativo
    registrar_evento_auditoria(
        "paciente",
        paciente.id,
        "ativar" if paciente.ativo else "desativar",
    )
    db.session.commit()
    status = "ativado" if paciente.ativo else "desativado"
    flash(f"Paciente {status} com sucesso.", "info")
    return redirect(url_for("pacientes.listar"))


@pacientes_bp.route("/pacientes/<int:paciente_id>/excluir", methods=["POST"])
@login_required
def excluir(paciente_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    paciente = Paciente.query.get_or_404(paciente_id)
    if not delete_unlinked_record(paciente, "paciente"):
        flash(
            "Não é possível excluir: há atendimentos ou registros vinculados. Desative o paciente para preservar o histórico.",
            "error",
        )
    else:
        flash("Paciente excluído com sucesso.", "info")
    return redirect(url_for("pacientes.listar"))
