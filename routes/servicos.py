from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import db
from database.models import Especialidade, Servico
from services.auditoria import registrar_evento_auditoria
from services.deletions import delete_unlinked_record
from services.permissions import has_profile_permission

servicos_bp = Blueprint("servicos", __name__, template_folder="../templates")


def _require_admin():
    if not has_profile_permission(
        current_user,
        "administrador",
        "gerenciar_servicos",
    ):
        flash("Somente administradores podem alterar serviços e preços.", "error")
        return False
    return True


@servicos_bp.route("/servicos")
@login_required
def listar():
    if not _require_admin():
        return redirect(url_for("auth.dashboard"))

    servicos = Servico.query.order_by(Servico.nome.asc()).all()
    return render_template("servicos/lista.html", servicos=servicos)


@servicos_bp.route("/servicos/novo", methods=["GET", "POST"])
@login_required
def novo():
    if not _require_admin():
        return redirect(url_for("auth.dashboard"))

    especialidades = Especialidade.query.filter_by(ativa=True).order_by(Especialidade.nome.asc()).all()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", "Consulta").strip()
        descricao = request.form.get("descricao", "").strip()
        valor = request.form.get("valor", "0")
        ativo = request.form.get("ativo") == "on"
        especialidade_id = request.form.get("especialidade_id", type=int)

        if not nome or not especialidade_id:
            flash("Informe nome do serviço e especialidade.", "error")
            return render_template("servicos/form.html", servico=None, especialidades=especialidades)

        try:
            valor_float = float(valor.replace(".", "").replace(",", "."))
        except (AttributeError, ValueError):
            flash("Valor inválido. Informe um valor numérico válido.", "error")
            return render_template("servicos/form.html", servico=None, especialidades=especialidades)

        if valor_float < 0:
            flash("O valor do serviço não pode ser negativo.", "error")
            return render_template("servicos/form.html", servico=None, especialidades=especialidades)

        if Servico.query.filter_by(nome=nome).first():
            flash("Já existe um serviço com este nome.", "error")
            return render_template("servicos/form.html", servico=None, especialidades=especialidades)

        servico = Servico(
            nome=nome,
            categoria=categoria,
            descricao=descricao or None,
            valor=valor_float,
            ativo=ativo,
            especialidade_id=especialidade_id,
        )
        db.session.add(servico)
        db.session.flush()
        registrar_evento_auditoria("servico", servico.id, "criar")
        db.session.commit()
        flash("Serviço cadastrado com sucesso.", "info")
        return redirect(url_for("servicos.listar"))

    return render_template("servicos/form.html", servico=None, especialidades=especialidades)


@servicos_bp.route("/servicos/<int:servico_id>/editar", methods=["GET", "POST"])
@login_required
def editar(servico_id):
    if not _require_admin():
        return redirect(url_for("auth.dashboard"))

    servico = Servico.query.get_or_404(servico_id)
    especialidades = Especialidade.query.filter_by(ativa=True).order_by(Especialidade.nome.asc()).all()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", servico.categoria).strip()
        descricao = request.form.get("descricao", "").strip()
        valor = request.form.get("valor", "0")
        ativo = request.form.get("ativo") == "on"
        especialidade_id = request.form.get("especialidade_id", type=int)

        if not nome or not especialidade_id:
            flash("Informe nome do serviço e especialidade.", "error")
            return render_template("servicos/form.html", servico=servico, especialidades=especialidades)

        try:
            valor_float = float(valor.replace(".", "").replace(",", "."))
        except (AttributeError, ValueError):
            flash("Valor inválido. Informe um valor numérico válido.", "error")
            return render_template("servicos/form.html", servico=servico, especialidades=especialidades)

        if valor_float < 0:
            flash("O valor do serviço não pode ser negativo.", "error")
            return render_template("servicos/form.html", servico=servico, especialidades=especialidades)

        existing = Servico.query.filter(Servico.nome == nome, Servico.id != servico.id).first()
        if existing:
            flash("Já existe outro serviço com este nome.", "error")
            return render_template("servicos/form.html", servico=servico, especialidades=especialidades)

        servico.nome = nome
        servico.categoria = categoria
        servico.descricao = descricao or None
        servico.valor = valor_float
        servico.ativo = ativo
        servico.especialidade_id = especialidade_id

        registrar_evento_auditoria("servico", servico.id, "alterar")
        db.session.commit()
        flash("Serviço atualizado com sucesso.", "info")
        return redirect(url_for("servicos.listar"))

    return render_template("servicos/form.html", servico=servico, especialidades=especialidades)


@servicos_bp.route("/servicos/<int:servico_id>/toggle", methods=["POST"])
@login_required
def toggle(servico_id):
    if not _require_admin():
        return redirect(url_for("auth.dashboard"))

    servico = Servico.query.get_or_404(servico_id)
    servico.ativo = not servico.ativo
    registrar_evento_auditoria(
        "servico",
        servico.id,
        "ativar" if servico.ativo else "inativar",
    )
    db.session.commit()
    status = "ativado" if servico.ativo else "inativado"
    flash(f"Serviço {status} com sucesso.", "info")
    return redirect(url_for("servicos.listar"))


@servicos_bp.route("/servicos/<int:servico_id>/excluir", methods=["POST"])
@login_required
def excluir(servico_id):
    if not _require_admin():
        return redirect(url_for("auth.dashboard"))

    servico = Servico.query.get_or_404(servico_id)
    if not delete_unlinked_record(servico, "servico"):
        flash(
            "Não é possível excluir: há solicitações vinculadas. Inative o serviço para preservar o histórico.",
            "error",
        )
    else:
        flash("Serviço excluído com sucesso.", "info")
    return redirect(url_for("servicos.listar"))
