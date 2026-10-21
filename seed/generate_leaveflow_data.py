#!/usr/bin/env python3
"""
LeaveFlow synthetic dataset generator  (stress-test edition)
=============================================================
Produces CSV files whose columns match schema.sql 1:1, plus a flat
event_log.csv for process mining (PM4Py).

Everything is SIMULATED.  The company, people and numbers are fictional.

Usage
-----
    pip install bcrypt pandas
    python generate_leaveflow_data.py --out leaveflow_dataset --validate

Options: --seed, --employees, --requests
"""
import argparse
import bisect
import csv
import heapq
import json
import os
import random
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=IST)      # dataset snapshot time
SIM_START = date(2025, 1, 1)
SIM_END = NOW.date()
COMPANY = "Meridian Tech Pvt Ltd (fictional)"
DOMAIN = "meridiantech.example"
ROLE_NAMES = {1: "EMPLOYEE", 2: "MANAGER", 3: "HR"}
SLA_HOURS = 48
OVERRIDE_WAIT_H = 72

DEMO_PASSWORDS = {"employee": "Employee@123", "manager": "Manager@123", "hr": "HrAdmin@123"}

FIRST_M = ["Aarav", "Vihaan", "Arjun", "Rohit", "Karan", "Rahul", "Amit", "Sanjay", "Rajesh", "Suresh",
           "Manoj", "Deepak", "Nikhil", "Aditya", "Siddharth", "Varun", "Harsh", "Kunal", "Gaurav", "Ankit",
           "Mohit", "Tarun", "Yash", "Pranav", "Abhishek", "Ravi", "Sunil", "Vivek", "Anil", "Prakash",
           "Naveen", "Srinivas", "Ramesh", "Mahesh", "Girish", "Lokesh", "Dinesh", "Hemant", "Ishaan", "Kabir",
           "Manish", "Neeraj", "Omkar", "Pavan", "Sandeep", "Tushar", "Uday", "Vishal", "Zubin", "Imran",
           "Farhan", "Arif", "Salman", "Joseph", "Thomas", "Daniel", "Ashwin", "Balaji", "Chetan", "Dhruv"]
FIRST_F = ["Aditi", "Aishwarya", "Akanksha", "Anjali", "Bhavna", "Chitra", "Deepa", "Divya", "Esha", "Gayatri",
           "Harini", "Isha", "Jaya", "Kavya", "Lakshmi", "Meera", "Nandini", "Neha", "Pooja", "Prachi",
           "Radhika", "Riya", "Sakshi", "Shreya", "Sneha", "Sonal", "Swati", "Tanvi", "Uma", "Vaishnavi",
           "Varsha", "Yamini", "Zoya", "Anita", "Sunita", "Rekha", "Sangeeta", "Kiran", "Madhuri", "Nisha",
           "Rashmi", "Shweta", "Smita", "Preeti", "Ritu", "Seema", "Shalini", "Tara", "Usha", "Vidya",
           "Fatima", "Ayesha", "Nazia", "Mary", "Susan", "Priyanka", "Rupali", "Komal", "Mitali", "Ananya"]
LAST = ["Sharma", "Verma", "Gupta", "Agarwal", "Iyer", "Iyengar", "Nair", "Menon", "Pillai", "Rao", "Reddy",
        "Naidu", "Das", "Dutta", "Bose", "Banerjee", "Chatterjee", "Mukherjee", "Ghosh", "Sen", "Patel", "Shah",
        "Mehta", "Desai", "Joshi", "Kulkarni", "Deshmukh", "Patil", "Pawar", "Jadhav", "Kapoor", "Malhotra",
        "Khanna", "Chopra", "Bhatia", "Singh", "Kaur", "Gill", "Sandhu", "Yadav", "Mishra", "Tiwari", "Pandey",
        "Dubey", "Srivastava", "Saxena", "Jain", "Bansal", "Goyal", "Mittal", "Khan", "Ansari", "Siddiqui",
        "Shaikh", "Fernandes", "Pereira", "Thomas", "George", "Mathew", "Krishnan", "Subramanian", "Venkatesh",
        "Raman", "Natarajan", "Chandran", "Hegde", "Shetty", "Bhat", "Kamath", "Gowda", "Murthy", "Prasad",
        "Kumar", "Chauhan", "Rathore", "Thakur", "Bhatt", "Trivedi", "Parikh", "Mahajan", "Sinha", "Roy",
        "Basu", "Mondal", "Haldar", "Saha"]

DEPTS = [
    ("Engineering", 0.26, ["Software Engineer", "Senior Software Engineer", "QA Engineer", "DevOps Engineer",
                           "Data Engineer", "Site Reliability Engineer"], "Engineering Manager", "VP Engineering"),
    ("Product", 0.072, ["Product Manager", "Product Analyst", "UX Designer", "UX Researcher"],
     "Group Product Manager", "Head of Product"),
    ("Sales", 0.18, ["Account Executive", "Sales Development Rep", "Solutions Consultant", "Account Manager"],
     "Regional Sales Manager", "Head of Sales"),
    ("Marketing", 0.06, ["Content Strategist", "Performance Marketer", "Brand Designer", "Marketing Analyst"],
     "Marketing Manager", "Head of Marketing"),
    ("Finance", 0.06, ["Accountant", "Financial Analyst", "Payroll Specialist", "Auditor"],
     "Finance Manager", "Head of Finance"),
    ("Human Resources", 0.024, ["Recruiter", "HR Business Partner", "L&D Specialist", "Compensation Analyst",
                                "Talent Partner"], "HR Manager", "Head of HR"),
    ("Operations", 0.168, ["Operations Executive", "Logistics Coordinator", "Procurement Specialist",
                           "Facilities Executive"], "Operations Manager", "Head of Operations"),
    ("Customer Support", 0.176, ["Support Engineer", "Customer Success Associate", "Support Specialist",
                                 "Escalation Analyst"], "Support Team Lead", "Head of Customer Support"),
]

LT = {
    "AL": dict(id=1, name="Annual Leave", desc="Paid annual / earned leave", allow=18.0, tracks=True, approval=True,
               doc=False, doc_thr=0, doc_desc="Supporting documentation", carry=True, carry_lim=5.0, maxc=15),
    "CL": dict(id=2, name="Casual Leave", desc="Short personal leave for urgent matters", allow=8.0, tracks=True,
               approval=True, doc=False, doc_thr=0, doc_desc="Supporting documentation", carry=False,
               carry_lim=0.0, maxc=3),
    "SICK": dict(id=3, name="Sick Leave", desc="Leave for illness or injury", allow=10.0, tracks=True, approval=True,
                 doc=True, doc_thr=2, doc_desc="Medical certificate", carry=False, carry_lim=0.0, maxc=10),
    "ML": dict(id=4, name="Maternity Leave", desc="26 weeks (130 working days) as per Maternity Benefit Act",
               allow=130.0, tracks=True, approval=True, doc=True, doc_thr=0, doc_desc="Medical certificate",
               carry=False, carry_lim=0.0, maxc=130),
    "PL": dict(id=5, name="Paternity Leave", desc="Leave for new fathers", allow=5.0, tracks=True, approval=True,
               doc=False, doc_thr=0, doc_desc="Supporting documentation", carry=False, carry_lim=0.0, maxc=5),
    "CO": dict(id=6, name="Comp-off", desc="Compensatory off for working on a holiday / weekend", allow=6.0,
               tracks=True, approval=True, doc=False, doc_thr=0, doc_desc="Supporting documentation",
               carry=False, carry_lim=0.0, maxc=2),
    "WFH": dict(id=7, name="Work From Home", desc="Remote work day (not an absence); auto-approved", allow=0.0,
                tracks=False, approval=False, doc=False, doc_thr=0, doc_desc="Supporting documentation",
                carry=False, carry_lim=0.0, maxc=5),
    "LOP": dict(id=8, name="Unpaid Leave", desc="Loss-of-pay leave", allow=0.0, tracks=False, approval=True,
                doc=False, doc_thr=0, doc_desc="Supporting documentation", carry=False, carry_lim=0.0, maxc=30),
}
TRACKED = [c for c, v in LT.items() if v["tracks"]]
PLANNED = {"AL", "CL", "CO", "LOP"}
SLOT_CODES = ["AL", "CL", "SICK", "WFH", "CO", "LOP"]
SLOT_WEIGHTS = [31, 17, 17, 22, 6, 4]

