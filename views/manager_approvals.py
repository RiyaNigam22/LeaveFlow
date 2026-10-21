import streamlit as st

import config
from auth.session import require_role
from database.connection import session_scope
from services import balance_service, leave_service
from services.rules_service import load_policy
from utils import ui
from utils.dates import fmt_date, now_utc
from workflows import engine
from workflows.engine import Actor
from workflows.states import STAGE_LABEL, Stage

user = require_role(config.ROLE_MANAGER, config.ROLE_HR)
actor = Actor.from_session(user)
ui.page_header("Approval Queue", "Requests waiting for your decision")

with ui.guard():
    items = []
    with session_scope() as s:
        sla = load_policy(s).sla_hours
        for step in engine.queue_for_actor(s, actor):
            r = step.request
            avail = None
            if r.leave_type.tracks_balance:
                avail = balance_service.get_or_create_balance(s, r.employee_id, r.leave_type, r.start_date.year).available
            items.append(dict(
                id=r.id, employee=r.employee.full_name, dept=r.employee.department.name, type=r.leave_type.name,
                start=r.start_date, end=r.end_date, days=r.working_days, reason=r.reason, stage=step.stage,
                waiting=(now_utc() - step.activated_at).total_seconds() / 3600, avail=avail,
                conflicts=leave_service.team_conflicts(s, r), doc=(r.document_name, r.document_content)))
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    st.caption(f"{len(items)} request(s) pending · SLA target {sla} h per stage")
    if not items:
        st.success("You are all caught up – no requests are waiting for you.")
    for it in items:
        overdue = it["waiting"] > sla
        with st.container(border=True):
            h1, h2 = st.columns([4, 2])
            h1.markdown(f"**{it['employee']}** · {it['dept']} &nbsp; "
                        f"{ui.status_badge('PENDING')} <small>{STAGE_LABEL[Stage(it['stage'])]} stage</small>", unsafe_allow_html=True)
            h2.markdown(f"<div style='text-align:right;color:{'#B42318' if overdue else '#667085'}'>"
                        f"Waiting {ui.fmt_hours(it['waiting'])}{' · SLA overdue' if overdue else ''}</div>", unsafe_allow_html=True)
            st.write(f"**{it['type']}** · {fmt_date(it['start'])} → {fmt_date(it['end'])} · **{it['days']}** working day(s)")
            if it["reason"]:
                st.caption(f"Reason: {it['reason']}")
            if it["avail"] is not None:
                st.caption(f"Employee's available balance (incl. this request reserved): {it['avail']:g} day(s)")
            if it["conflicts"]:
                st.warning("Overlapping team absence: " + ", ".join(it["conflicts"]))
            if it["doc"][0]:
                st.download_button(f"Download {it['doc'][0]}", it["doc"][1] or b"", file_name=it["doc"][0], key=f"doc_{it['id']}")
            note = st.text_input("Comment (required when rejecting)", key=f"note_{it['id']}")
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("Approve", key=f"ap_{it['id']}", type="primary", width="stretch"):
                ok, _r = ui.run_action(lambda s, i=it["id"]: leave_service.approve_request(s, actor, i, note or None))
                if ok:
                    st.session_state["flash"] = f"Request #{it['id']} approved."
                    st.rerun()
            if b2.button("Reject", key=f"rj_{it['id']}", width="stretch"):
                ok, _r = ui.run_action(lambda s, i=it["id"]: leave_service.reject_request(s, actor, i, note))
                if ok:
                    st.session_state["flash"] = f"Request #{it['id']} rejected."
                    st.rerun()
