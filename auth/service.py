# """Authentication logic (framework independent, unit-testable)."""
# from datetime import datetime, timedelta

# from sqlalchemy import select
# from sqlalchemy.orm import Session, joinedload

# import config
# from auth.security import hash_password, validate_password_strength, verify_password
# from database.models import User
# from services import audit_service
# from utils.dates import now_utc
# from utils.errors import AuthenticationError

# GENERIC_FAILURE = "Invalid username or password."


# def authenticate(session: Session, username: str, password: str, now: datetime | None = None) -> User:
#     """Validate credentials, apply lockout policy and write audit records.

#     Raises AuthenticationError with a user-safe message on failure. Failed-attempt counters are
#     persisted by the caller committing the session (call this inside session_scope and catch the
#     error *outside* the scope only after calling commit – see auth.session.login).
#     """
#     now = now or now_utc()
#     username = (username or "").strip().lower()
#     user = session.scalars(select(User).options(joinedload(User.role), joinedload(User.employee))
#                            .where(User.username == username)).first()
#     if user is None or not user.is_active or not user.employee.is_active:
#         audit_service.log(session, None, "LOGIN_FAILED", "User", None, new={"username": username}, now=now)
#         raise AuthenticationError(GENERIC_FAILURE)
#     if user.locked_until and user.locked_until > now:
#         minutes = int((user.locked_until - now).total_seconds() // 60) + 1
#         raise AuthenticationError(f"Account temporarily locked. Try again in about {minutes} minute(s).")
#     if not verify_password(password or "", user.password_hash):
#         user.failed_attempts = (user.failed_attempts or 0) + 1
#         audit_service.log(session, user.id, "LOGIN_FAILED", "User", user.id, now=now)
#         if user.failed_attempts >= config.MAX_LOGIN_ATTEMPTS:
#             user.locked_until = now + timedelta(minutes=config.LOCKOUT_MINUTES)
#             user.failed_attempts = 0
#             audit_service.log(session, user.id, "ACCOUNT_LOCKED", "User", user.id, now=now)
#         raise AuthenticationError(GENERIC_FAILURE)
#     user.failed_attempts = 0
#     user.locked_until = None
#     user.last_login_at = now
#     audit_service.log(session, user.id, "LOGIN", "User", user.id, now=now)
#     return user


# def change_password(session: Session, user_id: int, current: str, new: str) -> None:
#     user = session.get(User, user_id)
#     if user is None or not verify_password(current, user.password_hash):
#         raise AuthenticationError("Current password is incorrect.")
#     validate_password_strength(new)
#     user.password_hash = hash_password(new)
#     audit_service.log(session, user_id, "PASSWORD_CHANGED", "User", user_id)


"""Authentication logic (framework independent, unit-testable)."""
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

import config
from auth.security import hash_password, validate_password_strength, verify_password
from database.models import Employee, User
from services import audit_service
from utils.dates import now_utc
from utils.errors import AuthenticationError

GENERIC_FAILURE = "Invalid username or password."


def authenticate(session: Session, login_input: str, password: str, now: datetime | None = None) -> User:
    """Validate credentials (accepts username or email), apply lockout policy and write audit records.

    Raises AuthenticationError with a user-safe message on failure. Failed-attempt counters are
    persisted by the caller committing the session (call this inside session_scope and catch the
    error *outside* the scope only after calling commit – see auth.session.login).
    """
    now = now or now_utc()
    login_input = (login_input or "").strip().lower()

    # Query matching either User.username OR Employee.email
    query = (
        select(User)
        .join(User.employee)
        .options(joinedload(User.role), joinedload(User.employee))
        .where(
            or_(
                func.lower(User.username) == login_input,
                func.lower(Employee.email) == login_input,
            )
        )
    )
    user = session.scalars(query).first()

    if user is None or not user.is_active or not user.employee.is_active:
        audit_service.log(session, None, "LOGIN_FAILED", "User", None, new={"username": login_input}, now=now)
        raise AuthenticationError(GENERIC_FAILURE)
    if user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        raise AuthenticationError(f"Account temporarily locked. Try again in about {minutes} minute(s).")
    if not verify_password(password or "", user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        audit_service.log(session, user.id, "LOGIN_FAILED", "User", user.id, now=now)
        if user.failed_attempts >= config.MAX_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=config.LOCKOUT_MINUTES)
            user.failed_attempts = 0
            audit_service.log(session, user.id, "ACCOUNT_LOCKED", "User", user.id, now=now)
        raise AuthenticationError(GENERIC_FAILURE)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    audit_service.log(session, user.id, "LOGIN", "User", user.id, now=now)
    return user


def change_password(session: Session, user_id: int, current: str, new: str) -> None:
    user = session.get(User, user_id)
    if user is None or not verify_password(current, user.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    validate_password_strength(new)
    user.password_hash = hash_password(new)
    audit_service.log(session, user_id, "PASSWORD_CHANGED", "User", user_id)