import streamlit as st

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from services import balance_service, leave_service
from utils import ui
from utils.components import format_requests, request_detail, request_picker
from utils.dates import today_local
from workflows.engine import Actor

user = require_role(config.ROLE_MANAGER)
actor = Actor.from_session(user)
ui.page_header("Team Leave History", "Leave records and balances of your direct reports")

with ui.guard():
    with session_scope() as s:
        team = {e.id: e.full_name for e in leave_service.direct_reports(s, actor.employee_id)}
    if not team:
        st.info("You currently have no direct reports.")
        st.stop()
    c1, c2 = st.columns([2, 1])
    emp_id = c1.selectbox("Employee", list(team), format_func=team.get)
    year = c2.selectbox("Year", [today_local().year, today_local().year - 1])
    with session_scope() as s:
        req = mt.requests_df(s, [emp_id], year)
        bal = [{"Leave type": b.leave_type.name, "Entitled": float(b.total), "Used": float(b.used),
                "Pending": float(b.pending), "Available": float(b.available)}
               for b in balance_service.list_for_employee(s, emp_id, year)]
    counts = mt.status_counts(req)
    ui.kpi_cards([("Requests", counts["total"]), ("Approved", counts["approved"], "", "good"),
                  ("Pending", counts["pending"], "", "warn" if counts["pending"] else ""),
                  ("Rejected", counts["rejected"], "", "bad" if counts["rejected"] else "")])
    ui.section("Leave balances")
    st.dataframe(bal, hide_index=True, width="stretch")
    ui.section("Requests")
    ui.show_table(format_requests(req), "Status", height=320)
    rid = request_picker(req, "hist_pick")
    if rid:
        request_detail(actor, rid, key=f"hist_{rid}")
