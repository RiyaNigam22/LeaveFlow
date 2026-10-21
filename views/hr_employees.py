import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import joinedload

import config
from auth.session import require_role
from database.connection import session_scope
from database.models import Department, Employee
from services import admin_service as admin
from utils import ui
from utils.dates import today_local
from workflows.engine import Actor

user = require_role(config.ROLE_HR)
actor = Actor.from_session(user)
ui.page_header("Employees & Departments", "Manage the people and organization structure")
ROLE_LABEL = {config.ROLE_EMPLOYEE: "Employee", config.ROLE_MANAGER: "Manager", config.ROLE_HR: "HR / Admin"}

with ui.guard():
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    with session_scope() as s:
        emps = list(s.scalars(select(Employee).options(joinedload(Employee.user), joinedload(Employee.department),
                                                       joinedload(Employee.manager)).order_by(Employee.employee_code)).unique())
        depts = list(s.scalars(select(Department).order_by(Department.name)))
        e_rows = [{"Code": e.employee_code, "Name": e.full_name, "Email": e.email, "Department": e.department.name,
                   "Title": e.job_title or "", "Manager": e.manager.full_name if e.manager else "—",
                   "Role": ROLE_LABEL[e.user.role.name], "Username": e.user.username,
                   "Active": "Yes" if e.is_active else "No"} for e in emps]
        dept_opts = {d.id: d.name for d in depts}
        mgr_opts = {None: "— none —", **{e.id: e.full_name for e in emps if e.is_active and e.user.role.name in (config.ROLE_MANAGER, config.ROLE_HR)}}
        emp_opts = {e.id: f"{e.employee_code} · {e.full_name}" for e in emps}
        emp_data = {e.id: dict(first=e.first_name, last=e.last_name, email=e.email, title=e.job_title or "", dept=e.department_id,
                               mgr=e.manager_id, hire=e.hire_date, active=e.is_active, role=e.user.role.name) for e in emps}
        dept_data = {d.id: (d.name, d.head_employee_id) for d in depts}
        next_code = admin.next_employee_code(s)

    tab_e, tab_d = st.tabs(["Employees", "Departments"])
    with tab_e:
        q = st.text_input("Search by name, code or department")
        df = pd.DataFrame(e_rows)
        if q:
            df = df[df.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(), axis=1)]
        ui.show_table(df, height=320)
        with st.expander("Add employee"):
            with st.form("add_emp", clear_on_submit=True):
                c = st.columns(3)
                first, last, email = c[0].text_input("First name"), c[1].text_input("Last name"), c[2].text_input("Email")
                c = st.columns(3)
                title, dept = c[0].text_input("Job title"), c[1].selectbox("Department", list(dept_opts), format_func=dept_opts.get)
                mgr = c[2].selectbox("Manager", list(mgr_opts), format_func=mgr_opts.get)
                c = st.columns(4)
                hire = c[0].date_input("Hire date", value=today_local())
                role = c[1].selectbox("Role", list(ROLE_LABEL), format_func=ROLE_LABEL.get)
                uname, pwd = c[2].text_input("Username"), c[3].text_input("Initial password", type="password")
                if st.form_submit_button("Create employee", type="primary"):
                    ok, _ = ui.run_action(lambda s: admin.create_employee(s, actor, dict(
                        first_name=first.strip(), last_name=last.strip(), email=email.strip(), job_title=title.strip() or None,
                        department_id=dept, manager_id=mgr, hire_date=hire, employee_code=next_code), uname, pwd, role))
                    if ok:
                        st.session_state["flash"] = f"Employee {first} {last} created."
                        st.rerun()
        with st.expander("Edit employee"):
            eid = st.selectbox("Employee", list(emp_opts), format_func=emp_opts.get, key="edit_emp")
            d = emp_data[eid]
            with st.form(f"edit_emp_{eid}"):
                c = st.columns(3)
                first, last, email = c[0].text_input("First name", d["first"]), c[1].text_input("Last name", d["last"]), c[2].text_input("Email", d["email"])
                c = st.columns(3)
                title = c[0].text_input("Job title", d["title"])
                dept = c[1].selectbox("Department", list(dept_opts), list(dept_opts).index(d["dept"]), format_func=dept_opts.get)
                mgr = c[2].selectbox("Manager", list(mgr_opts), list(mgr_opts).index(d["mgr"]) if d["mgr"] in mgr_opts else 0, format_func=mgr_opts.get)
                c = st.columns(2)
                role = c[0].selectbox("Role", list(ROLE_LABEL), list(ROLE_LABEL).index(d["role"]), format_func=ROLE_LABEL.get)
                active = c[1].toggle("Active", d["active"])
                if st.form_submit_button("Save changes", type="primary"):
                    ok, _ = ui.run_action(lambda s: admin.update_employee(s, actor, eid, dict(
                        first_name=first.strip(), last_name=last.strip(), email=email.strip(), job_title=title.strip() or None,
                        department_id=dept, manager_id=mgr, is_active=active), role))
                    if ok:
                        st.session_state["flash"] = "Employee updated."
                        st.rerun()
    with tab_d:
        ui.show_table(pd.DataFrame([{"Department": n, "Head": emp_opts.get(h, "—").split("· ")[-1],
                                     "Employees": sum(1 for e in emp_data.values() if e["dept"] == i and e["active"])}
                                    for i, (n, h) in dept_data.items()]))
        heads = {k: v for k, v in mgr_opts.items()}
        with st.expander("Add department"):
            with st.form("add_dept", clear_on_submit=True):
                name, head = st.text_input("Department name"), st.selectbox("Department head", list(heads), format_func=heads.get)
                if st.form_submit_button("Create department", type="primary"):
                    ok, _ = ui.run_action(lambda s: admin.save_department(s, actor, name, head))
                    if ok:
                        st.session_state["flash"] = "Department created."
                        st.rerun()
        with st.expander("Edit department"):
            did = st.selectbox("Department", list(dept_opts), format_func=dept_opts.get, key="edit_dept")
            with st.form(f"edit_dept_{did}"):
                name = st.text_input("Department name", dept_data[did][0])
                cur = dept_data[did][1]
                head = st.selectbox("Department head", list(heads), list(heads).index(cur) if cur in heads else 0, format_func=heads.get)
                if st.form_submit_button("Save department", type="primary"):
                    ok, _ = ui.run_action(lambda s: admin.save_department(s, actor, name, head, did))
                    if ok:
                        st.session_state["flash"] = "Department updated."
                        st.rerun()
