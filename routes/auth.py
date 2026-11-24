from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash
from urllib.parse import urlsplit

from database import db
from database.models import Usuario


auth_bp = Blueprint("auth", __name__, template_folder="../templates")


def _dashboard_endpoint():
    if current_user.perfil == "financeiro":
        return "financeiro.index"
    return "auth.dashboard"


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(_dashboard_endpoint()))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        user = Usuario.query.filter(
            (Usuario.email == identifier) | (Usuario.username == identifier)
        ).first()

        if user and user.ativo and check_password_hash(user.senha_hash, password):
            if (
                user.perfil == "medico"
                and user.medico is not None
                and user.medico.ativo
            ):
                user.medico.presenca_ativa = True
                db.session.commit()
            login_user(user)
            next_page = request.args.get("next")
            if next_page:
                parsed_next = urlsplit(next_page)
                if (
                    not parsed_next.scheme
                    and not parsed_next.netloc
                    and next_page.startswith("/")
                    and not next_page.startswith("//")
                    and "\\" not in next_page
                ):
                    return redirect(next_page)
            return redirect(url_for(_dashboard_endpoint()))

        flash("Credenciais inválidas ou usuário inativo.", "error")
        return redirect(url_for("auth.login", clear="1"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    if current_user.perfil == "medico" and current_user.medico is not None:
        current_user.medico.presenca_ativa = False
        db.session.commit()
    logout_user()
    flash("Sessão encerrada com sucesso.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/dashboard")
@login_required
def dashboard():
    if not any(
        permission.codigo == "acessar_dashboard" for permission in current_user.permissoes
    ):
        flash("Você não possui permissão para acessar o dashboard.", "error")
        logout_user()
        return redirect(url_for("auth.login"))

    return render_template(
        "dashboard.html",
        user=current_user,
    )