HOLIDAYS = [
    (date(2025, 1, 1), "New Year's Day", True), (date(2025, 1, 14), "Makar Sankranti / Pongal", True),
    (date(2025, 1, 26), "Republic Day", True), (date(2025, 3, 14), "Holi", True),
    (date(2025, 3, 31), "Eid-ul-Fitr (tentative)", True), (date(2025, 4, 14), "Ambedkar Jayanti", True),
    (date(2025, 4, 18), "Good Friday", True), (date(2025, 5, 1), "Labour Day", True),
    (date(2025, 8, 15), "Independence Day", True), (date(2025, 8, 27), "Ganesh Chaturthi", True),
    (date(2025, 10, 2), "Gandhi Jayanti / Dussehra", True), (date(2025, 10, 21), "Diwali", True),
    (date(2025, 12, 25), "Christmas", True), (date(2025, 6, 6), "Company Foundation Day (discontinued)", False),
    (date(2026, 1, 1), "New Year's Day", True), (date(2026, 1, 14), "Makar Sankranti / Pongal", True),
    (date(2026, 1, 26), "Republic Day", True), (date(2026, 3, 4), "Holi", True),
    (date(2026, 3, 21), "Eid-ul-Fitr (tentative)", True), (date(2026, 4, 3), "Good Friday", True),
    (date(2026, 4, 14), "Ambedkar Jayanti", True), (date(2026, 5, 1), "Labour Day", True),
    (date(2026, 8, 15), "Independence Day", True), (date(2026, 9, 14), "Ganesh Chaturthi", True),
    (date(2026, 10, 2), "Gandhi Jayanti", True), (date(2026, 10, 20), "Dussehra", True),
    (date(2026, 11, 8), "Diwali", True), (date(2026, 12, 25), "Christmas", True),
]
ALLHOL = {h[0] for h in HOLIDAYS}
ACTIVE_HOL = {h[0] for h in HOLIDAYS if h[2]}

APPROVE_COMMENTS = ["Approved.", "Approved. Please document the handover.", "Looks fine, approved.",
                    "Approved - enjoy the time off.", "OK from my side."]
REJECT_REASONS = {
    "MANAGER": ["Insufficient team coverage during these dates.", "Critical release in progress - please reschedule.",
                "Month-end deliverables need your presence.", "Too many teammates already on leave."],
    "HR": ["Supporting documentation is incomplete.", "Request conflicts with leave policy limits.",
           "Leave balance verification failed."],
    "DEPARTMENT_HEAD": ["Department budget freeze - please defer.", "Handover plan missing for this duration.",
                        "Overlaps with a critical business period."],
}
OVERRIDE_APPROVE = "HR override: approved after the assigned approver exceeded the 72h response window."
OVERRIDE_REJECT = "HR override: rejected - conflicts with a critical business period."
OVERRIDE_CANCEL = ["HR override: leave revoked due to a business-critical requirement.",
                   "HR override: cancelled at the employee's request after approval.",
                   "HR override: cancelled - duplicate booking found after approval."]
EMP_CANCEL = ["Plans changed.", "Travel postponed.", "No longer required.", "Submitted by mistake."]
REASONS = {
    "AL": ["Family vacation", "Travel plans", "Personal work", "Visiting hometown", "Festival break"],
    "CL": ["Personal errand", "Family function", "Urgent personal work", "Home repair visit"],
    "SICK": ["Not well - medical rest", "Doctor's advice to rest", "Recovering from illness"],
    "ML": ["Maternity leave"], "PL": ["Paternity leave"], "CO": ["Comp-off for weekend work", "Comp-off for holiday duty"],
    "WFH": ["Working from home", "Home internet/electrician visit", "Remote work day", "Focus work day"],
    "LOP": ["Extended personal commitment", "Higher studies exam preparation", "Family relocation"],
}
STAGE_LABEL = {"MANAGER": "Manager", "HR": "HR", "DEPARTMENT_HEAD": "Dept Head"}
PENDING_OF = {"MANAGER": "MANAGER_PENDING", "HR": "HR_PENDING", "DEPARTMENT_HEAD": "DEPARTMENT_HEAD_PENDING"}

# --------------------------------------------------------------------------
# Global state
# --------------------------------------------------------------------------
r = random.Random(42)
WD_LIST, WD_IDX = [], {}
EMPS, DEPT_HEAD = [], {}
HR_POOL = []
FAC = {"MANAGER": {}, "HR": {}, "DEPARTMENT_HEAD": {}}
BAL = {}
OCC = defaultdict(list)
TEAMCOV = defaultdict(dict)
BALEV = defaultdict(list)
REQ, STEPS, AUD, NOT, EVT = [], [], [], [], []
HEAP, HEAPSEQ = [], [0]
STAT = defaultdict(int)


class E:
    __slots__ = ("id", "first", "last", "gender", "dept", "title", "mgr", "hire", "left", "role", "code", "email",
                 "username", "ml_ok", "pl_ok", "w", "special")


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------
def build_calendar():
    d = date(2024, 12, 1)
    while d <= date(2027, 12, 31):
        if d.weekday() < 5 and d not in ACTIVE_HOL:
            WD_IDX[d] = len(WD_LIST)
            WD_LIST.append(d)
        d += timedelta(days=1)


def next_wd(d):
    return WD_LIST[bisect.bisect_left(WD_LIST, d)]


def prev_wd(d):
    return WD_LIST[bisect.bisect_right(WD_LIST, d) - 1]


def ts_str(dt):
    return dt.astimezone(IST).replace(microsecond=0).isoformat(sep=" ")


def combine(d, hh, mm=0):
    return datetime.combine(d, dtime(hh, mm), tzinfo=IST)


def biz(dt, off=0.06):
    """Move a timestamp into business hours (Mon-Fri 09-19, not on a holiday)."""
    if r.random() < off:
        return dt
    while True:
        d = dt.date()
        if dt.weekday() >= 5 or d in ALLHOL:
            dt = combine(d + timedelta(days=1), 9) + timedelta(minutes=r.randint(0, 200))
        elif dt.hour >= 19:
            dt = combine(d + timedelta(days=1), 9) + timedelta(minutes=r.randint(0, 200))
        elif dt.hour < 9:
            dt = combine(d, 9) + timedelta(minutes=r.randint(0, 200))
        else:
            return dt


