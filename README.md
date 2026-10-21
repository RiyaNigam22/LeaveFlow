# LeaveFlow — Intelligent Employee Leave Management & Approval System

An end-to-end, rules-driven leave management application built with **Python, Streamlit, PostgreSQL and SQLAlchemy**.
It automates the full leave lifecycle — request, validation, multi-level approval, balance update, notification, audit —
and adds a process-analytics layer that shows *where the workflow loses time*.

> Built as a consulting-style portfolio project demonstrating business process automation, workflow design,
> role-based application development, relational modelling, SQL, business intelligence and auditability.

---

## 1. Business problem

In many organisations leave is still handled through email threads and spreadsheets:

- Managers approve without seeing balances, team overlap or policy limits.
- HR re-checks every request by hand (weekends, holidays, documents, overlaps).
- Balances drift out of sync; nobody can prove who approved what, and when.
- Leadership has no visibility into approval delays or absenteeism.

## 2. Solution

LeaveFlow encodes the policy once, in the database, and enforces it automatically:

```
Employee ─► Submit ─► Automatic validation ─► Manager ─► HR (if required) ─► Dept Head (if required)
                                                              │
                         Balance update ◄─ Notification ◄─ Audit log ◄─ Final decision ─► Analytics
```

### Business value

| Pain point | What LeaveFlow does | Outcome |
|---|---|---|
| Manual policy checking | Centralised rules engine validates balance, dates, overlaps, weekends, holidays, documents and approval level at submission | Invalid requests never reach an approver; HR effort drops |
| Inconsistent approval routing | Approval chain derived from configurable thresholds (≤2 d → Manager; >2 d → +HR; >7 d → +Dept Head) | Predictable, policy-compliant routing; changeable without code |
| No accountability | Every state change writes an audit record with user, entity, timestamp, old and new value | Audit-ready history; answers "who approved this and when?" |
| Slow approvals are invisible | Process analytics: avg/median turnaround, per-stage time, SLA breaches, bottleneck stage, approver response times, aging queue | Management can target the actual bottleneck |
| Staffing surprises | Team calendar highlights overlapping absences; approvers see conflicts on the request | Better coverage decisions |
| Balance disputes | Balances are reserved on submission and committed on final approval, inside one transaction | Balances always reconcile to request history |

## 3. Key features

- **Three roles** (Employee, Manager, HR/Admin) with page-level and service-level authorisation
- **Configurable leave types** (allowance, approval, document rule, carry-forward, max consecutive days, active flag) stored in the database
- **Rules engine** returns *all* validation findings at once, with live preview in the request form
- **Workflow engine** with explicit states and a legal-transition table; steps persisted in `approval_steps`
- **Balance reservation model** (`available = allocated + carried − used − pending`)
- **HR override** (approve / reject / cancel, including revoking approved leave) with mandatory reason
- **In-app notifications** with unread highlighting; **audit log** viewer with filters
- **Team calendar** (timeline + overlap detection) and **process analytics** dashboard
- **Security**: bcrypt hashes, login lockout, idle session timeout, generic login errors, no raw DB errors in the UI

## 4. Architecture

```
leaveflow/
├── app.py                  Entry point: login, role-based navigation, sidebar
├── config.py               Environment-driven configuration
├── pages/                  Streamlit pages (UI only – no business logic)
├── auth/                   security.py (bcrypt, policy) · service.py (authenticate, lockout) · session.py (Streamlit state, RBAC guards)
├── database/               models.py (ORM, source of truth) · connection.py · init_db.py (create/reset, schema export)
├── services/               rules_service (validation) · leave_service (use-cases) · balance_service
│                           admin_service (master data) · notification_service · audit_service
├── workflows/              states.py (pure state machine & rule selection) · engine.py (steps, transitions, permissions)
├── analytics/              metrics.py (pandas BI layer)
├── utils/                  dates.py (working-day logic) · errors.py · ui.py · components.py
├── seed/                   seed_data.py (demo data generated through the real services)
├── tests/                  pytest suite
└── schema.sql              PostgreSQL DDL (generated from the models)
```

Design principles: the UI calls **services**; services call the **workflow engine** and persist; the engine and
rules are **pure where possible** (and unit-tested without a database). Every use-case runs in **one transaction**
(`session_scope`), so a failure never leaves a half-applied approval. Services accept an injectable clock (`now`),
which is how the seed generates realistic history and how tests are deterministic.

