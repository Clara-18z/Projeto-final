from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from database import db
from database.models import Permissao, Usuario
from services.auditoria import registrar_evento_auditoria
from services.deletions import delete_unlinked_record
from services.permissions import (
    PROFILE_CHOICES,
    PROFILE_PERMISSION_OPTIONS,
    has_profile_permission,
    permissions_for_profile,
)

usuarios_bp = Blueprint("usuarios", __name__, template_folder="../templates")


def _require_permission():
    if not has_profile_permission(
        current_user,
        "administrador",
        "gerenciar_usuarios",
    ):
        flash("Você não tem permissão para gerenciar usuários.", "error")
        return False
    return True


def _permissoes_perfil(perfil):
    return (
        Permissao.query.filter(Permissao.codigo.in_(permissions_for_profile(perfil)))
        .order_by(Permissao.nome.asc())
        .all()
    )


def _selected_permissions(permission_ids, perfil, existing_user=None):
    try:
        selected_ids = {int(permission_id) for permission_id in permission_ids}
    except (TypeError, ValueError):
        return None

    permissoes = _permissoes_perfil(perfil)
    if selected_ids - {permission.id for permission in permissoes}:
        return None
    selected_permissions = [
        permission for permission in permissoes if permission.id in selected_ids
    ]
    if existing_user:
        old_codes = {permission.codigo for permission in existing_user.permissoes}
        legacy_permissions = {
            "recepcionista": {
                "gerenciar_pacientes": {"gerenciar_usuarios", "acessar_dashboard"},
                "gerenciar_solicitacoes": {
                    "gerenciar_servicos",
                    "acessar_dashboard",
                },
                "gerenciar_agenda": {"acessar_dashboard"},
                "gerenciar_fila": {"acessar_dashboard"},
            },
            "medico": {
                "gerenciar_agenda": {"acessar_dashboard"},
            },
        }
        selected_codes = {permission.codigo for permission in selected_permissions}
        for target_code, former_codes in legacy_permissions.get(perfil, {}).items():
            if target_code in selected_codes or not old_codes.intersection(former_codes):
                continue
            target_permission = next(
                (permission for permission in permissoes if permission.codigo == target_code),
                None,
            )
            if target_permission:
                selected_permissions.append(target_permission)
                selected_codes.add(target_code)
    dashboard_permission = next(
        (
            permission
            for permission in permissoes
            if permission.codigo == "acessar_dashboard"
        ),
        None,
    )
    if dashboard_permission and dashboard_permission not in selected_permissions:
        selected_permissions.append(dashboard_permission)
    return selected_permissions


def _would_remove_last_admin(usuario, perfil, ativo, permissions=None):
    is_active_admin = usuario.perfil == "administrador" and usuario.ativo
    if not is_active_admin:
        return False
    assigned_codes = (
        {permission.codigo for permission in permissions}
        if permissions is not None
        else {permission.codigo for permission in usuario.permissoes}
    )
    if (
        perfil == "administrador"
        and ativo
        and "gerenciar_usuarios" in assigned_codes
    ):
        return False

    other_admins = Usuario.query.filter(
        Usuario.perfil == "administrador",
        Usuario.ativo.is_(True),
        Usuario.id != usuario.id,
    ).all()
    return not any(
        any(permission.codigo == "gerenciar_usuarios" for permission in admin.permissoes)
        for admin in other_admins
    )


@usuarios_bp.route("/usuarios")
@login_required
def listar():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    usuarios = Usuario.query.order_by(Usuario.nome_completo.asc()).all()
    return render_template("usuarios/lista.html", usuarios=usuarios)


@usuarios_bp.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
def novo():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    if request.method == "POST":
        nome = request.form.get("nome_completo", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        perfil = request.form.get("perfil", "recepcionista")
        senha = request.form.get("senha", "")
        ativo = request.form.get("ativo") == "on"
        permission_ids = request.form.getlist("permissoes")
        permissoes = _permissoes_perfil(perfil)

        if perfil not in dict(PROFILE_CHOICES):
            flash("Perfil inválido.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=None,
            )
        selected_permissions = _selected_permissions(permission_ids, perfil)
        if selected_permissions is None:
            flash("Há permissões incompatíveis com o perfil selecionado.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=None,
            )

        if not nome or not email or not username or not senha:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=None,
            )

        if Usuario.query.filter((Usuario.email == email) | (Usuario.username == username)).first():
            flash("E-mail ou nome de usuário já cadastrado.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=None,
            )

        usuario = Usuario(
            nome_completo=nome,
            email=email,
            username=username,
            senha_hash=generate_password_hash(senha),
            perfil=perfil,
            ativo=ativo,
        )

        usuario.permissoes = selected_permissions
        from database import db

        db.session.add(usuario)
        db.session.flush()
        registrar_evento_auditoria("usuario", usuario.id, "criar")
        db.session.commit()
        flash("Usuário cadastrado com sucesso.", "info")
        return redirect(url_for("usuarios.listar"))

    return render_template(
        "usuarios/form.html",
        permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
        permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
        perfis=PROFILE_CHOICES,
        usuario=None,
    )


