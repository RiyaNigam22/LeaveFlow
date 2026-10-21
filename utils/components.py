"""Reusable Streamlit components that need data access (request tables / detail panel)."""
import pandas as pd
import streamlit as st

from database.connection import session_scope
from database.models import LeaveRequest
from services import leave_service
from utils import ui
from utils.dates import fmt_date, fmt_dt
from workflows.engine import Actor
from workflows.states import STAGE_LABEL, Stage


def format_requests(df: pd.DataFrame, show_employee: bool = False) -> pd.DataFrame:
    """Turn a requests_df into a presentation table (status labels, formatted dates)."""
    out = pd.DataFrame({"ID": df["request_id"]})
    if show_employee:
        out["Employee"], out["Department"] = df["employee"], df["department"]
    out["Leave type"] = df["leave_type"]
    out["From"] = df["start_date"].dt.strftime("%d %b %Y")
    out["To"] = df["end_date"].dt.strftime("%d %b %Y")
    out["Days"] = df["working_days"]
    out["Status"] = df["status"].map(ui.status_label)
    out["Submitted"] = ui.fmt_local(df["submitted_at"], "%d %b %Y")
    return out.reset_index(drop=True)


def request_detail(actor: Actor, request_id: int, key: str, allow_cancel: bool = False) -> None:
    """Details of one request: summary, approval timeline, document download and (optionally) cancel."""
    cancelled = False
    with session_scope() as session:
        req: LeaveRequest | None = leave_service.get_request(session, request_id)
        if req is None or not leave_service.can_view(session, actor, req):
            st.warning("You do not have access to this request.")
            return
        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown(f"**{req.leave_type.name}** &nbsp; {ui.status_badge(req.status)}", unsafe_allow_html=True)
            st.write(f"{req.employee.full_name} · {req.employee.department.name}")
            st.write(f"{fmt_date(req.start_date)} → {fmt_date(req.end_date)} · **{req.working_days}** working day(s)")
            if req.reason:
                st.caption(f"Reason: {req.reason}")
            if req.decision_reason and req.status in ("REJECTED", "CANCELLED"):
                st.warning(f"Decision note: {req.decision_reason}")
        with c2:
            st.caption(f"Submitted: {fmt_dt(req.submitted_at)}")
            st.caption(f"Decided: {fmt_dt(req.decided_at)}")
            if req.document_name:
                st.download_button(f"Download {req.document_name}", req.document_content or b"",
                                   file_name=req.document_name, key=f"{key}_doc")
        rows = [{"Stage": STAGE_LABEL[Stage(s.stage)],
                 "Approver": s.approver.full_name if s.approver else "HR team",
                 "Status": ui.status_label(s.status), "Activated": fmt_dt(s.activated_at),
                 "Decided": fmt_dt(s.decided_at), "Comments": s.comments or ""} for s in req.steps]
        if rows:
            st.markdown("**Approval workflow**")
            ui.show_table(pd.DataFrame(rows), "Status")
        else:
            st.caption("No approval steps – this request did not require approval.")
        if allow_cancel and leave_service.can_cancel(actor, req):
            if st.button("Cancel this request", key=f"{key}_cancel", type="secondary"):
                cancelled = True
    if cancelled:
        ok, _ = ui.run_action(lambda s: leave_service.cancel_request(s, actor, request_id),
                              "Your request has been cancelled.")
        if ok:
            st.rerun()


def request_picker(df: pd.DataFrame, key: str, label: str = "Select a request to view details") -> int | None:
    if df.empty:
        return None
    options = df["request_id"].tolist()
    labels = {r.request_id: f"#{r.request_id} · {r.leave_type} · {r.start_date:%d %b %Y} → {r.end_date:%d %b %Y}"
                            + (f" · {r.employee}" if "employee" in df else "") for r in df.itertuples()}
    return st.selectbox(label, options, format_func=labels.get, key=key, index=None, placeholder="Choose a request…")
