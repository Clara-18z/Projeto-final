from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database import db
from database.models import RegistroAuditoria
from services.permissions import has_profile_permission


auditoria_bp = Blueprint("auditoria", __name__, template_folder="../templates")


def _require_permission():
    if not has_profile_permission(
        current_user,
        "administrador",
        "consultar_auditoria",
    ):
        flash("Você não tem permissão para consultar a trilha de auditoria.", "error")
        return False
    return True


def _parse_period():
    hoje = date.today()
    inicio_texto = request.args.get(
        "inicio",
        (hoje - timedelta(days=29)).isoformat(),
    )
    fim_texto = request.args.get("fim", hoje.isoformat())
    try:
        inicio = datetime.strptime(inicio_texto, "%Y-%m-%d").date()
        fim = datetime.strptime(fim_texto, "%Y-%m-%d").date()
    except ValueError:
        return None
    if inicio > fim:
        return None
    return inicio, fim


@auditoria_bp.route("/auditoria")
@login_required
def listar():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    periodo = _parse_period()
    if periodo is None:
        flash("Informe um período válido para consultar a auditoria.", "error")
        return redirect(url_for("auditoria.listar"))

    inicio, fim = periodo
    inicio_dt = datetime.combine(inicio, time.min)
    fim_exclusivo = datetime.combine(fim + timedelta(days=1), time.min)
    statement = (
        select(RegistroAuditoria)
        .options(joinedload(RegistroAuditoria.usuario))
        .where(
            RegistroAuditoria.criado_em >= inicio_dt,
            RegistroAuditoria.criado_em < fim_exclusivo,
        )
        .order_by(RegistroAuditoria.criado_em.desc(), RegistroAuditoria.id.desc())
    )
    page_number = request.args.get("page", 1, type=int)
    pagination = db.paginate(
        statement,
        page=max(page_number or 1, 1),
        per_page=50,
        error_out=False,
    )
    return render_template(
        "auditoria/lista.html",
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        pagination=pagination,
    )
