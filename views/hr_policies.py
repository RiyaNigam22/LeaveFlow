from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select

import config
from auth.session import require_role
from database.connection import session_scope
from database.models import ApprovalRule, Holiday, LeaveType
from services import admin_service as admin, rules_service
from utils import ui
from utils.dates import today_local
from workflows.engine import Actor
from workflows.states import STAGE_LABEL, STAGE_ORDER, parse_stages

user = require_role(config.ROLE_HR)
actor = Actor.from_session(user)
ui.page_header("Leave Policies", "Leave types, holidays and approval rules – all configuration lives in the database")

with ui.guard():
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    tab_t, tab_h, tab_r = st.tabs(["Leave types", "Holidays", "Approval rules & settings"])

    with tab_t:
        with session_scope() as s:
            types = {t.id: t for t in s.scalars(select(LeaveType).order_by(LeaveType.name))}
            rows = [{"Code": t.code, "Name": t.name, "Allowance": float(t.annual_allowance), "Tracks balance": t.tracks_balance,
                     "Needs approval": t.requires_approval, "Needs document": t.requires_document,
                     "Doc if > days": t.document_threshold_days, "Carry forward": t.can_carry_forward,
                     "Max consecutive": t.max_consecutive_days, "Active": t.is_active} for t in types.values()]
            vals = {i: dict(code=t.code, name=t.name, description=t.description or "", allowance=float(t.annual_allowance),
                            tracks=t.tracks_balance, approval=t.requires_approval, doc=t.requires_document, thr=t.document_threshold_days,
                            docd=t.document_description, carry=t.can_carry_forward, limit=float(t.carry_forward_limit or 0),
                            maxd=t.max_consecutive_days or 0, active=t.is_active) for i, t in types.items()}
        ui.show_table(pd.DataFrame(rows))
        pick = st.selectbox("Edit leave type", [None] + list(types), format_func=lambda i: "➕ New leave type" if i is None else types[i].name)
        v = vals.get(pick, dict(code="", name="", description="", allowance=0.0, tracks=True, approval=True, doc=False, thr=0,
                                docd="Supporting documentation", carry=False, limit=0.0, maxd=0, active=True))
        with st.form(f"lt_{pick}"):
            c = st.columns(3)
            code, name, desc = c[0].text_input("Code", v["code"]), c[1].text_input("Name", v["name"]), c[2].text_input("Description", v["description"])
            c = st.columns(4)
            allow = c[0].number_input("Annual allowance (days)", 0.0, 365.0, v["allowance"], 0.5)
            maxd = c[1].number_input("Max consecutive working days (0 = no limit)", 0, 365, v["maxd"])
            tracks, approval = c[2].checkbox("Tracks balance", v["tracks"]), c[3].checkbox("Requires approval", v["approval"])
            c = st.columns(4)
            doc = c[0].checkbox("Requires document", v["doc"])
            thr = c[1].number_input("Document needed above (working days)", 0, 365, v["thr"])
            docd = c[2].text_input("Document wording", v["docd"])
            active = c[3].checkbox("Active", v["active"])
            c = st.columns(2)
            carry, limit = c[0].checkbox("Can carry forward", v["carry"]), c[1].number_input("Carry-forward limit (days)", 0.0, 365.0, v["limit"], 0.5)
            if st.form_submit_button("Save leave type", type="primary"):
                ok, _ = ui.run_action(lambda s: admin.save_leave_type(s, actor, dict(
                    code=code, name=name, description=desc or None, annual_allowance=Decimal(str(allow)), tracks_balance=tracks,
                    requires_approval=approval, requires_document=doc, document_threshold_days=int(thr), document_description=docd,
                    can_carry_forward=carry, carry_forward_limit=Decimal(str(limit)), max_consecutive_days=int(maxd) or None,
                    is_active=active), pick))
                if ok:
                    st.session_state["flash"] = "Leave type saved."
                    st.rerun()

    with tab_h:
        year = st.selectbox("Year", [today_local().year + 1, today_local().year, today_local().year - 1], index=1)
        with session_scope() as s:
            hols = list(s.scalars(select(Holiday).where(Holiday.holiday_date >= date(year, 1, 1),
                                                        Holiday.holiday_date <= date(year, 12, 31)).order_by(Holiday.holiday_date)))
            hrows = [{"Date": h.holiday_date.strftime("%a %d %b %Y"), "Holiday": h.name, "Active": h.is_active} for h in hols]
            hmap = {h.id: (h.holiday_date, h.name, h.is_active) for h in hols}
        ui.show_table(pd.DataFrame(hrows))
        pick = st.selectbox("Edit holiday", [None] + list(hmap), format_func=lambda i: "➕ New holiday" if i is None else f"{hmap[i][0]:%d %b} · {hmap[i][1]}")
        hv = hmap.get(pick, (date(year, 1, 1), "", True))
        with st.form(f"hol_{pick}"):
            c = st.columns(3)
            hd, hn, ha = c[0].date_input("Date", hv[0], format="DD/MM/YYYY"), c[1].text_input("Name", hv[1]), c[2].checkbox("Active", hv[2])
            b1, b2 = st.columns([1, 1])
            save = b1.form_submit_button("Save holiday", type="primary")
            delete = b2.form_submit_button("Delete holiday", disabled=pick is None)
            if save:
                ok, _ = ui.run_action(lambda s: admin.save_holiday(s, actor, hd, hn, ha, pick))
                if ok:
                    st.session_state["flash"] = "Holiday saved."
                    st.rerun()
            if delete:
                ok, _ = ui.run_action(lambda s: admin.delete_holiday(s, actor, pick))
                if ok:
                    st.session_state["flash"] = "Holiday deleted."
                    st.rerun()

    with tab_r:
        st.markdown("A request needing **more than** *N* working days uses the rule with the highest matching threshold.")
        with session_scope() as s:
            rules = [(r.id, r.min_days, parse_stages(r.stages), r.description) for r in s.scalars(select(ApprovalRule).order_by(ApprovalRule.min_days))]
            settings = {k: rules_service.get_setting(s, k) for k in rules_service.DEFAULT_SETTINGS}
        stage_names = {st_.value: STAGE_LABEL[st_] for st_ in STAGE_ORDER}
        for rid, min_days, stages, desc in rules:
            with st.expander(f"More than {min_days} working day(s) → " + " + ".join(STAGE_LABEL[x] for x in stages)):
                with st.form(f"rule_{rid}"):
                    c = st.columns([1, 3])
                    md = c[0].number_input("Threshold (days)", 0, 365, min_days)
                    chosen = c[1].multiselect("Approval stages", list(stage_names), [x.value for x in stages], format_func=stage_names.get)
                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("Save rule", type="primary"):
                        ok, _ = ui.run_action(lambda s: admin.save_approval_rule(s, actor, md, chosen, rid, desc))
                        if ok:
                            st.session_state["flash"] = "Approval rule saved."
                            st.rerun()
                    if b2.form_submit_button("Delete rule", disabled=min_days == 0):
                        ok, _ = ui.run_action(lambda s: admin.delete_approval_rule(s, actor, rid))
                        if ok:
                            st.session_state["flash"] = "Approval rule deleted."
                            st.rerun()
        with st.expander("➕ Add approval rule"):
            with st.form("rule_new", clear_on_submit=True):
                c = st.columns([1, 3])
                md = c[0].number_input("Threshold (days)", 0, 365, 14)
                chosen = c[1].multiselect("Approval stages", list(stage_names), ["MANAGER", "HR"], format_func=stage_names.get)
                if st.form_submit_button("Add rule", type="primary"):
                    ok, _ = ui.run_action(lambda s: admin.save_approval_rule(s, actor, md, chosen))
                    if ok:
                        st.session_state["flash"] = "Approval rule added."
                        st.rerun()
        ui.section("System settings")
        with st.form("settings"):
            vals = {}
            for key, (_d, label) in rules_service.DEFAULT_SETTINGS.items():
                vals[key] = st.text_input(f"{key} – {label}", settings[key])
            if st.form_submit_button("Save settings", type="primary"):
                def save_all(s):
                    for k, val in vals.items():
                        if val != settings[k]:
                            admin.save_setting(s, actor, k, val)
                ok, _ = ui.run_action(save_all)
                if ok:
                    st.session_state["flash"] = "Settings saved."
                    st.rerun()
