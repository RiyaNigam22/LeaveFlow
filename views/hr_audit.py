import json
from datetime import timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select

import config
from auth.session import require_role
from database.connection import session_scope
from database.models import AuditLog, User
from services import audit_service
from utils import ui
from utils.dates import fmt_dt, tz

user = require_role(config.ROLE_HR)
ui.page_header("Audit Log", "Immutable record of state-changing operations")

with ui.guard():
    with session_scope() as s:
        actions = list(s.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)))
        entities = list(s.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)))
        users = {u.id: u.username for u in s.scalars(select(User).order_by(User.username))}
    f = st.columns(5)
    action = f[0].selectbox("Action", [None] + actions, format_func=lambda a: "All" if a is None else a)
    entity = f[1].selectbox("Entity", [None] + entities, format_func=lambda a: "All" if a is None else a)
    uid = f[2].selectbox("User", [None] + list(users), format_func=lambda i: "All" if i is None else users[i])
    d1 = f[3].date_input("From", value=None, format="DD/MM/YYYY")
    d2 = f[4].date_input("To", value=None, format="DD/MM/YYYY")
    start = pd.Timestamp(d1).tz_localize(tz()).to_pydatetime() if d1 else None
    end = (pd.Timestamp(d2) + timedelta(days=1)).tz_localize(tz()).to_pydatetime() if d2 else None
    with session_scope() as s:
        rows = [{"When": fmt_dt(a.created_at), "User": users.get(a.user_id, "—"), "Action": a.action,
                 "Entity": a.entity_type, "Entity ID": a.entity_id or "",
                 "Previous value": json.dumps(a.old_value, default=str) if a.old_value else "",
                 "New value": json.dumps(a.new_value, default=str) if a.new_value else ""}
                for a in audit_service.search(s, action, entity, uid, start, end, limit=1000)]
    st.caption(f"{len(rows)} record(s) shown (latest 1000 max)")
    ui.show_table(pd.DataFrame(rows), height=520)