# --------------------------------------------------------------------------
# Organisation
# --------------------------------------------------------------------------
def build_org(N):
    used_names, used_user, used_email = set(), {"employee", "manager", "hr"}, set()
    reports = defaultdict(int)

    def rname(g):
        for _ in range(30):
            f = r.choice(FIRST_M if g == "M" else FIRST_F)
            l = r.choice(LAST)
            if (f, l) not in used_names:
                return f, l
        return f, l

    def mk(first, last, g, dept_id, title, mgr, hire, special=None, role=None):
        e = E()
        e.id = len(EMPS) + 1
        e.first, e.last, e.gender, e.dept, e.title, e.mgr = first, last, g, dept_id, title, mgr
        e.hire, e.left, e.role, e.special = hire, None, role, special
        e.code = f"EMP{e.id:05d}"
        used_names.add((first, last))
        base = f"{first}.{last}".lower()
        un, k = base, 2
        while un in used_user:
            un, k = f"{base}{k}", k + 1
        e.username = special or un
        used_user.add(e.username)
        em, k = base, 2
        while em in used_email:
            em, k = f"{base}{k}", k + 1
        used_email.add(em)
        e.email = f"{em}@{DOMAIN}"
        e.ml_ok = e.pl_ok = False
        e.w = 1.0
        EMPS.append(e)
        if mgr:
            reports[mgr] += 1
        return e

    def rnd_hire(lo, hi, recent_bias=False):
        span = (hi - lo).days
        x = r.betavariate(2.2, 1.3) if recent_bias else r.random()
        return lo + timedelta(days=int(x * span))

    sizes = [round(N * d[1]) for d in DEPTS]
    sizes[-1] += N - sum(sizes)
    ops_idx = [d[0] for d in DEPTS].index("Operations")
    sizes[ops_idx] -= 1
    ceo = mk("Rajiv", "Menon", "M", ops_idx + 1, "Chief Executive Officer", None, date(2012, 4, 2))
    hr_ops = []
    for di, (dname, _, ic_titles, mgr_title, head_title) in enumerate(DEPTS):
        dept_id, size = di + 1, sizes[di]
        if dname == "Engineering":
            head = mk("Vikram", "Nair", "M", dept_id, head_title, ceo.id, date(2017, 2, 6))
        elif dname == "Human Resources":
            head = mk("Priya", "Sharma", "F", dept_id, head_title, ceo.id, date(2016, 5, 9), special="hr", role=3)
        else:
            g = r.choice("MF")
            f, l = rname(g)
            head = mk(f, l, g, dept_id, head_title, ceo.id, rnd_hire(date(2013, 1, 1), date(2019, 12, 31)))
        DEPT_HEAD[dept_id] = head.id
        k = 4 if dname == "Human Resources" else max(2, round((size - 1) / 9))
        managers = []
        if dname == "Engineering":
            managers.append(mk("Karthik", "Rao", "M", dept_id, "Engineering Team Lead", head.id,
                               date(2019, 8, 19), special="manager"))
        while len(managers) < k:
            g = r.choice("MF")
            f, l = rname(g)
            managers.append(mk(f, l, g, dept_id, mgr_title, head.id, rnd_hire(date(2016, 1, 1), date(2022, 12, 31))))
        ic_n = size - 1 - k
        ics = []
        if dname == "Engineering":
            karthik = managers[0]
            others = managers[1:]
            ics.append(mk("Ananya", "Iyer", "F", dept_id, "Software Engineer", karthik.id, date(2022, 6, 13),
                          special="employee"))
            ics.append(mk("Rohan", "Das", "M", dept_id, "Software Engineer", karthik.id, date(2021, 3, 1)))
            for _ in range(2):
                g = r.choice("MF")
                f, l = rname(g)
                ics.append(mk(f, l, g, dept_id, r.choice(ic_titles), karthik.id,
                              rnd_hire(date(2017, 1, 1), date(2024, 12, 20), True)))
            rest = ic_n - 4
            pool = others
        else:
            rest, pool = ic_n, managers
        for i in range(rest):
            g = r.choice("MF")
            f, l = rname(g)
            m = pool[i % len(pool)]
            if r.random() < 0.14:
                hire = rnd_hire(date(2025, 1, 6), date(2026, 8, 15))
            else:
                hire = rnd_hire(date(2017, 1, 1), date(2024, 12, 20), True)
            if dname == "Human Resources" and i < 11:
                e = mk(f, l, g, dept_id, "HR Operations Executive", m.id, rnd_hire(date(2018, 1, 1), date(2023, 12, 31)),
                       role=3)
                hr_ops.append(e)
            else:
                e = mk(f, l, g, dept_id, r.choice(ic_titles), m.id, hire)
            ics.append(e)

    for e in EMPS:
        if e.role is None:
            e.role = 2 if reports[e.id] > 0 else 1

    for e in EMPS:
        if e.role == 1 and not e.special and r.random() < 0.03:
            lo = max(e.hire + timedelta(days=120), date(2025, 3, 1))
            hi = date(2026, 8, 31)
            if lo < hi:
                e.left = lo + timedelta(days=r.randint(0, (hi - lo).days))
    for e in EMPS:
        if e.left is None and not e.special:
            if e.gender == "F" and e.role == 1 and r.random() < 0.22:
                e.ml_ok = True
            if e.gender == "M" and e.role == 1 and r.random() < 0.22:
                e.pl_ok = True
        e.w = r.lognormvariate(0, 0.5) * (0.75 if e.role == 2 else 1.0)
        if e.title == "Chief Executive Officer":
            e.w = 0.15
        if e.special == "employee":
            e.w = 0.35

    mgr_ids = [e.id for e in EMPS if e.role == 2 and e.special != "manager"]
    slow_m = set(r.sample(mgr_ids, max(1, int(len(mgr_ids) * 0.08))))
    for e in EMPS:
        if reports[e.id] > 0:
            f = r.lognormvariate(0, 0.3)
            FAC["MANAGER"][e.id] = f * (r.uniform(4, 7) if e.id in slow_m else 1.0)
    heads = [h for h in DEPT_HEAD.values() if EMPS[h - 1].special is None and EMPS[h - 1].username != "vikram.nair"]
    slow_h = set(r.sample(heads, 2))
    for h in DEPT_HEAD.values():
        FAC["DEPARTMENT_HEAD"][h] = r.lognormvariate(0, 0.3) * (3.5 if h in slow_h else 1.0)
    HR_POOL.extend([e.id for e in EMPS if e.role == 3])
    slow_hr = set(r.sample([e.id for e in hr_ops], 2))
    for hid in HR_POOL:
        base = 0.8 if EMPS[hid - 1].special == "hr" else r.lognormvariate(0, 0.25)
        FAC["HR"][hid] = base * (4.5 if hid in slow_hr else 1.0)
    return reports, slow_m, slow_h, slow_hr


def pick_hr(exclude):
    for _ in range(50):
        h = r.choice(HR_POOL)
        if h not in exclude:
            return h
    return HR_POOL[0]


# --------------------------------------------------------------------------
# Leave-date generation and rule checks
# --------------------------------------------------------------------------
def pick_wd(code):
    if code == "AL":
        b = r.choices([(1, 2), (3, 5), (6, 7), (8, 12), (13, 15)], weights=[16, 36, 16, 24, 8])[0]
        return r.randint(*b)
    if code == "CL":
        return r.choices([1, 2, 3], weights=[60, 30, 10])[0]
    if code == "SICK":
        return r.choices([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], weights=[45, 25, 14, 6, 4, 1.5, 1.2, 1.2, 1, 1.1])[0]
    if code == "WFH":
        return r.choices([1, 2, 3, 4, 5], weights=[55, 25, 12, 4, 4])[0]
    if code == "CO":
        return r.choices([1, 2], weights=[80, 20])[0]
    if code == "LOP":
        return r.randint(1, 5) if r.random() < 0.7 else r.randint(6, 20)
    if code == "PL":
        return r.randint(3, 5)
    return r.randint(100, 130)


def gen_dates(code, ts, resub=None):
    d0 = ts.date()
    if resub:
        if r.random() < 0.6:
            start = next_wd(resub["start"] + timedelta(days=r.randint(7, 21)))
            wd = resub["wd"]
        else:
            start = next_wd(max(resub["start"], d0))
            wd = max(1, resub["wd"] - r.randint(1, 3))
    else:
        wd = pick_wd(code)
        if code == "SICK":
            start = prev_wd(d0 - timedelta(days=r.choice([0, 0, 0, 0, 1, 1, 2, 3])))
        elif code == "CL":
            start = next_wd(d0 + timedelta(days=r.choices([0, 1, 2, 3, 4, 5, 7], weights=[25, 20, 15, 12, 8, 8, 12])[0]))
        elif code == "WFH":
            start = next_wd(d0 + timedelta(days=r.choices([0, 1, 2, 3, 4, 5, 6, 7], weights=[15, 30, 20, 10, 8, 6, 6, 5])[0]))
        elif code == "CO":
            start = next_wd(d0 + timedelta(days=r.randint(1, 21)))
        elif code == "LOP":
            start = next_wd(d0 + timedelta(days=r.randint(3, 30)))
        elif code == "PL":
            start = next_wd(d0 + timedelta(days=r.randint(0, 45)))
        elif code == "ML":
            start = next_wd(d0 + timedelta(days=r.randint(15, 60)))
        else:
            start = None
            if ts.year == 2025 and ((ts.month == 11) or (ts.month == 12 and ts.day < 20)) and r.random() < 0.45:
                start = next_wd(date(2025, 12, r.randint(20, 29)))
            elif date(2025, 9, 15) <= d0 <= date(2025, 10, 15) and r.random() < 0.35:
                start = next_wd(date(2025, 10, r.randint(17, 27)))
            elif date(2026, 9, 10) <= d0 <= date(2026, 10, 7) and r.random() < 0.35:
                start = next_wd(date(2026, 11, r.randint(2, 12)))
            if start is None:
                start = next_wd(d0 + timedelta(days=min(150, int(r.expovariate(1 / 22)) + 4)))
            if start < d0:
                start = next_wd(d0)
    i = WD_IDX[start]
    end = WD_LIST[i + wd - 1]
    if end.year != start.year:
        end = prev_wd(date(start.year, 12, 31))
        wd = WD_IDX[end] - i + 1
    if code == "ML" and wd < 80:
        return None
    return start, end, wd


def overlaps(eid, start, end):
    for s, e in OCC[eid]:
        if start <= e and s <= end:
            return True
    return False


def team_key(emp):
    return emp.mgr if emp.mgr else DEPT_HEAD[emp.dept]


def coverage(emp, start, end):
    cnt = TEAMCOV.get(team_key(emp))
    if not cnt:
        return 0
    m, d, e = 0, start.toordinal(), end.toordinal()
    while d <= e:
        c = cnt.get(d, 0)
        if c > m:
            m = c
        d += 1
    return m


def available(b, t):
    used = pend = 0.0
    for x in b["res"]:
        if x["dec"] is None or x["dec"] > t:
            pend += x["wd"]
        elif x["out"] == "A" and (x["rev"] is None or x["rev"] > t):
            used += x["wd"]
    return b["alloc"] + b["carry"] - used - pend


def chain_for(wd):
    if wd > 7:
        return ["MANAGER", "HR", "DEPARTMENT_HEAD"]
    if wd > 2:
        return ["MANAGER", "HR"]
    return ["MANAGER"]


# --------------------------------------------------------------------------
# Approval simulation
# --------------------------------------------------------------------------
def stage_delay_h(stage, apr, activated, code):
    base = {"MANAGER": 4.0, "HR": 8.0, "DEPARTMENT_HEAD": 13.0}[stage]
    h = base * FAC[stage].get(apr, 1.0) * r.lognormvariate(0, 0.9)
    if code == "SICK":
        h *= 0.5
    d = activated.date()
    if stage == "HR":
        if d.day >= 26 or d.day <= 2:
            h *= 1.7
        if date(2025, 8, 11) <= d <= date(2025, 8, 22):
            h *= 3.0
    if d.month == 12:
        h *= 1.35
    if stage != "HR" and r.random() < 0.008:
        h += r.uniform(7, 30) * 24
    return min(h, 24 * 45)


