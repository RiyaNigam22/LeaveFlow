from datetime import timedelta

import streamlit as st
from sqlalchemy import select

from auth.session import require_login
from database.connection import session_scope
from database.models import Employee, LeaveType
from services import leave_service, rules_service
from utils import ui
from utils.dates import today_local
from workflows import engine
from workflows.engine import Actor

user = require_login()
actor = Actor.from_session(user)
ui.page_header("Request Leave", "Submit a new request. Validation runs automatically as you fill in the form.")

with ui.guard():
    with session_scope() as s:
        types = [(t.id, t.name, t.requires_document, t.document_threshold_days, t.document_description,
                  t.requires_approval, t.max_consecutive_days) for t in s.scalars(
            select(LeaveType).where(LeaveType.is_active.is_(True)).order_by(LeaveType.name))]
    if not types:
        st.warning("No leave types are currently available. Please contact HR.")
        st.stop()
    by_id = {t[0]: t for t in types}
    v = st.session_state.setdefault("form_version", 0)   # bumping this resets every widget after a successful submit

    if msg := st.session_state.pop("submitted_msg", None):
        st.success(msg)

    col_form, col_check = st.columns([3, 2], gap="large")
    with col_form:
        type_id = st.selectbox("Leave type", list(by_id), format_func=lambda i: by_id[i][1], key=f"lt_{v}")
        _, name, needs_doc, threshold, doc_desc, needs_approval, max_days = by_id[type_id]
        d1, d2 = st.columns(2)
        default = today_local() + timedelta(days=1)
        start = d1.date_input("From", value=default, format="DD/MM/YYYY", key=f"from_{v}")
        end = d2.date_input("To", value=default, format="DD/MM/YYYY", key=f"to_{v}")
        reason = st.text_area("Reason (optional)", max_chars=500, height=100, key=f"reason_{v}")
        document = None
        if needs_doc:
            document = st.file_uploader(f"{doc_desc} (required for more than {threshold} working day(s))",
                                        type=["pdf", "png", "jpg", "jpeg"], key=f"doc_{type_id}_{v}")

    with session_scope() as s:
        employee = s.get(Employee, user["employee_id"])
        leave_type = s.get(LeaveType, type_id)
        result = rules_service.validate_leave_request(s, employee, leave_type, start, end, document is not None)
        chain = engine.describe_chain(s, employee, result.stages) if result.working_days and leave_type.requires_approval else ""
        s.rollback()   # preview only – do not persist lazily created balance rows

    with col_check:
        ui.section("Request check")
        if result.working_days:
            st.metric("Working days", result.working_days, help="Weekends and company holidays are excluded.")
        if result.available_balance is not None:
            st.caption(f"Available balance: **{result.available_balance:g}** day(s)")
        if chain:
            st.caption(f"Approval path: {chain}")
        elif result.working_days and not needs_approval:
            st.caption("This leave type does not require approval.")
        for w in result.warnings:
            st.warning(w)
        for e in result.errors:
            st.error(e)
        if result.valid:
            st.success("This request passes all validation checks.")

    if st.button("Submit request", type="primary", disabled=not result.valid):
        doc = (document.name, document.getvalue()) if document else None
        ok, req = ui.run_action(lambda s: (lambda r: (r, leave_service.submission_message(r)))(
            leave_service.submit_leave_request(s, actor, type_id, start, end, reason, doc)))
        if ok:
            st.session_state["submitted_msg"] = req[1]
            st.session_state["form_version"] = v + 1
            st.rerun()
