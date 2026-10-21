from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from database.models import Department
from services import leave_service
from services.rules_service import load_policy
from sqlalchemy import select
from utils import ui
from utils.dates import today_local
from workflows.engine import Actor

user = require_role(config.ROLE_MANAGER, config.ROLE_HR)
actor = Actor.from_session(user)
is_hr = actor.is_hr
ui.page_header("Team Calendar", "Who is away, when – and where absences overlap" + (" (organization-wide)" if is_hr else ""))

with ui.guard():
    today = today_local()
    f1, f2, f3, f4 = st.columns(4)
    month_start = f1.date_input("Month", value=today.replace(day=1), format="DD/MM/YYYY", help="Any date in the month to show")
    month_start = month_start.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    include_pending = f2.toggle("Include pending requests", value=True)
    min_people = f3.number_input("Overlap alert at (people)", min_value=2, max_value=10, value=2)
    with session_scope() as s:
        if is_hr:
            depts = {d.id: d.name for d in s.scalars(select(Department).order_by(Department.name))}
            chosen = f4.multiselect("Department", list(depts), format_func=depts.get)
            req = mt.requests_df(s)
            if chosen:
                req = req[req["department_id"].isin(chosen)]
        else:
            ids = [e.id for e in leave_service.direct_reports(s, actor.employee_id)]
            req = mt.requests_df(s, ids)
        policy = load_policy(s)
    statuses = ("APPROVED", "MANAGER_PENDING", "HR_PENDING", "DEPARTMENT_HEAD_PENDING") if include_pending else ("APPROVED",)
    cal = mt.calendar_df(req, month_start, month_end, statuses)
    if cal.empty:
        st.info("No leave is scheduled for this period.")
        st.stop()
    cal = cal.assign(State=cal["status"].map(ui.status_label), Finish=cal["end_date"] + pd.Timedelta(days=1))
    fig = px.timeline(cal, x_start="start_date", x_end="Finish", y="employee", color="leave_type", pattern_shape="State",
                      hover_data={"department": True, "State": True, "working_days": True, "Finish": False},
                      title=f"Leave in {month_start:%B %Y}")
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(range=[month_start, month_end + timedelta(days=1)])
    ui.chart(fig)
    ui.section("Overlapping absences")
    ov = mt.overlap_days(cal[cal["start_date"].notna()], policy.holidays, policy.weekend_days, int(min_people))
    if ov.empty:
        st.success(f"No days with {int(min_people)} or more people away.")
    else:
        st.warning(f"{len(ov)} day(s) with {int(min_people)}+ people away – check coverage.")
        ov["Date"] = ov["Date"].map(lambda d: d.strftime("%a %d %b %Y"))
        st.dataframe(ov, hide_index=True, width="stretch")
    ui.section("Leave schedule")
    table = pd.DataFrame({"Employee": cal["employee"], "Department": cal["department"], "Leave type": cal["leave_type"],
                          "Start date": cal["start_date"].dt.strftime("%d %b %Y"), "End date": cal["end_date"].dt.strftime("%d %b %Y"),
                          "Days": cal["working_days"], "Status": cal["State"]})
    ui.show_table(table, "Status")