def simulate(emp, code, ts, start, end, wd, cov):
    lt = LT[code]
    q = dict(emp=emp, code=code, start=start, end=end, wd=wd, sub=ts, steps=[], cancel_kind=None,
             apr_t=None, rev_t=None, final_t=None, final_actor=None, dreason=None, status=None, res_out=None,
             res_dec=None, last_ts=ts)
    if not lt["approval"]:
        q.update(status="APPROVED", final_t=ts, dreason="Auto-approved: leave type does not require approval",
                 apr_t=ts, final_actor=emp.id, auto=True)
        return q
    q["auto"] = False

    prior, steps = set(), []
    for i, stage in enumerate(chain_for(wd)):
        st = dict(id=None, order=i + 1, stage=stage, approver=None, status="WAITING", activated=None, decided=None,
                  actor=None, comment=None, kind=None, override=False)
        if stage == "MANAGER":
            st["approver"] = emp.mgr if emp.mgr else pick_hr({emp.id})
        elif stage == "HR":
            st["approver"] = pick_hr({emp.id} | prior)
        else:
            head = DEPT_HEAD[emp.dept]
            st["approver"] = head
            if head == emp.id:
                st.update(status="SKIPPED", kind="rule", approver=None,
                          comment="Skipped: requester is the department head")
            elif head in prior:
                st.update(status="SKIPPED", kind="rule",
                          comment="Skipped: department head already approved an earlier stage")
        if st["status"] != "SKIPPED":
            prior.add(st["approver"])
        steps.append(st)

    p_m = 0.02
    if code in PLANNED:
        p_m += 0.06 * min(cov, 3)
    if code == "AL" and wd > 10:
        p_m += 0.03
    if code == "AL" and ts.month == 12 and start.month == 12:
        p_m += 0.04
    p_rej = {"MANAGER": p_m, "HR": 0.02, "DEPARTMENT_HEAD": 0.05}
    t, outcome, rej_reason, rej_actor = ts, "APPROVED", None, None
    last_dec = ts
    for idx, st in enumerate(steps):
        if st["kind"] == "rule":
            continue
        st["activated"] = t
        nat = biz(t + timedelta(hours=stage_delay_h(st["stage"], st["approver"], t, code)))
        later = steps[idx + 1:]
        if (nat - t) > timedelta(hours=OVERRIDE_WAIT_H) and r.random() < 0.20:
            ot = biz(t + timedelta(hours=OVERRIDE_WAIT_H + r.uniform(1, 30)))
            if ot > nat:
                ot = nat
            actor = pick_hr({emp.id, st["approver"]})
            st.update(decided=ot, actor=actor, override=True)
            if r.random() < 0.9:
                st.update(status="APPROVED", comment=OVERRIDE_APPROVE)
                for s2 in later:
                    if s2["kind"] != "rule":
                        s2.update(status="SKIPPED", kind="override", comment="Skipped: request approved via HR override")
                last_dec = ot
                break
            st.update(status="REJECTED", comment=OVERRIDE_REJECT)
            outcome, rej_reason, rej_actor, last_dec = "REJECTED", OVERRIDE_REJECT, actor, ot
            for s2 in later:
                s2.update(status="CANCELLED", kind=None, comment=None)
            break
        if r.random() < p_rej[st["stage"]]:
            reason = r.choice(REJECT_REASONS[st["stage"]])
            st.update(status="REJECTED", decided=nat, actor=st["approver"], comment=reason)
            outcome, rej_reason, rej_actor, last_dec = "REJECTED", reason, st["approver"], nat
            for s2 in later:
                s2.update(status="CANCELLED", kind=None, comment=None)
            break
        st.update(status="APPROVED", decided=nat, actor=st["approver"],
                  comment=r.choice(APPROVE_COMMENTS) if r.random() < 0.3 else None)
        t = last_dec = nat
    q["steps"] = steps
    final_t = last_dec

    if r.random() < 0.045 and code in PLANNED | {"SICK", "PL", "ML"} and final_t > ts + timedelta(hours=2):
        ct = ts + timedelta(minutes=30) + (final_t - ts - timedelta(minutes=30)) * r.random()
        if ct <= NOW:
            for st in steps:
                if st["kind"] == "rule":
                    continue
                if st["decided"] and st["decided"] <= ct:
                    continue
                if st["activated"] and st["activated"] <= ct:
                    st.update(status="CANCELLED", decided=ct, actor=emp.id, comment="Cancelled by employee",
                              override=False)
                else:
                    st.update(status="CANCELLED", activated=None, decided=None, actor=None, comment=None,
                              override=False, kind=None)
            q.update(status="CANCELLED", cancel_kind="EMP", final_t=ct, final_actor=emp.id,
                     dreason="Cancelled by employee: " + r.choice(EMP_CANCEL), res_out="R", res_dec=ct)
            return q

    if final_t > NOW:
        cur = None
        for st in steps:
            if st["kind"] == "rule":
                continue
            if cur is None and st["decided"] is not None and st["decided"] > NOW:
                cur = st
                st.update(status="PENDING", decided=None, actor=None, comment=None, override=False)
            elif cur is not None and st is not cur:
                st.update(status="WAITING", activated=None, decided=None, actor=None, comment=None,
                          override=False, kind=None)
        if cur is None:
            cur = next(s for s in steps if s["status"] == "WAITING")
            cur.update(status="PENDING", activated=NOW)
        q.update(status=PENDING_OF[cur["stage"]], final_t=None, res_out=None, res_dec=None)
        return q

    if outcome == "REJECTED":
        q.update(status="REJECTED", final_t=final_t, final_actor=rej_actor, dreason=rej_reason, res_out="R",
                 res_dec=final_t)
        return q
    q.update(status="APPROVED", final_t=final_t, apr_t=final_t, final_actor=steps[-1]["actor"] if steps else emp.id,
             res_out="A", res_dec=final_t)
    for st in reversed(steps):
        if st["status"] == "APPROVED":
            q["final_actor"] = st["actor"]
            break
    q["apr_actor"] = q["final_actor"]
    if any(s["override"] for s in steps):
        q["dreason"] = OVERRIDE_APPROVE

    if code in PLANNED | {"PL", "ML"} and r.random() < (0.012 + (0.012 if wd >= 10 else 0)):
        start_dt = combine(start, 9)
        if start_dt > final_t + timedelta(hours=26):
            oc = biz(final_t + timedelta(hours=1) + (start_dt - final_t - timedelta(hours=2)) * r.random())
            if oc <= NOW and oc < start_dt:
                q.update(status="CANCELLED", cancel_kind="HR", rev_t=oc, final_t=oc,
                         final_actor=pick_hr({emp.id}), dreason=r.choice(OVERRIDE_CANCEL))
    return q


# --------------------------------------------------------------------------
# Request creation / emission
# --------------------------------------------------------------------------
def aud(ts, uid, action, etype, eid, old, new):
    AUD.append((ts, len(AUD), uid, action, etype, str(eid), old, new))


def notif(ts, uid, title, msg, cat, rid, pending_flag=False):
    NOT.append((ts, len(NOT), uid, title, msg, cat, rid, pending_flag))


def jd(o):
    return None if o is None else json.dumps(o, separators=(",", ":"))