### Workflow

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> SUBMITTED
    SUBMITTED --> MANAGER_PENDING
    SUBMITTED --> APPROVED: no approval required
    MANAGER_PENDING --> HR_PENDING: >2 working days
    MANAGER_PENDING --> APPROVED: ≤2 days
    HR_PENDING --> DEPARTMENT_HEAD_PENDING: >7 working days
    HR_PENDING --> APPROVED
    DEPARTMENT_HEAD_PENDING --> APPROVED
    MANAGER_PENDING --> REJECTED
    HR_PENDING --> REJECTED
    DEPARTMENT_HEAD_PENDING --> REJECTED
    SUBMITTED --> CANCELLED
    MANAGER_PENDING --> CANCELLED
    HR_PENDING --> CANCELLED
    DEPARTMENT_HEAD_PENDING --> CANCELLED
    APPROVED --> CANCELLED: HR override only
```

## 5. Technology stack

Streamlit · Python 3.11+ · PostgreSQL 14+ · SQLAlchemy 2 · Pandas · Plotly · bcrypt · python-dotenv · pytest

## 6. Database schema overview

13 tables (full DDL in [`schema.sql`](schema.sql)):

| Table | Purpose |
|---|---|
| `roles`, `users` | Authentication, role, lockout counters; one user per employee |
| `departments`, `employees` | Org structure; `employees.manager_id` (self FK) and `departments.head_employee_id` drive approver resolution |
| `leave_types` | Configurable leave policy per type |
| `leave_balances` | Per employee / type / year: allocated, carried_forward, used, pending (unique constraint) |
| `leave_requests` | Requests with status, working days, optional document, decision metadata (check constraints on dates/status) |
| `approval_steps` | One row per stage: approver, status, `activated_at` / `decided_at` (powers SLA analytics) |
| `approval_rules` | Configurable thresholds → required stages |
| `system_settings` | Weekend days, back-dating limit, advance limit, SLA hours |
| `holidays` | Company holidays excluded from working days |
| `notifications`, `audit_logs` | In-app messages; JSON old/new values per change |

Indexes cover the hot paths (requests by employee/status and dates, steps by approver/status, unread notifications, audit by entity/time).

## 7. User roles

| Capability | Employee | Manager | HR / Admin |
|---|:-:|:-:|:-:|
| Own dashboard, request, history, cancel pending, notifications | ✔ | ✔ | ✔ |
| Approval queue, approve / reject (reason mandatory) | | ✔ (own reports) | ✔ (HR stage) |
| Team dashboard, team history, team calendar | | ✔ | ✔ (calendar org-wide) |
| Organization dashboard, process analytics, all requests | | | ✔ |
| Manage employees, departments, leave types, holidays, approval rules, balances | | | ✔ |
| Override requests, view audit log | | | ✔ |

Nobody can approve or override their own request.

## 8. Business rules

| Rule | Behaviour |
|---|---|
| Balance | Requested working days must be ≤ available balance (pending requests are reserved) |
| Overlap | Rejected if the dates overlap an existing *pending or approved* request of the same employee |
| Working days | Weekends (configurable) and active company holidays are excluded |
| Dates | End ≥ start; no more than *N* days in the past / *M* in advance (settings); a request cannot span two calendar years |
| Documents | Required when `requires_document` and working days > `document_threshold_days` |
| Max length | Working days per request ≤ leave type's `max_consecutive_days` |
| Approval level | Highest matching `approval_rules` row: >0 d Manager · >2 d Manager+HR · >7 d Manager+HR+Dept Head |
| Auto-approval | Leave types with `requires_approval = false` are confirmed immediately |
| Approver resolution | Manager = `employee.manager`; if none → any HR user. Dept Head = `department.head`; skipped if absent, if the requester is the head, or if the same person already approved an earlier stage |

Thresholds and stages live in the `approval_rules` table and are editable under **Leave Policies**.

## 9. Screenshots

Add your own after running the app:

| Page | Screenshot |
|---|---|
| Employee dashboard | `docs/screenshots/employee-dashboard.png` |
| Request form with live validation | `docs/screenshots/request-form.png` |
| Manager approval queue | `docs/screenshots/approval-queue.png` |
| Team calendar | `docs/screenshots/team-calendar.png` |
| Organization dashboard | `docs/screenshots/hr-dashboard.png` |
| Process analytics | `docs/screenshots/process-analytics.png` |

## 10. Installation

```bash
git clone <your-repo-url> leaveflow && cd leaveflow
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 11. Environment configuration

