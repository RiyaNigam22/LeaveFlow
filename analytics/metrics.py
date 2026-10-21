"""Business-intelligence layer: DataFrames and process metrics built from the relational data.

All functions are read-only. `employee_ids=None` means organisation-wide.
"""
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

import config
from database.models import (
    ApprovalStep, Department, Employee, LeaveBalance, LeaveRequest, LeaveType,
)
from services.rules_service import load_policy
from utils.dates import count_working_days, now_utc, today_local
from workflows.states import OPEN_STATUSES, PENDING_STATUSES, STAGE_LABEL, STAGE_ORDER, RequestStatus

REQUEST_COLS = ["request_id", "employee_id", "employee", "department_id", "department", "manager_id", "leave_type",
                "leave_code", "status", "start_date", "end_date", "working_days", "reason", "decision_reason",
                "submitted_at", "decided_at", "step_count", "has_document"]
STEP_COLS = ["step_id", "request_id", "employee_id", "employee", "department_id", "department", "stage", "step_status",
             "approver_employee_id", "approver", "activated_at", "decided_at", "request_status"]


def _hours(delta: pd.Series) -> pd.Series:
    return delta.dt.total_seconds() / 3600


def requests_df(session: Session, employee_ids: list[int] | None = None, year: int | None = None) -> pd.DataFrame:
    """One row per leave request (optionally restricted to employees and to a start-date year)."""
    emp = aliased(Employee)
    stmt = (select(
        LeaveRequest.id, emp.id, (emp.first_name + " " + emp.last_name), Department.id, Department.name, emp.manager_id,
        LeaveType.name, LeaveType.code, LeaveRequest.status, LeaveRequest.start_date, LeaveRequest.end_date,
        LeaveRequest.working_days, LeaveRequest.reason, LeaveRequest.decision_reason, LeaveRequest.submitted_at,
        LeaveRequest.decided_at,
        select(func.count(ApprovalStep.id)).where(
            ApprovalStep.request_id == LeaveRequest.id, ApprovalStep.status != "SKIPPED").scalar_subquery(),
        LeaveRequest.document_name.is_not(None))
        .join(emp, emp.id == LeaveRequest.employee_id)
        .join(Department, Department.id == emp.department_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc()))
    if employee_ids is not None:
        stmt = stmt.where(LeaveRequest.employee_id.in_(employee_ids or [-1]))
    if year:
        stmt = stmt.where(LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))
    df = pd.DataFrame([tuple(r) for r in session.execute(stmt)], columns=REQUEST_COLS)
    for col in ("submitted_at", "decided_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    # Turnaround is only meaningful for requests that went through at least one real approval step
    decided = df["decided_at"].notna() & (df["step_count"] > 0) & df["status"].isin(["APPROVED", "REJECTED"])
    df["approval_hours"] = _hours(df["decided_at"] - df["submitted_at"]).where(decided)
    return df


def steps_df(session: Session, employee_ids: list[int] | None = None, year: int | None = None) -> pd.DataFrame:
    """One row per approval step that actually took part in the workflow, with time spent in hours."""
    emp, appr = aliased(Employee), aliased(Employee)
    stmt = (select(
        ApprovalStep.id, LeaveRequest.id, emp.id, (emp.first_name + " " + emp.last_name), Department.id, Department.name,
        ApprovalStep.stage, ApprovalStep.status, ApprovalStep.approver_employee_id,
        (appr.first_name + " " + appr.last_name), ApprovalStep.activated_at, ApprovalStep.decided_at, LeaveRequest.status)
        .join(LeaveRequest, LeaveRequest.id == ApprovalStep.request_id)
        .join(emp, emp.id == LeaveRequest.employee_id)
        .join(Department, Department.id == emp.department_id)
        .outerjoin(appr, appr.id == ApprovalStep.approver_employee_id)
        .where(ApprovalStep.activated_at.is_not(None)))
    if employee_ids is not None:
        stmt = stmt.where(LeaveRequest.employee_id.in_(employee_ids or [-1]))
    if year:
        stmt = stmt.where(LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))
    df = pd.DataFrame([tuple(r) for r in session.execute(stmt)], columns=STEP_COLS)
    for col in ("activated_at", "decided_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["approver"] = df["approver"].fillna("HR team")
    is_pending = df["step_status"] == "PENDING"
    end = df["decided_at"].where(~is_pending, pd.Timestamp(now_utc()))
    df["hours"] = _hours(end - df["activated_at"])
    df["is_pending"] = is_pending
    df["is_decided"] = df["step_status"].isin(["APPROVED", "REJECTED"])
    return df


# --- process metrics ---------------------------------------------------------------------------

def approval_time_stats(req: pd.DataFrame) -> dict:
    h = req["approval_hours"].dropna()
    return {"avg_hours": float(h.mean()) if len(h) else 0.0, "median_hours": float(h.median()) if len(h) else 0.0,
            "count": int(len(h))}


def requests_by_stage(req: pd.DataFrame) -> pd.DataFrame:
    """Open requests grouped by the workflow stage they are currently waiting in."""
    order = [RequestStatus.MANAGER_PENDING, RequestStatus.HR_PENDING, RequestStatus.DEPARTMENT_HEAD_PENDING]
    counts = req["status"].value_counts()
    return pd.DataFrame({"Stage": [STAGE_LABEL[s] for s in STAGE_ORDER],
                         "Requests": [int(counts.get(o.value, 0)) for o in order]})


def stage_performance(steps: pd.DataFrame, sla_hours: int) -> pd.DataFrame:
    """Per stage: time spent, SLA breaches (completed late + currently overdue) and queue size."""
    rows = []
    for stage in STAGE_ORDER:
        s = steps[steps["stage"] == stage.value]
        done, pending = s[s["is_decided"]], s[s["is_pending"]]
        rows.append({
            "Stage": STAGE_LABEL[stage], "Decided": len(done),
            "Avg hours": round(done["hours"].mean(), 1) if len(done) else 0.0,
            "Median hours": round(done["hours"].median(), 1) if len(done) else 0.0,
            "Pending now": len(pending),
            "Avg pending age (h)": round(pending["hours"].mean(), 1) if len(pending) else 0.0,
            "SLA breaches": int((done["hours"] > sla_hours).sum() + (pending["hours"] > sla_hours).sum()),
            "Breach rate %": round(100 * ((done["hours"] > sla_hours).sum() + (pending["hours"] > sla_hours).sum())
                                   / max(len(s), 1), 1),
        })
    return pd.DataFrame(rows)


def bottleneck(perf: pd.DataFrame) -> dict | None:
    """The stage where requests spend the longest on average (decided + still-pending time)."""
    active = perf[(perf["Decided"] + perf["Pending now"]) > 0].copy()
    if active.empty:
        return None
    total = active["Decided"] + active["Pending now"]
    active["blend"] = (active["Avg hours"] * active["Decided"] + active["Avg pending age (h)"] * active["Pending now"]) / total
    top = active.sort_values("blend", ascending=False).iloc[0]
    return {"stage": top["Stage"], "avg_hours": round(float(top["blend"]), 1), "breaches": int(top["SLA breaches"])}


def approver_performance(steps: pd.DataFrame, sla_hours: int) -> pd.DataFrame:
    done = steps[steps["is_decided"]]
    if done.empty:
        return pd.DataFrame(columns=["Approver", "Decisions", "Avg hours", "Late (SLA)"])
    g = done.groupby("approver")["hours"]
    out = pd.DataFrame({"Decisions": g.size(), "Avg hours": g.mean().round(1),
                        "Late (SLA)": done.assign(late=done["hours"] > sla_hours).groupby("approver")["late"].sum()})
    return out.reset_index().rename(columns={"approver": "Approver"}).sort_values("Avg hours", ascending=False)


# --- leave analytics ----------------------------------------------------------------------------

def monthly_trend(req: pd.DataFrame, year: int) -> pd.DataFrame:
    months = pd.DataFrame({"month": range(1, 13)})
    submitted = req[req["submitted_at"].dt.year == year].groupby(req["submitted_at"].dt.month).size()
    approved = req[(req["status"] == "APPROVED") & (req["start_date"].dt.year == year)]
    days = approved.groupby(approved["start_date"].dt.month)["working_days"].sum()
    months["Month"] = [date(year, m, 1).strftime("%b") for m in months["month"]]
    months["Requests submitted"] = months["month"].map(submitted).fillna(0).astype(int)
    months["Approved leave days"] = months["month"].map(days).fillna(0).astype(int)
    return months[["Month", "Requests submitted", "Approved leave days"]]


def leave_by_type(req: pd.DataFrame, statuses=("APPROVED",), measure="working_days") -> pd.DataFrame:
    sub = req[req["status"].isin(statuses)]
    g = sub.groupby("leave_type")[measure].sum() if measure == "working_days" else sub.groupby("leave_type").size()
    return g.reset_index(name="Days" if measure == "working_days" else "Requests").rename(columns={"leave_type": "Leave type"})


def status_counts(req: pd.DataFrame) -> dict:
    c = req["status"].value_counts()
    pending = sum(int(c.get(s.value, 0)) for s in OPEN_STATUSES)
    return {"pending": pending, "approved": int(c.get("APPROVED", 0)), "rejected": int(c.get("REJECTED", 0)),
            "cancelled": int(c.get("CANCELLED", 0)), "total": int(len(req))}


def sick_leave_pct(req: pd.DataFrame) -> float:
    approved = req[req["status"] == "APPROVED"]
    total = approved["working_days"].sum()
    return round(100 * approved.loc[approved["leave_code"] == config.SICK_LEAVE_CODE, "working_days"].sum() / total, 1) if total else 0.0


def balance_df(session: Session, year: int, employee_ids: list[int] | None = None) -> pd.DataFrame:
    stmt = (select(Employee.id, Department.name, LeaveType.name, LeaveBalance.allocated, LeaveBalance.carried_forward,
                   LeaveBalance.used, LeaveBalance.pending)
            .join(LeaveBalance, LeaveBalance.employee_id == Employee.id).join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
            .join(Department, Department.id == Employee.department_id)
            .where(LeaveBalance.year == year, LeaveType.tracks_balance.is_(True), Employee.is_active.is_(True)))
    if employee_ids is not None:
        stmt = stmt.where(Employee.id.in_(employee_ids or [-1]))
    df = pd.DataFrame([tuple(r) for r in session.execute(stmt)],
                      columns=["employee_id", "department", "leave_type", "allocated", "carried", "used", "pending"])
    for c in ("allocated", "carried", "used", "pending"):
        df[c] = df[c].astype(float)
    df["total"] = df["allocated"] + df["carried"]
    df["available"] = df["total"] - df["used"] - df["pending"]
    return df


def utilization_pct(bal: pd.DataFrame) -> float:
    total = bal["total"].sum()
    return round(100 * bal["used"].sum() / total, 1) if total else 0.0


def department_summary(session: Session, year: int) -> pd.DataFrame:
    """Headcount, requests, absence days, utilisation and absenteeism per department."""
    policy = load_policy(session)
    today = today_local()
    window_end = min(today, date(year, 12, 31)) if year <= today.year else date(year, 1, 1)
    elapsed = max(count_working_days(date(year, 1, 1), window_end, policy.holidays, policy.weekend_days), 1)
    emp_rows = session.execute(select(Department.name, Employee.id).join(Employee, Employee.department_id == Department.id)
                               .where(Employee.is_active.is_(True))).all()
    headcount = pd.Series([r[0] for r in emp_rows]).value_counts()
    req = requests_df(session, year=year)
    bal = balance_df(session, year)
    out = []
    for dept, hc in headcount.items():
        r = req[req["department"] == dept]
        approved = r[(r["status"] == "APPROVED") & (~r["leave_code"].isin(config.NON_ABSENCE_CODES))]
        absence_days = 0
        for _, row in approved.iterrows():
            lo, hi = max(row["start_date"].date(), date(year, 1, 1)), min(row["end_date"].date(), window_end)
            absence_days += count_working_days(lo, hi, policy.holidays, policy.weekend_days) if lo <= hi else 0
        out.append({"Department": dept, "Headcount": int(hc), "Requests": int(len(r)),
                    "Approved days": int(r.loc[r["status"] == "APPROVED", "working_days"].sum()),
                    "Absence days (YTD)": int(absence_days),
                    "Absenteeism %": round(100 * absence_days / (hc * elapsed), 2),
                    "Utilization %": utilization_pct(bal[bal["department"] == dept])})
    return pd.DataFrame(out).sort_values("Department").reset_index(drop=True)


# --- calendar --------------------------------------------------------------------------------------

def calendar_df(req: pd.DataFrame, start: date, end: date, statuses=("APPROVED",) + tuple(s.value for s in PENDING_STATUSES)) -> pd.DataFrame:
    """Requests intersecting [start, end] suitable for a timeline."""
    c = req[req["status"].isin(statuses) & (req["start_date"].dt.date <= end) & (req["end_date"].dt.date >= start)].copy()
    return c.sort_values(["start_date", "employee"])


def overlap_days(cal: pd.DataFrame, policy_holidays=frozenset(), weekend_days=(5, 6), min_people: int = 2) -> pd.DataFrame:
    """Days on which at least `min_people` colleagues are away – candidates for coverage problems."""
    rows: dict[date, list[str]] = {}
    for _, r in cal.iterrows():
        d = r["start_date"].date()
        while d <= r["end_date"].date():
            if d.weekday() not in weekend_days and d not in policy_holidays:
                rows.setdefault(d, []).append(r["employee"])
            d = date.fromordinal(d.toordinal() + 1)
    data = [{"Date": d, "Away": len(set(n)), "Who": ", ".join(sorted(set(n)))} for d, n in sorted(rows.items())
            if len(set(n)) >= min_people]
    return pd.DataFrame(data, columns=["Date", "Away", "Who"])