def try_create(emp, code, ts, resub=None, draft=False):
    lt = LT[code]
    dates = gen_dates(code, ts, resub)
    if not dates:
        return None
    start, end, wd = dates
    d0 = ts.date()
    if ts.date() < emp.hire + timedelta(days=7) or start < emp.hire + timedelta(days=14):
        return None
    if emp.left and (end >= emp.left - timedelta(days=3) or d0 >= emp.left - timedelta(days=3)):
        return None
    if not draft:
        if start < d0 - timedelta(days=7) or start > d0 + timedelta(days=180) or wd < 1 or wd > lt["maxc"]:
            return None
        if overlaps(emp.id, start, end):
            return None
        bal = None
        if lt["tracks"]:
            bal = BAL.get((emp.id, lt["id"], start.year))
            if bal is None or wd > available(bal, ts):
                return None
    rid = len(REQ) + 1
    if draft:
        q = dict(emp=emp, code=code, start=start, end=end, wd=wd, sub=None, steps=[], status="DRAFT", auto=False,
                 cancel_kind=None, final_t=None, dreason=None, apr_t=None, rev_t=None, last_ts=ts, created=ts,
                 resub_of=None, res_out=None, res_dec=None)
        q["id"] = rid
        REQ.append(q)
        aud(ts, emp.id, "REQUEST_DRAFT_CREATED", "leave_request", rid, None, {"status": "DRAFT"})
        STAT["drafts"] += 1
        return q
    cov = coverage(emp, start, end) if code in PLANNED else 0
    q = simulate(emp, code, ts, start, end, wd, cov)
    q["id"] = rid
    q["created"] = ts
    q["resub_of"] = resub["id"] if resub else None
    REQ.append(q)
    for st in q["steps"]:
        st["id"] = len(STEPS) + 1
        st["request_id"] = rid
        STEPS.append(st)
    q["doc"] = None
    if (lt["doc"] and wd > lt["doc_thr"]):
        q["doc"] = f"{code.lower()}_{'medical_certificate' if code in ('SICK', 'ML') else 'document'}_{rid}.pdf"
    q["reason"] = r.choice(REASONS[code])

    st_ = q["status"]
    if st_ in ("APPROVED", "MANAGER_PENDING", "HR_PENDING", "DEPARTMENT_HEAD_PENDING"):
        OCC[emp.id].append((start, end))
        if code not in ("WFH",):
            cnt = TEAMCOV[team_key(emp)]
            for o in range(start.toordinal(), end.toordinal() + 1):
                cnt[o] = cnt.get(o, 0) + 1
    if lt["tracks"]:
        b = BAL[(emp.id, lt["id"], start.year)]
        b["res"].append(dict(wd=wd, dec=q["res_dec"], out=q["res_out"], rev=q["rev_t"]))
        k = (emp.id, lt["id"], start.year)
        BALEV[k].append((ts, len(BALEV[k]), "BALANCE_RESERVED", wd, 0, rid, emp.id))
        if q["res_dec"] is not None:
            if q["res_out"] == "A":
                BALEV[k].append((q["res_dec"], len(BALEV[k]), "BALANCE_COMMITTED", -wd, wd, rid, q["apr_actor"]))
            else:
                BALEV[k].append((q["res_dec"], len(BALEV[k]), "BALANCE_RELEASED", -wd, 0, rid, q["final_actor"]))
        if q["rev_t"] is not None:
            BALEV[k].append((q["rev_t"], len(BALEV[k]), "BALANCE_REVOKED", 0, -wd, rid, q["final_actor"]))
    emit(q)
    if st_ == "REJECTED" and r.random() < 0.30 and not resub:
        ts2 = biz(q["final_t"] + timedelta(days=r.uniform(1, 4)))
        if ts2 <= NOW:
            HEAPSEQ[0] += 1
            heapq.heappush(HEAP, (ts2, HEAPSEQ[0], "resub", dict(emp=emp, code=code, start=start, wd=wd, id=rid)))
    return q


def emit(q):
    emp, code, rid, lt = q["emp"], q["code"], q["id"], LT[q["code"]]
    ev = []
    last = q["sub"]

    def E_(ts, activity, actor, hrs=None):
        ev.append((ts, len(ev), activity, actor, hrs, (hrs is not None and hrs > SLA_HOURS)))

    desc = f"{lt['name']} {q['start']:%d %b %Y} - {q['end']:%d %b %Y} ({q['wd']} working day{'s' if q['wd'] != 1 else ''})"
    sub = q["sub"]
    E_(sub, "Submit Request", emp.id)
    aud(sub, emp.id, "REQUEST_SUBMITTED", "leave_request", rid, None,
        {"status": "APPROVED" if q["auto"] else "MANAGER_PENDING", "leave_type": code, "working_days": q["wd"]})
    notif(sub, emp.id, "Leave request submitted", f"Your request for {desc} was submitted.", "REQUEST_SUBMITTED", rid)
    if q["auto"]:
        t2 = sub + timedelta(seconds=1)
        E_(t2, "Auto Approve", None)
        E_(t2 + timedelta(seconds=1), "Request Approved", None)
        aud(t2, emp.id, "REQUEST_AUTO_APPROVED", "leave_request", rid, {"status": "SUBMITTED"}, {"status": "APPROVED"})
        notif(t2, emp.id, "Leave approved", f"{desc} was auto-approved.", "REQUEST_APPROVED", rid)
        q["last_ts"] = t2
        q["events"] = ev
        return
    steps = q["steps"]
    prev_done = sub
    for i, st in enumerate(steps):
        lab = STAGE_LABEL[st["stage"]]
        if st["kind"] == "rule":
            if i == 0 or steps[i - 1]["status"] == "APPROVED":
                E_(prev_done + timedelta(seconds=1), f"{lab} Review Skipped", None)
            continue
        if st["activated"] is not None:
            E_(st["activated"], f"{lab} Review Started", None)
            notif(st["activated"], st["approver"], "Approval needed",
                  f"{emp.first} {emp.last} requested {desc}. Your decision is needed ({lab} stage).",
                  "APPROVAL_REQUIRED", rid, st["status"] == "PENDING")
            last = max(last, st["activated"])
        if st["status"] in ("APPROVED", "REJECTED") and st["decided"]:
            hrs = round((st["decided"] - st["activated"]).total_seconds() / 3600, 2)
            if st["override"]:
                word = "Approved" if st["status"] == "APPROVED" else "Rejected"
                E_(st["decided"], f"HR Override {word}", st["actor"], hrs)
                aud(st["decided"], st["actor"], f"HR_OVERRIDE_{'APPROVE' if word == 'Approved' else 'REJECT'}",
                    "leave_request", rid, {"status": PENDING_OF[st["stage"]]},
                    {"status": st["status"], "reason": st["comment"]})
            else:
                E_(st["decided"], f"{lab} {'Approved' if st['status'] == 'APPROVED' else 'Rejected'}", st["actor"], hrs)
                aud(st["decided"], st["actor"], f"STEP_{st['status']}", "approval_step", st["id"],
                    {"status": "PENDING"}, {"status": st["status"], "stage": st["stage"]})
            prev_done = st["decided"]
            last = max(last, st["decided"])
            if st["status"] == "APPROVED" and any(s["activated"] is not None for s in steps[i + 1:]):
                notif(st["decided"], emp.id, "Request progressed",
                      f"{lab} stage approved: {desc}. Awaiting next approval.", "REQUEST_PROGRESS", rid)
        elif st["status"] == "CANCELLED" and st["decided"]:
            E_(st["decided"], "Employee Cancelled", emp.id, None)
    s = q["status"]
    if s in ("APPROVED", "REJECTED", "CANCELLED"):
        ft = q["final_t"]
        if q["cancel_kind"] == "EMP":
            prev = next((PENDING_OF[x["stage"]] for x in steps if x["status"] == "CANCELLED" and x["activated"]),
                        "MANAGER_PENDING")
            aud(ft, emp.id, "REQUEST_CANCELLED", "leave_request", rid, {"status": prev},
                {"status": "CANCELLED", "reason": q["dreason"]})
            E_(ft + timedelta(seconds=1), "Request Cancelled", None)
            notif(ft, emp.id, "Leave cancelled", f"You cancelled: {desc}.", "REQUEST_CANCELLED", rid)
            for x in steps:
                if x["status"] == "CANCELLED" and x["activated"]:
                    notif(ft, x["approver"], "Request withdrawn", f"{emp.first} {emp.last} withdrew: {desc}.",
                          "REQUEST_WITHDRAWN", rid)
            last = max(last, ft)
        elif q["cancel_kind"] == "HR":
            at, oc = q["apr_t"], q["rev_t"]
            if not any(x["override"] for x in steps):
                aud(at, q["apr_actor"], "REQUEST_APPROVED", "leave_request", rid,
                    {"status": PENDING_OF[[x for x in steps if x["status"] == "APPROVED"][-1]["stage"]]},
                    {"status": "APPROVED"})
            E_(at + timedelta(seconds=1), "Request Approved", None)
            notif(at, emp.id, "Leave approved", f"{desc} was approved.", "REQUEST_APPROVED", rid)
            aud(oc, q["final_actor"], "HR_OVERRIDE_CANCEL", "leave_request", rid, {"status": "APPROVED"},
                {"status": "CANCELLED", "reason": q["dreason"]})
            E_(oc, "HR Override Cancelled", q["final_actor"])
            E_(oc + timedelta(seconds=1), "Request Cancelled", None)
            notif(oc, emp.id, "Approved leave cancelled by HR", f"{desc} was cancelled. {q['dreason']}",
                  "REQUEST_CANCELLED", rid)
            last = max(last, oc)
        elif s == "APPROVED":
            if not any(x["override"] for x in steps):
                aud(ft, q["apr_actor"], "REQUEST_APPROVED", "leave_request", rid,
                    {"status": PENDING_OF[[x for x in steps if x["status"] == "APPROVED"][-1]["stage"]]},
                    {"status": "APPROVED"})
            E_(ft + timedelta(seconds=1), "Request Approved", None)
            notif(ft, emp.id, "Leave approved", f"{desc} was approved.", "REQUEST_APPROVED", rid)
            last = max(last, ft)
        elif s == "REJECTED":
            rs = [x for x in steps if x["status"] == "REJECTED"][0]
            if not rs["override"]:
                aud(ft, q["final_actor"], "REQUEST_REJECTED", "leave_request", rid,
                    {"status": PENDING_OF[rs["stage"]]}, {"status": "REJECTED", "reason": q["dreason"]})
            E_(ft + timedelta(seconds=1), "Request Rejected", None)
            notif(ft, emp.id, "Leave rejected", f"{desc} was rejected. Reason: {q['dreason']}", "REQUEST_REJECTED", rid)
            last = max(last, ft)
    q["last_ts"] = last
    q["events"] = ev


