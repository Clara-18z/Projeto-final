from flask import request
from flask_login import current_user

from database import db
from database.models import RegistroAuditoria


def registrar_evento_auditoria(entidade, entidade_id, acao):
    db.session.add(
        RegistroAuditoria(
            usuario_id=current_user.id if current_user.is_authenticated else None,
            entidade=entidade,
            entidade_id=entidade_id,
            acao=acao,
            ip=request.remote_addr,
        )
    )


def registrar_consulta_auditoria(entidade, registros):
    if registros:
        for registro in registros:
            registrar_evento_auditoria(entidade, registro.id, "consultar")
    else:
        registrar_evento_auditoria(entidade, 0, "consultar_lista")
    db.session.commit()
