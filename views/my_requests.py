import streamlit as st

from analytics import metrics as mt
from auth.session import require_login
from database.connection import session_scope
from utils import ui
from utils.components import format_requests, request_detail, request_picker
from utils.dates import today_local
from workflows.engine import Actor

user = require_login()
actor = Actor.from_session(user)
ui.page_header("My Requests", "History and status of all your leave requests")

with ui.guard():
    with session_scope() as s:
        req = mt.requests_df(s, [user["employee_id"]])
    years = sorted({int(y) for y in req["start_date"].dt.year}, reverse=True) or [today_local().year]
    f1, f2, f3 = st.columns(3)
    year = f1.selectbox("Year", ["All"] + years)
    statuses = f2.multiselect("Status", sorted(req["status"].unique()), format_func=ui.status_label)
    types = f3.multiselect("Leave type", sorted(req["leave_type"].unique()))
    view = req
    if year != "All":
        view = view[view["start_date"].dt.year == year]
    if statuses:
        view = view[view["status"].isin(statuses)]
    if types:
        view = view[view["leave_type"].isin(types)]
    ui.show_table(format_requests(view), "Status", height=340)
    rid = request_picker(view, "my_req_pick")
    if rid:
        ui.section(f"Request #{rid}")
        request_detail(actor, rid, key=f"my_{rid}", allow_cancel=True)