# --------------------------------------------------------------------------
# Scheduling of submission slots
# --------------------------------------------------------------------------
def build_slot_sampler():
    days, cum, tot = [], [], 0.0
    month_f = {1: .85, 2: .9, 3: 1.1, 4: 1.1, 5: 1.15, 6: 1.05, 7: .95, 8: .9, 9: 1.0, 10: 1.2, 11: 1.25, 12: 1.7}
    d = SIM_START
    while d <= SIM_END:
        w = month_f[d.month]
        if d.weekday() >= 5:
            w *= 0.08
        elif d.weekday() == 0:
            w *= 1.2
        if (d + timedelta(days=4)).month != d.month:
            w *= 1.45
        if d in ALLHOL:
            w *= 0.1
        if d == SIM_END:
            w *= 0.5
        tot += w
        days.append(d)
        cum.append(tot)
        d += timedelta(days=1)
    hours = list(range(7, 21))
    hw = [2, 5, 12, 16, 14, 8, 7, 12, 12, 10, 8, 5, 2, 1]
    hcum, t2 = [], 0
    for x in hw:
        t2 += x
        hcum.append(t2)

    def sample(lo=None, hi=None):
        for _ in range(100):
            if lo:
                d = lo + timedelta(days=r.randint(0, (hi - lo).days))
            else:
                d = days[bisect.bisect(cum, r.random() * tot)]
            hr = hours[bisect.bisect(hcum, r.random() * t2)]
            ts = combine(d, hr, r.randint(0, 59)) + timedelta(seconds=r.randint(0, 59))
            if ts <= NOW and d.weekday() < 5 or (lo is None and ts <= NOW):
                return ts
        return NOW - timedelta(hours=3)
    return sample


def run_slot(ts, forced, cum_w, ml_pool, pl_pool):
    if forced == "KR":
        k = next(e for e in EMPS if e.special == "manager")
        team = [e for e in EMPS if e.mgr == k.id]
        for _ in range(14):
            if try_create(r.choice(team), r.choice(["AL", "CL", "CO"]), ts):
                return
        return
    if forced is None and r.random() < 0.005:
        emp = EMPS[bisect.bisect(cum_w, r.random() * cum_w[-1])]
        try_create(emp, r.choice(["AL", "CL", "CO"]), ts, draft=True)
        return
    for _ in range(14):
        if forced == "ML":
            emp, code = r.choice(ml_pool), "ML"
        elif forced == "PL":
            emp, code = r.choice(pl_pool), "PL"
        else:
            emp = EMPS[bisect.bisect(cum_w, r.random() * cum_w[-1])]
            code = r.choices(SLOT_CODES, SLOT_WEIGHTS)[0]
        if try_create(emp, code, ts):
            return
    STAT["slots_failed"] += 1


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return len(rows) if hasattr(rows, "__len__") else None


