"""Audit trail. Every state-changing operation calls log() inside the same transaction."""
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditLog
from utils.dates import now_utc


def _json_safe(value):
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


def log(session: Session, user_id: int | None, action: str, entity_type: str, entity_id,
        old=None, new=None, now: datetime | None = None) -> AuditLog:
    entry = AuditLog(
        user_id=user_id, action=action, entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        old_value=_json_safe(old), new_value=_json_safe(new), created_at=now or now_utc(),
    )
    session.add(entry)
    return entry


def snapshot(obj, fields: list[str]) -> dict:
    """Capture selected column values of an ORM object for old/new audit values."""
    return {f: getattr(obj, f) for f in fields}


def recent(session: Session, limit: int = 500) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)))


def search(session: Session, action: str | None = None, entity_type: str | None = None, user_id: int | None = None,
           start: datetime | None = None, end: datetime | None = None, limit: int = 500) -> list[AuditLog]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at < end)
    return list(session.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)))
