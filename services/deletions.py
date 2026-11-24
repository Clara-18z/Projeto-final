from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import Usuario
from services.auditoria import registrar_evento_auditoria


_SECONDARY_TABLES = {"usuario_permissoes"}


def has_linked_records(record):
    for table in db.metadata.tables.values():
        if table is record.__table__ or table.name in _SECONDARY_TABLES:
            continue
        for column in table.columns:
            if any(
                foreign_key.column.table is record.__table__
                for foreign_key in column.foreign_keys
            ) and db.session.execute(
                select(column).where(column == record.id).limit(1)
            ).first():
                return True
    return False


def delete_unlinked_record(record, entity):
    if has_linked_records(record):
        return False

    registrar_evento_auditoria(entity, record.id, "excluir")
    if isinstance(record, Usuario):
        record.permissoes.clear()
    db.session.delete(record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False
    return True