def main():
    global r
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="leaveflow_dataset")
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--employees", type=int, default=2500)
    ap.add_argument("--requests", type=int, default=50000)
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    r = random.Random(a.seed)
    os.makedirs(a.out, exist_ok=True)
    build_calendar()

    try:
        import bcrypt
    except ImportError:
        sys.exit("Please run: pip install bcrypt")

    reports, slow_m, slow_h, slow_hr = build_org(a.employees)
    n_emp = len(EMPS)

    # ---- precompute dynamic passwords & hashes for all employees
    user_passwords = {}
    hashes = {}
    for e in EMPS:
        if e.special in DEMO_PASSWORDS:
            pw = DEMO_PASSWORDS[e.special]
        else:
            pw = f"{e.first.capitalize()}@{e.code}"
        user_passwords[e.id] = pw
        if pw not in hashes:
            hashes[pw] = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()

    # ---- balances
    for e in EMPS:
        for year in (2025, 2026):
            if e.hire.year > year or (e.left and e.left.year < year):
                continue
            for code in TRACKED:
                if (code == "ML" and e.gender != "F") or (code == "PL" and e.gender != "M"):
                    continue
                lt = LT[code]
                allow = lt["allow"]
                if code in ("AL", "CL", "SICK", "CO") and e.hire.year == year:
                    allow = max(0.5, round(allow * (13 - e.hire.month) / 12 * 2) / 2)
                carry = 0.0
                if lt["carry"] and e.hire < date(year, 1, 1):
                    carry = r.choice([0, 0, 0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5])
                created = combine(max(date(year, 1, 1), e.hire) if e.hire.year == year else date(year, 1, 1), 9)
                BAL[(e.id, lt["id"], year)] = dict(id=len(BAL) + 1, emp=e.id, lt=lt["id"], year=year, alloc=allow,
                                                   carry=float(carry), created=created, res=[])

    # ---- schedule slots
    sampler = build_slot_sampler()
    cum_w, tot = [], 0.0
    for e in EMPS:
        tot += e.w
        cum_w.append(tot)
    ml_pool = [e for e in EMPS if e.ml_ok]
    pl_pool = [e for e in EMPS if e.pl_ok]

    def push(ts, kind, payload):
        HEAPSEQ[0] += 1
        heapq.heappush(HEAP, (ts, HEAPSEQ[0], kind, payload))

    for _ in range(int(a.requests * 0.985)):
        push(sampler(), "slot", None)
    for _ in range(30):
        push(sampler(date(2025, 1, 6), date(2025, 5, 30)), "forced", "ML")
    for _ in range(10):
        push(sampler(date(2026, 1, 5), date(2026, 2, 27)), "forced", "ML")
    for _ in range(60):
        push(sampler(date(2025, 1, 6), date(2026, 9, 25)), "forced", "PL")
    for _ in range(6):
        push(NOW - timedelta(minutes=r.randint(20, 240)), "forced", "KR")

    while HEAP:
        ts, _, kind, payload = heapq.heappop(HEAP)
        if kind == "slot":
            run_slot(ts, None, cum_w, ml_pool, pl_pool)
        elif kind == "forced":
            run_slot(ts, payload, cum_w, ml_pool, pl_pool)
        else:
            for _ in range(3):
                if try_create(payload["emp"], payload["code"], ts, resub=payload):
                    STAT["resubmissions"] += 1
                    break

    # ---- balance audit replay + final balances
    for k, evs in BALEV.items():
        evs.sort()
        p = u = 0.0
        for ts, _, action, dp, du, rid, uid in evs:
            old = {"pending": p, "used": u}
            p, u = round(p + dp, 1), round(u + du, 1)
            assert p >= -1e-9 and u >= -1e-9, (k, action, p, u)
            aud(ts, uid, action, "leave_balance", BAL[k]["id"], old, {"pending": p, "used": u, "request_id": rid})
        BAL[k]["pending"], BAL[k]["used"], BAL[k]["last"] = p, u, evs[-1][0]

    # ---- security / admin audit noise
    hr_uid = next(e.id for e in EMPS if e.special == "hr")
    active_ids = [e.id for e in EMPS if not e.left]
    for h in HOLIDAYS:
        when = combine(date(2024, 12, 16) if h[0].year == 2025 else date(2025, 12, 8), 11) + timedelta(minutes=r.randint(0, 90))
        aud(when, hr_uid, "HOLIDAY_CREATED", "holiday", h[0].isoformat(), None, {"name": h[1], "is_active": h[2]})
    for e in EMPS:
        if e.hire >= SIM_START:
            when = combine(e.hire - timedelta(days=3), 11) + timedelta(minutes=r.randint(0, 120))
            aud(when, r.choice(HR_POOL), "EMPLOYEE_CREATED", "employee", e.id, None, {"employee_code": e.code})
    sd = build_slot_sampler()
    for _ in range(2000):
        uid = r.choice(active_ids)
        aud(sd(), uid, "LOGIN_FAILED", "user", uid, None, {"reason": "invalid_credentials"})
    for _ in range(150):
        uid = r.choice(active_ids)
        t0 = sd()
        for i in range(5):
            aud(t0 + timedelta(seconds=45 * i), uid, "LOGIN_FAILED", "user", uid, None, {"reason": "invalid_credentials"})
        aud(t0 + timedelta(seconds=200), uid, "ACCOUNT_LOCKED", "user", uid, None, {"locked_minutes": 15})
        aud(t0 + timedelta(minutes=r.randint(16, 40)), uid, "LOGIN_SUCCESS", "user", uid, None, None)

    # ---------------------------------------------------------------- write
    out = a.out
    P = lambda n: os.path.join(out, n)
    counts = {}
    created_dt = combine(date(2024, 12, 2), 9)
    counts["roles"] = write_csv(P("roles.csv"), ["id", "name", "description"],
                                [(1, "EMPLOYEE", "Own requests, history, notifications"),
                                 (2, "MANAGER", "Employee + approval queue and team views for own reports"),
                                 (3, "HR", "HR / Admin: organisation-wide views, master data, overrides, audit log")])
    counts["departments"] = write_csv(
        P("departments.csv"), ["id", "name", "head_employee_id", "created_at", "updated_at"],
        [(i + 1, d[0], DEPT_HEAD[i + 1], ts_str(created_dt), ts_str(created_dt)) for i, d in enumerate(DEPTS)])
    counts["employees"] = write_csv(
        P("employees.csv"),
        ["id", "employee_code", "first_name", "last_name", "email", "job_title", "department_id", "manager_id",
         "hire_date", "is_active", "created_at", "updated_at"],
        [(e.id, e.code, e.first, e.last, e.email, e.title, e.dept, e.mgr, e.hire.isoformat(),
          "false" if e.left else "true",
          ts_str(max(created_dt, combine(e.hire, 9))), ts_str(combine(e.left, 18) if e.left else max(created_dt, combine(e.hire, 9))))
         for e in EMPS])
    urows = []
    for e in EMPS:
        pw = user_passwords[e.id]
        if e.left:
            ll = combine(e.left - timedelta(days=r.randint(0, 3)), 10)
        else:
            days_back = r.randint(0, 2) if e.role != 1 else int(min(30, r.expovariate(1 / 6)))
            ll = NOW - timedelta(days=days_back, hours=r.randint(0, 20), minutes=r.randint(0, 59))
        urows.append((e.id, e.username, hashes[pw], e.role, e.id, "false" if e.left else "true", ts_str(ll), 0, None,
                      ts_str(max(created_dt, combine(e.hire, 9))), ts_str(ll)))
    counts["users"] = write_csv(
        P("users.csv"), ["id", "username", "password_hash", "role_id", "employee_id", "is_active", "last_login_at",
                         "failed_attempts", "locked_until", "created_at", "updated_at"], urows)

    # export user credentials cheat-sheet
    write_csv(
        P("user_credentials.csv"),
        ["employee_id", "full_name", "email", "username", "role", "password"],
        [(e.id, f"{e.first} {e.last}", e.email, e.username, ROLE_NAMES[e.role], user_passwords[e.id]) for e in EMPS]
    )

    counts["leave_types"] = write_csv(
        P("leave_types.csv"),
        ["id", "code", "name", "description", "annual_allowance", "tracks_balance", "requires_approval",
         "requires_document", "document_threshold_days", "document_description", "can_carry_forward",
         "carry_forward_limit", "max_consecutive_days", "is_active", "created_at", "updated_at"],
        [(v["id"], c, v["name"], v["desc"], v["allow"], str(v["tracks"]).lower(), str(v["approval"]).lower(),
          str(v["doc"]).lower(), v["doc_thr"], v["doc_desc"], str(v["carry"]).lower(), v["carry_lim"], v["maxc"],
          "true", ts_str(created_dt), ts_str(created_dt)) for c, v in LT.items()])
    counts["holidays"] = write_csv(
        P("holidays.csv"), ["id", "holiday_date", "name", "is_active", "created_at", "updated_at"],
        [(i + 1, h[0].isoformat(), h[1], str(h[2]).lower(), ts_str(created_dt), ts_str(created_dt))
         for i, h in enumerate(sorted(HOLIDAYS))])
    counts["approval_rules"] = write_csv(
        P("approval_rules.csv"), ["id", "min_days", "stages", "description", "created_at", "updated_at"],
        [(1, 0, "MANAGER", "More than 0 working days: Manager", ts_str(created_dt), ts_str(created_dt)),
         (2, 2, "MANAGER,HR", "More than 2 working days: Manager + HR", ts_str(created_dt), ts_str(created_dt)),
         (3, 7, "MANAGER,HR,DEPARTMENT_HEAD", "More than 7 working days: Manager + HR + Department Head",
          ts_str(created_dt), ts_str(created_dt))])
    counts["system_settings"] = write_csv(
        P("system_settings.csv"), ["key", "value", "description"],
        [("weekend_days", "5,6", "Weekend weekdays (Mon=0 ... Sun=6)"),
         ("max_backdate_days", "7", "Maximum days in the past a request may start"),
         ("max_advance_days", "180", "Maximum days in advance a request may start"),
         ("sla_hours_per_stage", str(SLA_HOURS), "Target decision time per approval stage (wall-clock hours)"),
         ("override_window_hours", str(OVERRIDE_WAIT_H), "Informational: HR may override after this wait"),
         ("company_name", COMPANY, "Display name"), ("timezone", "Asia/Kolkata", "Application timezone")])
    brows = []
    for k, b in sorted(BAL.items(), key=lambda kv: kv[1]["id"]):
        last = b.get("last", b["created"])
        brows.append((b["id"], b["emp"], b["lt"], b["year"], b["alloc"], b["carry"], b.get("used", 0.0),
                      b.get("pending", 0.0), ts_str(b["created"]), ts_str(max(last, b["created"]))))
    counts["leave_balances"] = write_csv(
        P("leave_balances.csv"),
        ["id", "employee_id", "leave_type_id", "year", "allocated", "carried_forward", "used", "pending",
         "created_at", "updated_at"], brows)
    rrows = []
    for q in REQ:
        s = q["status"]
        dec = q["final_t"] if s in ("APPROVED", "REJECTED", "CANCELLED") else None
        rrows.append((q["id"], q["emp"].id, LT[q["code"]]["id"], q["start"].isoformat(), q["end"].isoformat(), q["wd"],
                      r_reason(q), q.get("doc"), None, s, ts_str(q["sub"]) if q["sub"] else None,
                      ts_str(dec) if dec else None, q["dreason"], ts_str(q["created"]),
                      ts_str(max(q["last_ts"], q["created"]))))
    counts["leave_requests"] = write_csv(
        P("leave_requests.csv"),
        ["id", "employee_id", "leave_type_id", "start_date", "end_date", "working_days", "reason", "document_name",
         "document_content", "status", "submitted_at", "decided_at", "decision_reason", "created_at", "updated_at"],
        rrows)
    srows = []
    reqmap = {q["id"]: q for q in REQ}
    for st in STEPS:
        q = reqmap[st["request_id"]]
        srows.append((st["id"], st["request_id"], st["order"], st["stage"], st["approver"], st["status"],
                      ts_str(st["activated"]) if st["activated"] else None,
                      ts_str(st["decided"]) if st["decided"] else None, st["actor"], st["comment"],
                      ts_str(q["sub"]), ts_str(st["decided"] or st["activated"] or q["sub"])))
    counts["approval_steps"] = write_csv(
        P("approval_steps.csv"),
        ["id", "request_id", "step_order", "stage", "approver_employee_id", "status", "activated_at", "decided_at",
         "acted_by_user_id", "comments", "created_at", "updated_at"], srows)
    AUD.sort(key=lambda x: (x[0], x[1]))
    counts["audit_logs"] = write_csv(
        P("audit_logs.csv"),
        ["id", "user_id", "action", "entity_type", "entity_id", "old_value", "new_value", "created_at"],
        [(i + 1, x[2], x[3], x[4], x[5], jd(x[6]), jd(x[7]), ts_str(x[0])) for i, x in enumerate(AUD)])
    NOT.sort(key=lambda x: (x[0], x[1]))
    nrows = []
    for i, x in enumerate(NOT):
        age_days = (NOW - x[0]).days
        if x[7]:
            read = r.random() < 0.30
        else:
            read = r.random() < (0.97 if age_days > 14 else 0.6)
        nrows.append((i + 1, x[2], x[3], x[4], x[5], x[6], "true" if read else "false", ts_str(x[0])))
    counts["notifications"] = write_csv(
        P("notifications.csv"),
        ["id", "user_id", "title", "message", "category", "request_id", "is_read", "created_at"], nrows)
    erows = []
    for q in REQ:
        if q["status"] == "DRAFT":
            continue
        e = q["emp"]
        evs = sorted(q["events"], key=lambda x: (x[0], x[1]))
        for ts, _, act, actor, hrs, br in evs:
            ae = EMPS[actor - 1] if actor else None
            erows.append((q["id"], act, ts_str(ts), ae.code if ae else "SYSTEM",
                          ROLE_NAMES[ae.role] if ae else "SYSTEM", q["code"], DEPTS[e.dept - 1][0], q["wd"],
                          q["status"], hrs if hrs is not None else None,
                          ("true" if br else "false") if hrs is not None else None, q.get("resub_of")))
    counts["event_log"] = write_csv(
        P("event_log.csv"),
        ["case_id", "activity", "timestamp", "resource", "resource_role", "leave_type", "department", "working_days",
         "case_status", "stage_hours", "sla_breach", "resubmission_of_request_id"], erows)

    print("rows written:")
    for k, v in counts.items():
        print(f"  {k:16s}{v:>9,}")
    print("total rows:", f"{sum(counts.values()):,}")
    print("extras:", dict(STAT))
    info = dict(counts=counts, slow_managers=len(slow_m), slow_dept_heads=[EMPS[h - 1].username for h in slow_h],
                slow_hr=[EMPS[h - 1].username for h in slow_hr], seed=a.seed, stats=dict(STAT))
    with open(P("_generation_info.json"), "w") as f:
        json.dump(info, f, indent=2, default=str)
    if a.validate:
        validate(out)


