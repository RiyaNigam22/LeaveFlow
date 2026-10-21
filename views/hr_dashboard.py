import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func, select

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from database.models import Employee
from utils import ui
from utils.dates import today_local

user = require_role(config.ROLE_HR)
ui.page_header("Organization Dashboard", "Leave activity and utilization across the company")
year = st.selectbox("Year", [today_local().year, today_local().year - 1], label_visibility="collapsed")

with ui.guard():
    with session_scope() as s:
        headcount = s.scalar(select(func.count(Employee.id)).where(Employee.is_active.is_(True)))
        req = mt.requests_df(s, year=year)
        bal = mt.balance_df(s, year)
        dept = mt.department_summary(s, year)
    counts, at = mt.status_counts(req), mt.approval_time_stats(req)
    util, sick = mt.utilization_pct(bal), mt.sick_leave_pct(req)
    ui.kpi_cards([("Total employees", headcount, "Active headcount"), ("Total requests", counts["total"], f"Starting in {year}"),
                  ("Pending requests", counts["pending"], "Open in workflow", "warn" if counts["pending"] else "good"),
                  ("Avg approval time", ui.fmt_hours(at["avg_hours"]), f"Median {ui.fmt_hours(at['median_hours'])}"),
                  ("Leave utilization", f"{util}%", "Used ÷ entitled days"), ("Sick leave share", f"{sick}%", "Of approved leave days")])
    a, b = st.columns(2)
    with a:
        trend = mt.monthly_trend(req, year)
        fig = go.Figure([go.Bar(x=trend["Month"], y=trend["Approved leave days"], name="Approved leave days"),
                         go.Scatter(x=trend["Month"], y=trend["Requests submitted"], name="Requests submitted", mode="lines+markers")])
        fig.update_layout(title="Monthly leave trend")
        ui.chart(fig)
    with b:
        dist = mt.leave_by_type(req)
        ui.chart(px.pie(dist, names="Leave type", values="Days", hole=0.5, title="Leave type distribution (approved days)")) if not dist.empty else st.info("No approved leave yet.")
    c, d = st.columns(2)
    with c:
        ui.chart(px.bar(dept, x="Department", y="Approved days", title="Department comparison – approved leave days"))
    with d:
        ui.chart(px.bar(dept, x="Department", y="Utilization %", title="Department leave utilization (%)"))
    e, f = st.columns(2)
    with e:
        hrs = req["approval_hours"].dropna()
        if hrs.empty:
            st.info("No completed approvals yet.")
        else:
            ui.chart(px.histogram(hrs.clip(upper=168).to_frame("Hours"), x="Hours", nbins=21, title="Approval turnaround time (hours, capped at 168)"))
    with f:
        ui.chart(px.bar(dept, x="Department", y="Absenteeism %", title="Department absenteeism – absence days ÷ working days (YTD)"))
    ui.section("Department summary")
    st.dataframe(dept, hide_index=True, width="stretch")