@usuarios_bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
def editar(usuario_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    usuario = Usuario.query.get_or_404(usuario_id)

    if request.method == "POST":
        nome = request.form.get("nome_completo", "").strip()
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        perfil = request.form.get("perfil", usuario.perfil)
        senha = request.form.get("senha", "")
        ativo = request.form.get("ativo") == "on"
        permission_ids = request.form.getlist("permissoes")
        permissoes = _permissoes_perfil(perfil)

        if perfil not in dict(PROFILE_CHOICES):
            flash("Perfil inválido.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )
        selected_permissions = _selected_permissions(
            permission_ids,
            perfil,
            existing_user=usuario,
        )
        if selected_permissions is None:
            flash("Há permissões incompatíveis com o perfil selecionado.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )
        if _would_remove_last_admin(usuario, perfil, ativo, selected_permissions):
            flash("Não é possível remover o último administrador com permissão de gestão.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )
        if usuario.medico and perfil != "medico":
            flash("O perfil de uma conta vinculada a médico não pode ser alterado.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )

        if not nome or not email or not username:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )

        duplicate_user = Usuario.query.filter(
            ((Usuario.email == email) | (Usuario.username == username))
            & (Usuario.id != usuario.id)
        ).first()
        if duplicate_user:
            flash("E-mail ou nome de usuário já cadastrado por outro usuário.", "error")
            return render_template(
                "usuarios/form.html",
                permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
                permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
                perfis=PROFILE_CHOICES,
                usuario=usuario,
            )

        usuario.nome_completo = nome
        usuario.email = email
        usuario.username = username
        usuario.perfil = perfil
        usuario.ativo = ativo
        if senha:
            usuario.senha_hash = generate_password_hash(senha)

        usuario.permissoes = selected_permissions

        registrar_evento_auditoria("usuario", usuario.id, "alterar")
        db.session.commit()
        flash("Usuário atualizado com sucesso.", "info")
        return redirect(url_for("usuarios.listar"))

    return render_template(
        "usuarios/form.html",
        permissoes=Permissao.query.order_by(Permissao.nome.asc()).all(),
        permissoes_por_perfil=PROFILE_PERMISSION_OPTIONS,
        perfis=PROFILE_CHOICES,
        usuario=usuario,
    )


@usuarios_bp.route("/usuarios/<int:usuario_id>/toggle", methods=["POST"])
@login_required
def toggle(usuario_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    usuario = Usuario.query.get_or_404(usuario_id)
    if _would_remove_last_admin(usuario, usuario.perfil, not usuario.ativo):
        flash("Não é possível desativar o último administrador com permissão de gestão.", "error")
        return redirect(url_for("usuarios.listar"))
    usuario.ativo = not usuario.ativo
    registrar_evento_auditoria(
        "usuario",
        usuario.id,
        "ativar" if usuario.ativo else "desativar",
    )
    db.session.commit()
    status = "ativado" if usuario.ativo else "desativado"
    flash(f"Usuário {status} com sucesso.", "info")
    return redirect(url_for("usuarios.listar"))


@usuarios_bp.route("/usuarios/<int:usuario_id>/excluir", methods=["POST"])
@login_required
def excluir(usuario_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    usuario = Usuario.query.get_or_404(usuario_id)
    if usuario.id == current_user.id:
        flash("Não é possível excluir a própria conta conectada.", "error")
    elif _would_remove_last_admin(usuario, usuario.perfil, False):
        flash(
            "Não é possível excluir o último administrador com permissão de gestão.",
            "error",
        )
    elif not delete_unlinked_record(usuario, "usuario"):
        flash(
            "Não é possível excluir: há registros vinculados à conta. Desative o usuário para preservar o histórico.",
            "error",
        )
    else:
        flash("Usuário excluído com sucesso.", "info")
    return redirect(url_for("usuarios.listar"))