def r_reason(q):
    return q.get("reason") if q["status"] != "DRAFT" else r.choice(REASONS[q["code"]])


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate(out):
    import pandas as pd
    rd = lambda n: pd.read_csv(os.path.join(out, n + ".csv"))
    T = {n: rd(n) for n in ["roles", "departments", "employees", "users", "leave_types", "holidays", "approval_rules",
                            "system_settings", "leave_balances", "leave_requests", "approval_steps", "audit_logs",
                            "notifications", "event_log"]}
    bad = []

    def chk(name, cond):
        ok = bool(cond)
        print(("  PASS  " if ok else "  FAIL  ") + name)
        if not ok:
            bad.append(name)

    emp, req, stp, bal = T["employees"], T["leave_requests"], T["approval_steps"], T["leave_balances"]
    print("validation:")
    for n in ["roles", "departments", "employees", "users", "leave_types", "holidays", "leave_balances",
              "leave_requests", "approval_steps", "audit_logs", "notifications"]:
        chk(f"unique primary key: {n}", T[n]["id"].is_unique)
    ids = set(emp.id)
    chk("employees.manager_id FK", emp.manager_id.dropna().isin(ids).all())
    chk("employees.department_id FK", emp.department_id.isin(T["departments"].id).all())
    chk("departments.head_employee_id FK", T["departments"].head_employee_id.isin(ids).all())
    chk("users: one per employee, FK role", T["users"].employee_id.is_unique and T["users"].employee_id.isin(ids).all()
        and T["users"].role_id.isin(T["roles"].id).all())
    chk("balances unique(emp,type,year)", not bal.duplicated(["employee_id", "leave_type_id", "year"]).any())
    chk("requests FK", req.employee_id.isin(ids).all() and req.leave_type_id.isin(T["leave_types"].id).all())
    chk("steps FK", stp.request_id.isin(req.id).all() and stp.approver_employee_id.dropna().isin(ids).all()
        and stp.acted_by_user_id.dropna().isin(T["users"].id).all())
    chk("steps unique(request,order)", not stp.duplicated(["request_id", "step_order"]).any())
    chk("audit user FK", T["audit_logs"].user_id.dropna().isin(T["users"].id).all())
    chk("notifications FK", T["notifications"].user_id.isin(T["users"].id).all()
        and T["notifications"].request_id.dropna().isin(req.id).all())
    chk("event_log case FK", T["event_log"].case_id.isin(req.id).all())
    chk("end_date >= start_date", (pd.to_datetime(req.end_date) >= pd.to_datetime(req.start_date)).all())
    chk("working_days >= 0", (req.working_days >= 0).all())
    chk("status enum (requests)", req.status.isin(["DRAFT", "SUBMITTED", "MANAGER_PENDING", "HR_PENDING",
                                                  "DEPARTMENT_HEAD_PENDING", "APPROVED", "REJECTED", "CANCELLED"]).all())
    chk("stage enum", stp.stage.isin(["MANAGER", "HR", "DEPARTMENT_HEAD"]).all())
    chk("step status enum", stp.status.isin(["WAITING", "PENDING", "APPROVED", "REJECTED", "SKIPPED", "CANCELLED"]).all())
    chk("balances used/pending >= 0", ((bal.used >= 0) & (bal.pending >= 0)).all())
    chk("balances used+pending <= allocated+carried", (bal.used + bal.pending <= bal.allocated + bal.carried_forward + 1e-9).all())
    chk("requests do not span two years", (req.start_date.str[:4] == req.end_date.str[:4]).all())
    build_calendar_if_needed()
    chk("working_days matches calendar",
        all(WD_IDX[date.fromisoformat(e)] - WD_IDX[date.fromisoformat(s)] + 1 == w
            for s, e, w in zip(req.start_date, req.end_date, req.working_days)))
    lt_t = T["leave_types"].set_index("id")
    rq = req.merge(T["leave_types"][["id", "tracks_balance"]], left_on="leave_type_id", right_on="id", suffixes=("", "_lt"))
    rq = rq[rq.tracks_balance]
    rq["year"] = rq.start_date.str[:4].astype(int)
    used = rq[rq.status == "APPROVED"].groupby(["employee_id", "leave_type_id", "year"]).working_days.sum()
    pend = rq[rq.status.isin(["MANAGER_PENDING", "HR_PENDING", "DEPARTMENT_HEAD_PENDING"])].groupby(
        ["employee_id", "leave_type_id", "year"]).working_days.sum()
    b2 = bal.set_index(["employee_id", "leave_type_id", "year"])
    chk("balances.used == sum(approved requests)", (b2.used.sub(used.reindex(b2.index).fillna(0)).abs() < 1e-9).all())
    chk("balances.pending == sum(pending requests)", (b2.pending.sub(pend.reindex(b2.index).fillna(0)).abs() < 1e-9).all())
    occ = req[req.status.isin(["APPROVED", "MANAGER_PENDING", "HR_PENDING", "DEPARTMENT_HEAD_PENDING"])].sort_values(
        ["employee_id", "start_date"])
    prev_end = occ.groupby("employee_id").end_date.shift()
    chk("no overlapping pending/approved requests", not (prev_end.notna() & (occ.start_date <= prev_end)).any())
    nonauto = req.merge(T["leave_types"][["id", "requires_approval"]], left_on="leave_type_id", right_on="id", suffixes=("", "_l"))
    nonauto = nonauto[(nonauto.status != "DRAFT") & nonauto.requires_approval]
    cnt = stp.groupby("request_id").size().reindex(nonauto.id).fillna(0)
    expect = nonauto.working_days.map(lambda w: 3 if w > 7 else 2 if w > 2 else 1).values
    chk("approval chain length matches rules (>0/>2/>7)", (cnt.values == expect).all())
    chk("approver never the requester",
        not stp.merge(req[["id", "employee_id"]], left_on="request_id", right_on="id")
        .eval("approver_employee_id == employee_id").any())
    chk("nobody decides their own request",
        not stp.dropna(subset=["acted_by_user_id"]).merge(req[["id", "employee_id"]], left_on="request_id", right_on="id")
        .eval("acted_by_user_id == employee_id and status != 'CANCELLED'").any())
    pend_req = req[req.status.isin(["MANAGER_PENDING", "HR_PENDING", "DEPARTMENT_HEAD_PENDING"])]
    pend_steps = stp[stp.status == "PENDING"].groupby("request_id").size()
    chk("each in-flight request has exactly one PENDING step", (pend_steps.reindex(pend_req.id).fillna(0) == 1).all())
    chk("in-flight status matches PENDING step stage",
        (pend_req.set_index("id").status.str.replace("_PENDING", "") ==
         stp[stp.status == "PENDING"].set_index("request_id").stage.reindex(pend_req.id)).all())
    appr = req[req.status == "APPROVED"].merge(T["leave_types"][["id", "requires_approval"]], left_on="leave_type_id",
                                               right_on="id", suffixes=("", "_l"))
    appr = appr[appr.requires_approval]
    bad_steps = stp[stp.request_id.isin(appr.id) & ~stp.status.isin(["APPROVED", "SKIPPED"])]
    chk("approved requests only have APPROVED/SKIPPED steps", bad_steps.empty)
    chk("rejected requests contain a REJECTED step",
        req[req.status == "REJECTED"].id.isin(stp[stp.status == "REJECTED"].request_id).all())
    chk("rejection / cancellation reasons present",
        req[req.status.isin(["REJECTED", "CANCELLED"])].decision_reason.notna().all())
    chk("draft requests have no submitted_at", req[req.status == "DRAFT"].submitted_at.isna().all())
    sub = pd.to_datetime(req.submitted_at, utc=True)
    dec = pd.to_datetime(req.decided_at, utc=True)
    chk("decided_at >= submitted_at", ((dec - sub).dropna() >= pd.Timedelta(0)).all())
    sd = stp.dropna(subset=["decided_at", "activated_at"])
    chk("step decided_at >= activated_at",
        ((pd.to_datetime(sd.decided_at, utc=True) - pd.to_datetime(sd.activated_at, utc=True)) >= pd.Timedelta(0)).all())
    chk("documents attached when required",
        req.merge(T["leave_types"], left_on="leave_type_id", right_on="id", suffixes=("", "_t"))
        .query("status != 'DRAFT' and requires_document and working_days > document_threshold_days").document_name.notna().all())
    chk("working_days <= max_consecutive_days",
        req.merge(T["leave_types"], left_on="leave_type_id", right_on="id", suffixes=("", "_t"))
        .eval("working_days <= max_consecutive_days").all())
    chk("at least 2 HR users", (T["users"].role_id == 3).sum() >= 2)
    chk("README demo accounts exist", {"employee", "manager", "hr"} <= set(T["users"].username))
    mgr_id = int(T["users"].set_index("username").loc["manager", "employee_id"])
    chk("manager 'karthik' has exactly 4 direct reports", (emp.manager_id == mgr_id).sum() == 4)
    if bad:
        sys.exit(f"VALIDATION FAILED: {bad}")
    print("ALL CHECKS PASSED")


def build_calendar_if_needed():
    if not WD_LIST:
        build_calendar()


if __name__ == "__main__":
    main()