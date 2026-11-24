import csv
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from io import StringIO

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func

from database import db
from database.models import (
    Agendamento,
    Medico,
    Senha,
    Servico,
    Solicitacao,
    ValidacaoPagamentoFinanceiro,
)

relatorios_bp = Blueprint("relatorios", __name__, template_folder="../templates")


def _require_permission():
    if current_user.perfil != "administrador" or not any(
        permission.codigo == "consultar_relatorios"
        for permission in current_user.permissoes
    ):
        flash("Você não tem permissão para consultar relatórios.", "error")
        return False
    return True


def _parse_period():
    hoje = date.today()
    periodo = request.args.get("periodo", "personalizado")
    if periodo not in {"diario", "mensal", "anual", "personalizado"}:
        return None

    if periodo == "personalizado":
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
        return periodo, inicio, fim, hoje

    data_referencia_texto = request.args.get("data", hoje.isoformat())
    try:
        data_referencia = datetime.strptime(
            data_referencia_texto,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return None

    if periodo == "diario":
        return periodo, data_referencia, data_referencia, data_referencia
    if periodo == "mensal":
        inicio = data_referencia.replace(day=1)
        fim = data_referencia.replace(
            day=monthrange(data_referencia.year, data_referencia.month)[1]
        )
        return periodo, inicio, fim, data_referencia

    inicio = date(data_referencia.year, 1, 1)
    fim = date(data_referencia.year, 12, 31)
    return periodo, inicio, fim, data_referencia


def _parse_medico_id():
    medico_id_texto = request.args.get("medico_id", "").strip()
    if not medico_id_texto:
        return None
    try:
        medico_id = int(medico_id_texto)
    except ValueError:
        return False
    if medico_id <= 0 or db.session.get(Medico, medico_id) is None:
        return False
    return medico_id


def _chart_rows(rows):
    normalized_rows = [
        (label, float(value or 0)) for label, value in rows
    ]
    max_value = max((value for _, value in normalized_rows), default=0)
    return [
        {
            "label": label,
            "value": value,
            "width": round(value * 100 / max_value) if max_value else 0,
        }
        for label, value in normalized_rows
    ]


def _status_label(status):
    return {
        "agendado": "Agendados",
        "cancelado": "Cancelados",
        "concluido": "Concluídos",
        "aguardando": "Aguardando",
        "chamada": "Chamados",
        "em_atendimento": "Em atendimento",
        "atendido": "Atendidos",
        "nao_compareceu": "Faltas",
    }.get(status, status.replace("_", " ").capitalize())


def _build_report(inicio, fim, medico_id=None):
    inicio_dt = datetime.combine(inicio, time.min)
    fim_exclusivo = datetime.combine(fim + timedelta(days=1), time.min)

    agendamentos_query = db.session.query(
        Agendamento.status,
        func.count(Agendamento.id),
    ).filter(
        Agendamento.data_hora >= inicio_dt,
        Agendamento.data_hora < fim_exclusivo,
    )
    senhas_query = db.session.query(Senha.status, func.count(Senha.id)).filter(
        Senha.data_hora >= inicio_dt,
        Senha.data_hora < fim_exclusivo,
    )
    if medico_id is not None:
        agendamentos_query = agendamentos_query.filter(
            Agendamento.medico_id == medico_id
        )
        senhas_query = senhas_query.filter(Senha.medico_id == medico_id)

    agendamentos_por_status = (
        agendamentos_query.group_by(Agendamento.status)
        .order_by(Agendamento.status)
        .all()
    )
    senhas_por_status = (
        senhas_query.group_by(Senha.status)
        .order_by(Senha.status)
        .all()
    )
    atendimentos_query = db.session.query(Senha.status, func.count(Senha.id)).filter(
        Senha.data_hora >= inicio_dt,
        Senha.data_hora < fim_exclusivo,
        Senha.status.in_({"chamada", "em_atendimento", "atendido"}),
    )
    if medico_id is not None:
        atendimentos_query = atendimentos_query.filter(
            Senha.medico_id == medico_id
        )
    atendimentos_por_status = (
        atendimentos_query
        .group_by(Senha.status)
        .order_by(Senha.status)
        .all()
    )

    pacientes_atendidos_query = db.session.query(
        func.count(func.distinct(Senha.paciente_id))
    ).filter(
        Senha.data_hora >= inicio_dt,
        Senha.data_hora < fim_exclusivo,
        Senha.status == "atendido",
    )
    if medico_id is not None:
        pacientes_atendidos_query = pacientes_atendidos_query.filter(
            Senha.medico_id == medico_id
        )
    total_pacientes_atendidos = pacientes_atendidos_query.scalar() or 0

    medicos_query = Medico.query.order_by(Medico.nome_exibicao.asc())
    if medico_id is not None:
        medicos_query = medicos_query.filter(Medico.id == medico_id)
    produtividade = {
        medico.id: {
            "medico_id": medico.id,
            "nome": medico.nome_exibicao,
            "agendamentos": 0,
            "atendimentos": 0,
            "atendidos": 0,
            "cancelamentos": 0,
            "faltas": 0,
        }
        for medico in medicos_query.all()
    }

    produtividade_agendamentos_query = db.session.query(
        Agendamento.medico_id,
        func.count(Agendamento.id),
        func.sum(case((Agendamento.status == "cancelado", 1), else_=0)),
    ).filter(
        Agendamento.data_hora >= inicio_dt,
        Agendamento.data_hora < fim_exclusivo,
    )
    if medico_id is not None:
        produtividade_agendamentos_query = produtividade_agendamentos_query.filter(
            Agendamento.medico_id == medico_id
        )
    for doctor_id, total, cancelamentos in (
        produtividade_agendamentos_query.group_by(Agendamento.medico_id).all()
    ):
        if doctor_id in produtividade:
            produtividade[doctor_id]["agendamentos"] = total
            produtividade[doctor_id]["cancelamentos"] = cancelamentos or 0

    produtividade_senhas_query = db.session.query(
        Senha.medico_id,
        func.sum(case((Senha.status.in_({"chamada", "em_atendimento", "atendido"}), 1), else_=0)),
        func.sum(case((Senha.status == "atendido", 1), else_=0)),
        func.sum(case((Senha.status == "nao_compareceu", 1), else_=0)),
    ).filter(
        Senha.data_hora >= inicio_dt,
        Senha.data_hora < fim_exclusivo,
    )
    if medico_id is not None:
        produtividade_senhas_query = produtividade_senhas_query.filter(
            Senha.medico_id == medico_id
        )
    for doctor_id, atendimentos, atendidos, faltas in (
        produtividade_senhas_query.group_by(Senha.medico_id).all()
    ):
        if doctor_id in produtividade:
            produtividade[doctor_id]["atendimentos"] = atendimentos or 0
            produtividade[doctor_id]["atendidos"] = atendidos or 0
            produtividade[doctor_id]["faltas"] = faltas or 0

    produtividade_medicos = sorted(
        produtividade.values(),
        key=lambda item: (
            -item["atendidos"],
            -item["agendamentos"],
            item["nome"].casefold(),
        ),
    )
    atendimentos_por_medico = [
        (
            item["nome"],
            item["atendimentos"],
            item["atendidos"],
        )
        for item in produtividade_medicos
    ]

    solicitacoes_query = (
        db.session.query(Servico.nome, func.count(Solicitacao.id))
        .join(Solicitacao, Solicitacao.servico_id == Servico.id)
        .filter(
            Solicitacao.data_solicitacao >= inicio_dt,
            Solicitacao.data_solicitacao < fim_exclusivo,
        )
    )
    if medico_id is not None:
        solicitacoes_query = (
            solicitacoes_query.outerjoin(
                Agendamento,
                Agendamento.solicitacao_id == Solicitacao.id,
            )
            .filter(
                db.or_(
                    Solicitacao.medico_id == medico_id,
                    Agendamento.medico_id == medico_id,
                )
            )
        )
    solicitacoes_por_servico = (
        solicitacoes_query.group_by(Servico.id, Servico.nome)
        .order_by(func.count(Solicitacao.id).desc(), Servico.nome.asc())
        .all()
    )

    horarios_query = db.session.query(
        func.strftime("%H", Agendamento.data_hora),
        func.count(Agendamento.id),
    ).filter(
        Agendamento.data_hora >= inicio_dt,
        Agendamento.data_hora < fim_exclusivo,
        Agendamento.status != "cancelado",
    )
    if medico_id is not None:
        horarios_query = horarios_query.filter(Agendamento.medico_id == medico_id)
    horarios_de_maior_movimento = [
        (f"{hora}:00", total)
        for hora, total in horarios_query.group_by(
            func.strftime("%H", Agendamento.data_hora)
        )
        .order_by(
            func.count(Agendamento.id).desc(),
            func.strftime("%H", Agendamento.data_hora).asc(),
        )
        .all()
    ]

    agendamentos_por_dia_query = db.session.query(
        func.date(Agendamento.data_hora),
        func.count(Agendamento.id),
    ).filter(
        Agendamento.data_hora >= inicio_dt,
        Agendamento.data_hora < fim_exclusivo,
    )
    if medico_id is not None:
        agendamentos_por_dia_query = agendamentos_por_dia_query.filter(
            Agendamento.medico_id == medico_id
        )
    agendamentos_por_dia = (
        agendamentos_por_dia_query.group_by(func.date(Agendamento.data_hora))
        .order_by(func.date(Agendamento.data_hora))
        .all()
    )

    recebidos_query = (
        db.session.query(func.coalesce(func.sum(Solicitacao.valor_snapshot), 0))
        .join(
            ValidacaoPagamentoFinanceiro,
            ValidacaoPagamentoFinanceiro.solicitacao_id == Solicitacao.id,
        )
        .filter(
            ValidacaoPagamentoFinanceiro.data_confirmacao >= inicio_dt,
            ValidacaoPagamentoFinanceiro.data_confirmacao < fim_exclusivo,
        )
    )
    pendentes_query = (
        db.session.query(func.coalesce(func.sum(Solicitacao.valor_snapshot), 0))
        .filter(
            Solicitacao.data_solicitacao >= inicio_dt,
            Solicitacao.data_solicitacao < fim_exclusivo,
            ~Solicitacao.validacao_pagamento.has(),
            Solicitacao.status != "cancelado",
        )
    )
    hoje_inicio = datetime.combine(date.today(), time.min)
    hoje_fim = hoje_inicio + timedelta(days=1)
    recebidos_hoje_query = (
        db.session.query(func.coalesce(func.sum(Solicitacao.valor_snapshot), 0))
        .join(
            ValidacaoPagamentoFinanceiro,
            ValidacaoPagamentoFinanceiro.solicitacao_id == Solicitacao.id,
        )
        .filter(
            ValidacaoPagamentoFinanceiro.data_confirmacao >= hoje_inicio,
            ValidacaoPagamentoFinanceiro.data_confirmacao < hoje_fim,
        )
    )
    if medico_id is not None:
        recebidos_query = (
            recebidos_query.outerjoin(
                Agendamento,
                Agendamento.solicitacao_id == Solicitacao.id,
            )
            .filter(
                db.or_(
                    Solicitacao.medico_id == medico_id,
                    Agendamento.medico_id == medico_id,
                )
            )
        )
        recebidos_hoje_query = (
            recebidos_hoje_query.outerjoin(
                Agendamento,
                Agendamento.solicitacao_id == Solicitacao.id,
            )
            .filter(
                db.or_(
                    Solicitacao.medico_id == medico_id,
                    Agendamento.medico_id == medico_id,
                )
            )
        )
        pendentes_query = (
            pendentes_query.outerjoin(
                Agendamento,
                Agendamento.solicitacao_id == Solicitacao.id,
            )
            .filter(
                db.or_(
                    Solicitacao.medico_id == medico_id,
                    Agendamento.medico_id == medico_id,
                )
            )
        )

    total_agendamentos = sum(total for _, total in agendamentos_por_status)
    total_senhas = sum(total for _, total in senhas_por_status)
    total_atendimentos = sum(
        total
        for status, total in senhas_por_status
        if status == "atendido"
    )
    total_cancelamentos = sum(
        total
        for status, total in agendamentos_por_status
        if status == "cancelado"
    )
    total_faltas = sum(
        total
        for status, total in senhas_por_status
        if status == "nao_compareceu"
    )
    agendamentos_por_status_rotulados = [
        (_status_label(status), total)
        for status, total in agendamentos_por_status
    ]
    atendimentos_por_status_rotulados = [
        (_status_label(status), total)
        for status, total in atendimentos_por_status
    ]
    senhas_por_status_rotulados = [
        (_status_label(status), total)
        for status, total in senhas_por_status
    ]

    valor_recebido = round(float(recebidos_query.scalar() or 0), 2)
    valor_recebido_hoje = round(float(recebidos_hoje_query.scalar() or 0), 2)
    valor_pendente = round(float(pendentes_query.scalar() or 0), 2)

    return {
        "total_agendamentos": total_agendamentos,
        "total_atendimentos": total_atendimentos,
        "total_senhas": total_senhas,
        "total_cancelamentos": total_cancelamentos,
        "total_faltas": total_faltas,
        "total_pacientes_atendidos": total_pacientes_atendidos,
        "valor_recebido": valor_recebido,
        "valor_recebido_hoje": valor_recebido_hoje,
        "valor_pendente": valor_pendente,
        "agendamentos_por_status": agendamentos_por_status_rotulados,
        "atendimentos_por_status": atendimentos_por_status_rotulados,
        "senhas_por_status": senhas_por_status_rotulados,
        "atendimentos_por_medico": atendimentos_por_medico,
        "produtividade_medicos": produtividade_medicos,
        "solicitacoes_por_servico": solicitacoes_por_servico,
        "agendamentos_por_dia": agendamentos_por_dia,
        "horarios_de_maior_movimento": horarios_de_maior_movimento,
        "agendamentos_chart": _chart_rows(agendamentos_por_status_rotulados),
        "atendimentos_chart": _chart_rows(atendimentos_por_status_rotulados),
        "senhas_chart": _chart_rows(senhas_por_status_rotulados),
        "produtividade_chart": _chart_rows(
            [
                (item["nome"], item["atendidos"])
                for item in produtividade_medicos
            ]
        ),
        "horarios_chart": _chart_rows(horarios_de_maior_movimento),
        "financeiro_chart": _chart_rows(
            [
                ("Recebidos no período", valor_recebido),
                ("Recebidos hoje", valor_recebido_hoje),
                ("Pendentes no período", valor_pendente),
            ]
        ),
    }


@relatorios_bp.route("/relatorios")
@login_required
def index():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    filtros_periodo = _parse_period()
    if filtros_periodo is None:
        flash("Informe um período válido, com a data inicial anterior ou igual à final.", "error")
        return redirect(url_for("relatorios.index"))

    medico_id = _parse_medico_id()
    if medico_id is False:
        flash("Selecione um médico válido.", "error")
        return redirect(url_for("relatorios.index"))

    periodo, inicio, fim, data_referencia = filtros_periodo
    relatorio = _build_report(inicio, fim, medico_id)
    medicos = Medico.query.order_by(Medico.nome_exibicao.asc()).all()
    return render_template(
        "relatorios/index.html",
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        periodo=periodo,
        data_referencia=data_referencia.isoformat(),
        medico_id=medico_id,
        medicos=medicos,
        export_url=url_for(
            "relatorios.exportar_csv",
            inicio=inicio.isoformat(),
            fim=fim.isoformat(),
            medico_id=medico_id or "",
        ),
        relatorio=relatorio,
    )


@relatorios_bp.route("/relatorios/exportar.csv")
@login_required
def exportar_csv():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    filtros_periodo = _parse_period()
    if filtros_periodo is None:
        flash("Informe um período válido, com a data inicial anterior ou igual à final.", "error")
        return redirect(url_for("relatorios.index"))

    medico_id = _parse_medico_id()
    if medico_id is False:
        flash("Selecione um médico válido.", "error")
        return redirect(url_for("relatorios.index"))

    _, inicio, fim, _ = filtros_periodo
    relatorio = _build_report(inicio, fim, medico_id)
    medico_selecionado = db.session.get(Medico, medico_id) if medico_id else None
    arquivo = StringIO()
    escritor = csv.writer(arquivo)
    escritor.writerow(["Relatórios e indicadores", inicio.isoformat(), fim.isoformat()])
    escritor.writerow(
        [
            "Médico",
            medico_selecionado.nome_exibicao if medico_selecionado else "Todos",
        ]
    )
    escritor.writerow([])
    escritor.writerow(["Indicador", "Resultado"])
    escritor.writerow(["Agendamentos", relatorio["total_agendamentos"]])
    escritor.writerow(["Atendimentos realizados", relatorio["total_atendimentos"]])
    escritor.writerow(["Pacientes atendidos", relatorio["total_pacientes_atendidos"]])
    escritor.writerow(["Cancelamentos", relatorio["total_cancelamentos"]])
    escritor.writerow(["Faltas", relatorio["total_faltas"]])
    escritor.writerow(["Senhas emitidas", relatorio["total_senhas"]])
    escritor.writerow(["Valores recebidos", f'{relatorio["valor_recebido"]:.2f}'])
    escritor.writerow(
        ["Faturamento recebido hoje", f'{relatorio["valor_recebido_hoje"]:.2f}']
    )
    escritor.writerow(["Valores pendentes", f'{relatorio["valor_pendente"]:.2f}'])
    escritor.writerow([])
    escritor.writerow(["Agendamentos por status", "Quantidade"])
    escritor.writerows(relatorio["agendamentos_por_status"])
    escritor.writerow([])
    escritor.writerow(["Atendimentos por status", "Quantidade"])
    escritor.writerows(relatorio["atendimentos_por_status"])
    escritor.writerow([])
    escritor.writerow(["Senhas por status", "Quantidade"])
    escritor.writerows(relatorio["senhas_por_status"])
    escritor.writerow([])
    escritor.writerow(["Atendimentos por médico", "Total", "Concluídos"])
    escritor.writerows(relatorio["atendimentos_por_medico"])
    escritor.writerow([])
    escritor.writerow(
        ["Produtividade médica", "Agendamentos", "Atendidos", "Cancelamentos", "Faltas"]
    )
    escritor.writerows(
        [
            (
                item["nome"],
                item["agendamentos"],
                item["atendidos"],
                item["cancelamentos"],
                item["faltas"],
            )
            for item in relatorio["produtividade_medicos"]
        ]
    )
    escritor.writerow([])
    escritor.writerow(["Solicitações por serviço", "Quantidade"])
    escritor.writerows(relatorio["solicitacoes_por_servico"])
    escritor.writerow([])
    escritor.writerow(["Agendamentos por dia", "Quantidade"])
    escritor.writerows(relatorio["agendamentos_por_dia"])
    escritor.writerow([])
    escritor.writerow(["Movimento por horário", "Agendamentos"])
    escritor.writerows(relatorio["horarios_de_maior_movimento"])

    response = Response(
        "\ufeff" + arquivo.getvalue(),
        content_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename=relatorio-indicadores-{inicio.isoformat()}-{fim.isoformat()}.csv"
    )
    response.headers["Cache-Control"] = "no-store"
    return response
