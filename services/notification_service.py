"""In-app notifications stored in the database."""
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import config
from database.models import Notification, Role, User
from utils.dates import now_utc

# Categories
SUBMITTED = "LEAVE_SUBMITTED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
APPROVED = "REQUEST_APPROVED"
REJECTED = "REQUEST_REJECTED"
CANCELLED = "REQUEST_CANCELLED"
BALANCE_UPDATED = "BALANCE_UPDATED"
OVERRIDE = "ADMIN_OVERRIDE"
INFO = "INFO"


def notify(session: Session, user_id: int, title: str, message: str, category: str,
           request_id: int | None = None, now: datetime | None = None) -> Notification:
    n = Notification(user_id=user_id, title=title, message=message, category=category,
                     request_id=request_id, created_at=now or now_utc())
    session.add(n)
    return n


def hr_user_ids(session: Session, exclude_user_id: int | None = None) -> list[int]:
    stmt = (select(User.id).join(Role, User.role_id == Role.id)
            .where(Role.name == config.ROLE_HR, User.is_active.is_(True)))
    ids = list(session.scalars(stmt))
    return [i for i in ids if i != exclude_user_id]


def notify_hr(session: Session, title: str, message: str, category: str,
              request_id: int | None = None, exclude_user_id: int | None = None, now: datetime | None = None) -> None:
    for uid in hr_user_ids(session, exclude_user_id):
        notify(session, uid, title, message, category, request_id, now)


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.is_read.is_(False))) or 0


def list_for_user(session: Session, user_id: int, unread_only: bool = False, limit: int = 100) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(session.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)))


def mark_read(session: Session, user_id: int, notification_id: int) -> None:
    session.execute(update(Notification).where(
        Notification.id == notification_id, Notification.user_id == user_id).values(is_read=True))


def mark_all_read(session: Session, user_id: int) -> None:
    session.execute(update(Notification).where(
        Notification.user_id == user_id, Notification.is_read.is_(False)).values(is_read=True))
