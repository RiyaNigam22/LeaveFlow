# """Streamlit session handling and role-based access control.

# Authentication state lives in st.session_state (server-side, per browser session) – the browser
# only holds Streamlit's own session id, never credentials. Sessions expire after
# SESSION_TIMEOUT_MINUTES of inactivity.
# """
# from datetime import datetime, timedelta, timezone

# import streamlit as st

# import config
# from auth.service import authenticate
# from database.connection import session_scope
# from services import audit_service
# from utils.errors import AuthenticationError

# _KEY = "auth_user"


# def current_user() -> dict | None:
#     user = st.session_state.get(_KEY)
#     if not user:
#         return None
#     now = datetime.now(timezone.utc)
#     if now - user["last_seen"] > timedelta(minutes=config.SESSION_TIMEOUT_MINUTES):
#         st.session_state.pop(_KEY, None)
#         st.session_state["session_expired"] = True
#         return None
#     user["last_seen"] = now
#     return user


# def login(username: str, password: str) -> None:
#     """Raises AuthenticationError on failure (failed-attempt bookkeeping is committed first)."""
#     error: AuthenticationError | None = None
#     with session_scope() as session:
#         try:
#             user = authenticate(session, username, password)
#         except AuthenticationError as exc:
#             error = exc          # keep the audit/lockout changes: commit, then re-raise below
#             user = None
#         if user is not None:
#             st.session_state[_KEY] = {
#                 "user_id": user.id, "username": user.username, "role": user.role.name,
#                 "employee_id": user.employee_id, "full_name": user.employee.full_name,
#                 "department_id": user.employee.department_id,
#                 "last_seen": datetime.now(timezone.utc),
#             }
#             st.session_state.pop("session_expired", None)
#     if error:
#         raise error


# def logout() -> None:
#     user = st.session_state.pop(_KEY, None)
#     if user:
#         with session_scope() as session:
#             audit_service.log(session, user["user_id"], "LOGOUT", "User", user["user_id"])
#     for key in list(st.session_state.keys()):
#         if key != "session_expired":
#             del st.session_state[key]


# def require_login() -> dict:
#     user = current_user()
#     if user is None:
#         st.warning("Your session has expired or you are not signed in. Please sign in again.")
#         st.stop()
#     return user


# def require_role(*roles: str) -> dict:
#     """Page-level authorisation guard – stops the page if the role is not permitted."""
#     user = require_login()
#     if user["role"] not in roles:
#         st.error("You do not have permission to view this page.")
#         st.stop()
#     return user


"""Streamlit session handling and role-based access control.

Authentication state lives in st.session_state (server-side, per browser session) – the browser
only holds Streamlit's own session id, never credentials. Sessions expire after
SESSION_TIMEOUT_MINUTES of inactivity.
"""
from datetime import datetime, timedelta, timezone

import streamlit as st

import config
from auth.service import authenticate
from database.connection import session_scope
from services import audit_service
from utils.errors import AuthenticationError

_KEY = "auth_user"


def current_user() -> dict | None:
    user = st.session_state.get(_KEY)
    if not user:
        return None
    now = datetime.now(timezone.utc)
    if now - user["last_seen"] > timedelta(minutes=config.SESSION_TIMEOUT_MINUTES):
        st.session_state.pop(_KEY, None)
        st.session_state["session_expired"] = True
        return None
    user["last_seen"] = now
    return user


# def login(username: str, password: str) -> None:
#     """Raises AuthenticationError on failure (failed-attempt bookkeeping is committed first)."""
#     error: AuthenticationError | None = None
#     with session_scope() as session:
#         try:
#             user = authenticate(session, username, password)
#         except AuthenticationError as exc:
#             error = exc          # keep the audit/lockout changes: commit, then re-raise below
#             user = None
#         if user is not None:
#             st.session_state[_KEY] = {
#                 "user_id": user.id, "username": user.username, "role": user.role.name,
#                 "employee_id": user.employee_id, "full_name": user.employee.full_name,
#                 "department_id": user.employee.department_id,
#                 "last_seen": datetime.now(timezone.utc),
#             }
#             st.session_state.pop("session_expired", None)
#     if error:
#         raise error

def login(username: str, password: str) -> None:
    """Raises AuthenticationError on failure (failed-attempt bookkeeping is committed first)."""
    error: AuthenticationError | None = None
    with session_scope() as session:
        try:
            user = authenticate(session, username, password)
        except AuthenticationError as exc:
            error = exc          # keep the audit/lockout changes: commit, then re-raise below
            user = None
        if user is not None:
            # Map DB role names to match config constants cleanly
            raw_role = user.role.name.upper()
            if raw_role in ("HR", "HR_ADMIN"):
                user_role = config.ROLE_HR          # Evaluates to "HR_ADMIN"
            elif raw_role == "MANAGER":
                user_role = config.ROLE_MANAGER     # Evaluates to "MANAGER"
            elif raw_role == "EMPLOYEE":
                user_role = config.ROLE_EMPLOYEE    # Evaluates to "EMPLOYEE"
            else:
                user_role = raw_role

            st.session_state[_KEY] = {
                "user_id": user.id, 
                "username": user.username, 
                "role": user_role,
                "employee_id": user.employee_id, 
                "full_name": user.employee.full_name,
                "department_id": user.employee.department_id,
                "last_seen": datetime.now(timezone.utc),
            }
            st.session_state.pop("session_expired", None)
    if error:
        raise error
    
def logout() -> None:
    user = st.session_state.pop(_KEY, None)
    if user:
        with session_scope() as session:
            audit_service.log(session, user["user_id"], "LOGOUT", "User", user["user_id"])
    for key in list(st.session_state.keys()):
        if key != "session_expired":
            del st.session_state[key]


def require_login() -> dict:
    user = current_user()
    if user is None:
        st.warning("Your session has expired or you are not signed in. Please sign in again.")
        st.stop()
    return user


def require_role(*roles: str) -> dict:
    """Page-level authorisation guard – stops the page if the role is not permitted."""
    user = require_login()
    if user["role"] not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()
    return user
