import streamlit as st

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from services import leave_service
from utils import ui
from utils.components import format_requests, request_detail, request_picker
from workflows.engine import Actor
from workflows.states import OPEN_STATUSES, RequestStatus

user = require_role(config.ROLE_HR)
actor = Actor.from_session(user)
ui.page_header("All Requests", "Every leave request in the organization, with HR override")

with ui.guard():
    with session_scope() as s:
        req = mt.requests_df(s)
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    f = st.columns(5)
    year = f[0].selectbox("Year", ["All"] + sorted({int(y) for y in req["start_date"].dt.year}, reverse=True))
    dept = f[1].multiselect("Department", sorted(req["department"].unique()))
    status = f[2].multiselect("Status", sorted(req["status"].unique()), format_func=ui.status_label)
    ltype = f[3].multiselect("Leave type", sorted(req["leave_type"].unique()))
    q = f[4].text_input("Employee contains")
    v = req
    if year != "All":
        v = v[v["start_date"].dt.year == year]
    if dept:
        v = v[v["department"].isin(dept)]
    if status:
        v = v[v["status"].isin(status)]
    if ltype:
        v = v[v["leave_type"].isin(ltype)]
    if q:
        v = v[v["employee"].str.contains(q, case=False)]
    st.caption(f"{len(v)} request(s)")
    ui.show_table(format_requests(v, show_employee=True), "Status", height=360)
    rid = request_picker(v, "hr_pick")
    if rid:
        ui.section(f"Request #{rid}")
        request_detail(actor, rid, key=f"hr_{rid}")
        row = v[v["request_id"] == rid].iloc[0]
        st_ = RequestStatus(row["status"])
        if st_ in OPEN_STATUSES or st_ == RequestStatus.APPROVED:
            ui.section("HR override")
            if row["employee_id"] == actor.employee_id:
                st.info("You cannot override your own request.")
            else:
                options = {"Approve": RequestStatus.APPROVED, "Reject": RequestStatus.REJECTED,
                           "Cancel": RequestStatus.CANCELLED} if st_ in OPEN_STATUSES else {"Cancel (revoke approved leave)": RequestStatus.CANCELLED}
                choice = st.radio("Action", list(options), horizontal=True, key=f"ov_act_{rid}")
                reason = st.text_area("Reason (mandatory, recorded in the audit log)", key=f"ov_reason_{rid}")
                if st.button("Apply override", type="primary", key=f"ov_btn_{rid}"):
                    ok, _ = ui.run_action(lambda s: leave_service.override_request(s, actor, rid, options[choice], reason))
                    if ok:
                        st.session_state["flash"] = f"Request #{rid} updated by override."
                        st.rerun()
