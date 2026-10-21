import plotly.express as px
import streamlit as st

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from services.rules_service import load_policy
from utils import ui
from utils.dates import today_local

user = require_role(config.ROLE_HR)
ui.page_header("Process Analytics", "Where does the approval workflow lose time?")
year = st.selectbox("Year", [today_local().year, today_local().year - 1], label_visibility="collapsed")

with ui.guard():
    with session_scope() as s:
        sla = load_policy(s).sla_hours
        req, steps = mt.requests_df(s, year=year), mt.steps_df(s, year=year)
        dept = mt.department_summary(s, year)
    perf = mt.stage_performance(steps, sla)
    at, bn = mt.approval_time_stats(req), mt.bottleneck(perf)
    breaches = int(perf["SLA breaches"].sum())
    ui.kpi_cards([("Average approval time", ui.fmt_hours(at["avg_hours"]), f"{at['count']} completed approvals"),
                  ("Median approval time", ui.fmt_hours(at["median_hours"]), "Typical request"),
                  ("SLA breaches", breaches, f"Stage actions over {sla} h", "bad" if breaches else "good"),
                  ("Bottleneck stage", bn["stage"] if bn else "—", f"{bn['avg_hours']} h avg time in stage" if bn else "", "warn" if bn else "")])

    ui.section("Insights")
    if bn:
        worst = perf.sort_values("Breach rate %", ascending=False).iloc[0]
        st.markdown(f"- **{bn['stage']}** is the slowest stage ({bn['avg_hours']} h on average, including requests still waiting).")
        st.markdown(f"- **{worst['Stage']}** has the highest SLA breach rate: {worst['Breach rate %']}% ({int(worst['SLA breaches'])} breaches against a {sla} h target).")
        if at["avg_hours"] > at["median_hours"] * 1.3:
            st.markdown(f"- Average ({ui.fmt_hours(at['avg_hours'])}) is well above the median ({ui.fmt_hours(at['median_hours'])}): a minority of requests stall for a long time.")
        overdue = steps[steps["is_pending"] & (steps["hours"] > sla)]
        if len(overdue):
            st.markdown(f"- **{len(overdue)} request(s)** are currently waiting longer than the SLA – see the aging table below.")
    else:
        st.info("Not enough workflow activity yet.")

    a, b = st.columns(2)
    with a:
        ui.chart(px.bar(mt.requests_by_stage(req), x="Stage", y="Requests", title="Open requests by workflow stage"))
    with b:
        fig = px.bar(perf, x="Stage", y="Avg hours", title=f"Average time per stage (hours) vs SLA {sla} h")
        fig.add_hline(y=sla, line_dash="dash", line_color="#D92D20", annotation_text="SLA")
        ui.chart(fig)
    c, d = st.columns(2)
    with c:
        trend = mt.monthly_trend(req, year)
        ui.chart(px.line(trend, x="Month", y="Requests submitted", markers=True, title="Request volume trend"))
    with d:
        ui.chart(px.bar(dept, x="Department", y="Absenteeism %", title="Department absenteeism (% of working days, YTD)"))

    ui.section("Stage performance")
    st.dataframe(perf, hide_index=True, width="stretch")
    ui.section("Approver performance")
    st.dataframe(mt.approver_performance(steps, sla), hide_index=True, width="stretch")
    ui.section("Aging of pending approvals")
    aging = steps[steps["is_pending"]].sort_values("hours", ascending=False)
    if aging.empty:
        st.success("No pending approvals.")
    else:
        table = aging[["request_id", "employee", "department", "stage", "approver", "hours"]].copy()
        table["SLA"] = (table["hours"] > sla).map({True: "Overdue", False: "On track"})
        table["hours"] = table["hours"].round(1)
        table["stage"] = table["stage"].str.replace("_", " ").str.title()
        table.columns = ["Request", "Employee", "Department", "Stage", "Waiting on", "Hours waiting", "SLA"]
        st.dataframe(table, hide_index=True, width="stretch")