```bash
cp .env.example .env     # then edit DATABASE_URL etc.
```

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL of the app database | `postgresql+psycopg2://leaveflow:leaveflow@localhost:5432/leaveflow` |
| `TEST_DATABASE_URL` | Separate database used by pytest (**its tables are dropped**) | `…/leaveflow_test` |
| `APP_TIMEZONE` | Timezone for "today" and displayed times | `Asia/Kolkata` |
| `SESSION_TIMEOUT_MINUTES` | Idle session expiry | `30` |
| `MAX_LOGIN_ATTEMPTS` / `LOCKOUT_MINUTES` | Lockout policy | `5` / `15` |
| `MAX_DOCUMENT_MB` | Upload size limit | `5` |
| `SICK_LEAVE_CODE` / `NON_ABSENCE_CODES` | Leave-type codes used by analytics | `SICK` / `WFH` |

## 12. Database setup

```bash
# one-time, as a PostgreSQL superuser
psql -c "CREATE USER leaveflow WITH PASSWORD 'leaveflow';"
psql -c "CREATE DATABASE leaveflow OWNER leaveflow;"
psql -c "CREATE DATABASE leaveflow_test OWNER leaveflow;"

# create tables and load demo data (safe to re-run: --reset rebuilds everything)
python -m database.init_db --reset
```

Alternatives: `python -m database.init_db` creates tables only; `psql -f schema.sql` applies the DDL directly;
`python -m database.init_db --export-schema` regenerates `schema.sql` from the models.

## 13. Running locally

```bash
streamlit run app.py
```

Open http://localhost:8501 and sign in.

## 14. Testing

```bash
pytest -q
```

~136 tests, all against real PostgreSQL (`TEST_DATABASE_URL`): working-day and holiday logic, balance validation,
overlap detection, document rules, approval-rule selection and thresholds, every workflow transition and permission,
mandatory rejection reasons, balance reserve/commit/release/revoke, notifications, audit records, login lockout,
admin safeguards, and Streamlit `AppTest` flows (every page renders for its role, role guards, login, request
submission, approve/reject, and "no raw errors reach the user"). DB tests are skipped automatically if PostgreSQL is not reachable.

## 15. Demo credentials (local development only)

| Role | Username | Password | Notes |
|---|---|---|---|
| Employee | `employee` | `Employee@123` | Ananya Iyer, Engineering |
| Manager | `manager` | `Manager@123` | Karthik Rao, Engineering team lead (4 reports) |
| HR / Admin | `hr` | `HrAdmin@123` | Priya Sharma, Head of HR |

All other seeded users sign in as `firstname.lastname` (e.g. `rohan.das`, `vikram.nair`) with password `Welcome@123`.
**Change or remove these accounts before any real deployment.**

Suggested walkthrough: submit a 9-day Annual Leave as `employee` (watch the live check show a 3-stage path) →
approve as `manager` → approve as `hr` → approve as `vikram.nair` → check notifications and the audit log → open
*Process Analytics* as `hr`.

## 16. Design notes & known limitations

- **Sessions** live in Streamlit's server-side `session_state`; a browser refresh signs the user out (no cookie persistence). Idle timeout is enforced.
- **Approval hours are wall-clock hours**, not business hours. SLA is a single per-stage target (`SLA_HOURS_PER_STAGE`).
- **"Team" = direct reports.** Skip-level visibility is not modelled.
- Requests spanning two calendar years must be split (balances are per year).
- Notifications are in-app only (no email/SMS).
- Documents are stored in the database (≤ 5 MB) – fine for a demo; use object storage at scale.
- HR users cannot approve their own requests, so at least **two** HR/Admin users are needed.

## 17. Future improvements

Email/Teams/Slack notifications · SSO (OIDC/SAML) and cookie-based sessions · half-day and hourly leave ·
delegation when approvers are away · business-hours SLA calendars and automatic escalation/reminders ·
iCal export / calendar sync · Alembic migrations · REST API for HRIS / payroll integration ·
object storage for documents · multi-level skip-level team views · forecasting of absence peaks.
