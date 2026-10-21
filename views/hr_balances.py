from decimal import Decimal

import streamlit as st
from sqlalchemy import select

import config
from analytics import metrics as mt
from auth.session import require_role
from database.connection import session_scope
from database.models import Employee
from services import admin_service as admin, balance_service
from utils import ui
from utils.dates import today_local
from workflows.engine import Actor

user = require_role(config.ROLE_HR)
actor = Actor.from_session(user)
ui.page_header("Leave Balances", "Review and configure leave entitlements")

with ui.guard():
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    this_year = today_local().year
    c = st.columns([2, 1])
    year = c[1].selectbox("Year", [this_year + 1, this_year, this_year - 1], index=1)
    with session_scope() as s:
        emps = {e.id: f"{e.employee_code} · {e.full_name}" for e in s.scalars(
            select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.employee_code))}
    emp_id = c[0].selectbox("Employee", list(emps), format_func=emps.get)

    with session_scope() as s:
        bals = [(b.leave_type_id, b.leave_type.name, b.allocated, b.carried_forward, b.used, b.pending, b.available)
                for b in balance_service.list_for_employee(s, emp_id, year)]
    with st.form(f"bal_{emp_id}_{year}"):
        st.caption("Edit the entitlement; used and pending days are maintained by the workflow.")
        new = {}
        for lt_id, name, alloc, carry, used, pend, avail in bals:
            cols = st.columns([2, 1, 1, 1, 1, 1])
            cols[0].markdown(f"**{name}**")
            a = cols[1].number_input("Allocated", 0.0, 365.0, float(alloc), 0.5, key=f"a{lt_id}")
            cf = cols[2].number_input("Carried fwd", 0.0, 365.0, float(carry), 0.5, key=f"c{lt_id}")
            cols[3].metric("Used", f"{used:g}")
            cols[4].metric("Pending", f"{pend:g}")
            cols[5].metric("Available", f"{avail:g}")
            new[lt_id] = (a, cf, float(alloc), float(carry))
        if st.form_submit_button("Save balances", type="primary"):
            def save(s):
                for lt_id, (a, cf, a0, c0) in new.items():
                    if (a, cf) != (a0, c0):
                        admin.update_balance(s, actor, emp_id, lt_id, year, Decimal(str(a)), Decimal(str(cf)))
            ok, _ = ui.run_action(save)
            if ok:
                st.session_state["flash"] = "Balances updated and the employee was notified."
                st.rerun()

    ui.section("Year roll-over")
    st.caption("Creates missing balances for every active employee at the leave type's allowance, "
               "carrying forward unused days (up to each type's limit) from the previous year.")
    if st.button(f"Allocate balances for {year}"):
        ok, n = ui.run_action(lambda s: admin.allocate_year(s, actor, year))
        if ok:
            st.success(f"{n} balance record(s) created.") if n else st.info("All balances already exist for this year.")

    ui.section(f"Organization balances {year}")
    with session_scope() as s:
        bal = mt.balance_df(s, year)
    if not bal.empty:
        summary = bal.groupby(["department", "leave_type"])[["total", "used", "pending", "available"]].sum().reset_index()
        summary.columns = ["Department", "Leave type", "Entitled", "Used", "Pending", "Available"]
        st.dataframe(summary, hide_index=True, width="stretch")
