import pandas as pd
import plotly.express as px
import streamlit as st

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from services import leave_service
from services.rules_service import load_policy
from utils import ui
from utils.dates import now_utc, to_local, today_local
from workflows import engine
from workflows.engine import Actor

user = require_role(config.ROLE_MANAGER)
actor = Actor.from_session(user)
ui.page_header("Team Dashboard", "Approval workload and leave activity for your direct reports")
year = today_local().year

with ui.guard():
    with session_scope() as s:
        team = leave_service.direct_reports(s, actor.employee_id)
        ids = [e.id for e in team]
        req = mt.requests_df(s, ids, year)
        steps = mt.steps_df(s, ids, year)
        steps = steps[steps["approver_employee_id"] == actor.employee_id]
        sla = load_policy(s).sla_hours
        queue = [(q.request_id, q.request.employee.full_name, q.request.leave_type.name, q.request.start_date,
                  q.request.working_days, q.activated_at) for q in engine.queue_for_actor(s, actor)]
    month = to_local(now_utc()).strftime("%Y-%m")
    mine = steps[steps["is_decided"]]
    this_month = mine[mine["decided_at"].dt.tz_convert(config.APP_TIMEZONE).dt.strftime("%Y-%m") == month]
    avg_h = float(mine["hours"].mean()) if len(mine) else 0.0
    ui.kpi_cards([("Pending approvals", len(queue), "In your queue now", "warn" if queue else "good"),
                  ("Approved this month", int((this_month["step_status"] == "APPROVED").sum()), "Your decisions"),
                  ("Rejected this month", int((this_month["step_status"] == "REJECTED").sum()), "Your decisions"),
                  ("Avg approval time", ui.fmt_hours(avg_h), f"Your response time · SLA {sla} h", "bad" if avg_h > sla else "good")])
    if not team:
        st.info("You currently have no direct reports.")
    a, b, c = st.columns(3)
    with a:
        ui.chart(px.bar(mt.monthly_trend(req, year), x="Month", y="Approved leave days", title="Team leave trend (approved days)"))
    with b:
        t = mt.leave_by_type(req)
        if t.empty:
            st.info("No approved team leave yet.")
        else:
            ui.chart(px.bar(t, x="Leave type", y="Days", title="Team leave by type"))
    with c:
        ratio = mine["step_status"].value_counts().rename_axis("Decision").reset_index(name="Count")
        if ratio.empty:
            st.info("No decisions yet.")
        else:
            ratio["Decision"] = ratio["Decision"].str.title()
            ui.chart(px.pie(ratio, names="Decision", values="Count", hole=0.55, title="Approval / rejection ratio",
                            color="Decision", color_discrete_map={"Approved": "#12B76A", "Rejected": "#D92D20"}))
    ui.section("Oldest pending approvals")
    if queue:
        rows = [{"ID": q[0], "Employee": q[1], "Leave type": q[2], "Starts": q[3].strftime("%d %b %Y"), "Days": q[4],
                 "Waiting": ui.fmt_hours((now_utc() - q[5]).total_seconds() / 3600),
                 "SLA": "Overdue" if (now_utc() - q[5]).total_seconds() / 3600 > sla else "On track"} for q in queue[:5]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        ui.page_link("views/manager_approvals.py", "Open approval queue", ":material/approval:")
    else:
        st.success("You are all caught up – no requests are waiting for you.")
