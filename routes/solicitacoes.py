from datetime import datetime
import random

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import db
from database.models import (
    Medico,
    Paciente,
    Servico,
    Solicitacao,
    Usuario,
)
from services.auditoria import (
    registrar_consulta_auditoria,
    registrar_evento_auditoria,
)
from services.permissions import has_profile_permission

solicitacoes_bp = Blueprint("solicitacoes", __name__, template_folder="../templates")


def _require_permission():
    if not has_profile_permission(
        current_user,
        "recepcionista",
        {"gerenciar_solicitacoes", "acessar_dashboard"},
    ):
        flash("Você não tem permissão para gerenciar solicitações.", "error")
        return False
    return True


@solicitacoes_bp.route("/solicitacoes")
@login_required
def listar():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    solicitacoes = Solicitacao.query.order_by(Solicitacao.data_solicitacao.desc()).all()
    registrar_consulta_auditoria("solicitacao", solicitacoes)
    return render_template("solicitacoes/lista.html", solicitacoes=solicitacoes)


@solicitacoes_bp.route("/solicitacoes/nova", methods=["GET", "POST"])
@login_required
def nova():
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    pacientes = Paciente.query.filter_by(ativo=True).order_by(Paciente.nome_completo.asc()).all()
    registrar_consulta_auditoria("paciente", pacientes)
    servicos = Servico.query.filter_by(ativo=True).order_by(Servico.nome.asc()).all()
    medicos = (
        Medico.query.join(Usuario, Medico.usuario_id == Usuario.id)
        .filter(
            Medico.ativo.is_(True),
            Medico.sala_id.isnot(None),
            Usuario.ativo.is_(True),
            Usuario.perfil == "medico",
        )
        .order_by(Medico.nome_exibicao.asc())
        .all()
    )
    medicos = [
        medico
        for medico in medicos
        if medico.sala and medico.sala.ativa and medico.sala.status != "indisponivel"
    ]
    form_context = {
        "solicitacao": None,
        "pacientes": pacientes,
        "servicos": servicos,
        "medicos": medicos,
    }
    if request.method == "POST":
        paciente_id = request.form.get("paciente_id", type=int)
        servico_id = request.form.get("servico_id", type=int)
        medico_id = request.form.get("medico_id", type=int)
        observacoes = request.form.get("observacoes", "").strip()

        servico = db.session.get(Servico, servico_id) if servico_id else None
        if not servico or not servico.ativo:
            flash("Selecione um serviço válido e ativo.", "error")
            return render_template(
                "solicitacoes/form.html",
                **form_context,
                form_data=request.form,
            )

        medico = next(
            (
                item
                for item in medicos
                if item.id == medico_id
                and item.especialidade_id == servico.especialidade_id
            ),
            None,
        )
        if not medico:
            flash(
                "Selecione um médico ativo da especialidade do serviço, "
                "com sala disponível.",
                "error",
            )
            return render_template(
                "solicitacoes/form.html",
                **form_context,
                form_data=request.form,
            )

        paciente = db.session.get(Paciente, paciente_id) if paciente_id else None
        if paciente_id and (not paciente or not paciente.ativo):
            flash("Selecione um paciente ativo.", "error")
            return render_template(
                "solicitacoes/form.html",
                **form_context,
                form_data=request.form,
            )

        novo_paciente = False
        if paciente is None:
            nome = request.form.get("novo_nome_completo", "").strip()
            cpf = Paciente.normalize_cpf(request.form.get("novo_cpf", ""))
            data_nascimento_texto = request.form.get("novo_data_nascimento", "").strip()
            telefone = request.form.get("novo_telefone", "").strip()
            endereco = request.form.get("novo_endereco", "").strip()
            observacoes_paciente = request.form.get("novo_observacoes", "").strip()
            try:
                data_nascimento = datetime.strptime(
                    data_nascimento_texto,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                data_nascimento = None

            if not nome or not cpf or not data_nascimento or not telefone or not endereco:
                flash("Preencha todos os dados obrigatórios do paciente.", "error")
                return render_template(
                    "solicitacoes/form.html",
                    **form_context,
                    form_data=request.form,
                )
            if len(cpf) != 11 or not cpf.isdigit():
                flash("CPF inválido. Informe 11 dígitos numéricos.", "error")
                return render_template(
                    "solicitacoes/form.html",
                    **form_context,
                    form_data=request.form,
                )
            if Paciente.query.filter_by(cpf=cpf).first():
                flash("Paciente já cadastrado com este CPF; selecione-o na lista.", "error")
                return render_template(
                    "solicitacoes/form.html",
                    **form_context,
                    form_data=request.form,
                )
            paciente = Paciente(
                nome_completo=nome,
                cpf=cpf,
                data_nascimento=data_nascimento,
                telefone=telefone,
                endereco=endereco,
                observacoes=observacoes_paciente or None,
                ativo=True,
            )
            db.session.add(paciente)
            db.session.flush()
            registrar_evento_auditoria("paciente", paciente.id, "criar")
            novo_paciente = True

        codigo = f"SL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"

        solicitacao = Solicitacao(
            codigo=codigo,
            paciente_id=paciente.id,
            servico_id=servico.id,
            especialidade_id=servico.especialidade_id,
            medico_id=medico.id,
            valor_snapshot=servico.valor,
            status="aguardando_pagamento",
            observacoes=observacoes or None,
        )

        db.session.add(solicitacao)
        db.session.flush()
        registrar_evento_auditoria("solicitacao", solicitacao.id, "criar")
        db.session.commit()
        flash(
            "Paciente e atendimento registrados. Imprima o documento para o paciente levar ao setor financeiro."
            if novo_paciente
            else "Atendimento registrado. Imprima o documento para o paciente levar ao setor financeiro.",
            "info",
        )
        return redirect(
            url_for("solicitacoes.documento_financeiro", solicitacao_id=solicitacao.id)
        )

    return render_template(
        "solicitacoes/form.html",
        **form_context,
        form_data={},
    )


@solicitacoes_bp.route("/solicitacoes/<int:solicitacao_id>/documento-financeiro")
@login_required
def documento_financeiro(solicitacao_id):
    if not _require_permission():
        return redirect(url_for("auth.dashboard"))

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    registrar_consulta_auditoria("solicitacao", [solicitacao])
    db.session.commit()
    return render_template(
        "solicitacoes/documento_financeiro.html",
        solicitacao=solicitacao,
        data_emissao=datetime.now(),
    )


@solicitacoes_bp.route("/solicitacoes/<int:solicitacao_id>/confirmar-pagamento", methods=["GET", "POST"])
@login_required
def confirmar_pagamento(solicitacao_id):
    flash(
        "A confirmação de pagamentos está disponível somente no módulo Financeiro.",
        "error",
    )
    if has_profile_permission(current_user, "financeiro", "gerenciar_financeiro"):
        return redirect(url_for("financeiro.index"))
    return redirect(url_for("auth.dashboard"))
