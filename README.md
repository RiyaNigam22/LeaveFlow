# LeaveFlow --- Intelligent Employee Leave Management & Approval System

**An end-to-end, rules-driven employee leave management platform built
with Python, Streamlit, PostgreSQL, and SQLAlchemy.**

[**🚀 Launch Live Application**](https://leaveflow-demo.streamlit.app/)

LeaveFlow streamlines the employee leave lifecycle---from request
submission and policy validation to multi-stage approvals, balance
updates, notifications, audit trails, and process analytics.

> **Portfolio project:** Demonstrates business process automation,
> role-based access control (RBAC), relational database design, workflow
> orchestration, and operational analytics using a fictional employee
> dataset.

------------------------------------------------------------------------

## 1. Business Problem

Managing leave through emails and spreadsheets creates avoidable
operational challenges:

-   **Inconsistent policy enforcement:** Requests may be approved
    without checking eligibility, balances, holidays, or overlapping
    leave.
-   **Fragmented approvals:** Managers and HR lack a unified view of
    requests and pending decisions.
-   **Poor traceability:** It is difficult to establish who approved,
    rejected, or modified a request.
-   **Limited visibility:** HR teams cannot easily identify approval
    bottlenecks or absence trends.

**LeaveFlow centralizes these processes in one application**, using
configurable rules and a structured approval workflow.

## 2. What LeaveFlow Does

  -----------------------------------------------------------------------
  Business need                       LeaveFlow capability
  ----------------------------------- -----------------------------------
  Consistent leave decisions          Centralized validation for leave
                                      balance, dates, overlap, holidays,
                                      documentation, and maximum duration

  Multi-level approvals               Configurable Manager → HR →
                                      Department Head routing

  Accurate leave accounting           Tracks allocated, carried-forward,
                                      used, and pending balances

  Operational accountability          Records workflow actions and
                                      changes in an audit log

  Better team planning                Team leave calendar and visibility
                                      into overlapping absences

  Management insights                 Approval turnaround, pending
                                      stages, SLA breaches, and
                                      departmental leave trends
  -----------------------------------------------------------------------

### Approval Workflow

``` mermaid
flowchart TD
    A[Employee submits leave request] --> B[Validate policy and balance]
    B --> C{Valid request?}
    C -->|No| D[Show validation findings]
    C -->|Yes| E{Approval required?}
    E -->|No| J[Confirm request]
    E -->|Yes| F[Manager review]
    F -->|Reject| K[Reject request]
    F -->|Approve, short leave| J
    F -->|Approve, longer leave| G[HR review]
    G -->|Reject| K
    G -->|Approve, up to 7 days| J
    G -->|Approve, over 7 days| H[Department Head review]
    H -->|Approve| J
    H -->|Reject| K
    J --> L[Update balance, notifications and audit log]
    K --> L
    L --> M[Dashboard and process analytics]
```

Approval stages are driven by configurable rules; the diagram
illustrates the standard approval path. Actual routing also accounts for
leave type, approver availability, and workflow rules.

## 3. Core Features

### Employee Portal

-   Personal dashboard with leave balances and request history
-   Leave submission with policy validation and working-day calculation
-   Visibility into request status and upcoming approved leave
-   Cancellation of eligible pending requests
-   In-app notifications

### Manager Portal

-   Team dashboard and pending approval queue
-   Approve or reject requests with workflow checks
-   View direct reports' leave history
-   Team leave calendar and overlapping absence visibility
-   Approval-related metrics

### HR / Administrator Portal

-   Organization-wide leave and approval dashboards
-   Employee, department, leave type, holiday, and balance
    administration
-   Configurable approval rules and system settings
-   Authorized request overrides with reasons
-   Audit trail and process analytics

### Business Rules and Workflow Controls

-   Excludes weekends and configured holidays from working-day
    calculations
-   Checks available leave balance and overlapping requests
-   Applies leave-type document requirements and maximum durations
-   Routes requests through the appropriate approval stages
-   Prevents users from approving their own requests
-   Updates balances, notifications, and audit records as workflow
    decisions occur

## 4. Technology Stack

  Layer                  Technology
  ---------------------- ---------------------------------------------------
  Application and UI     Python, Streamlit
  Relational database    PostgreSQL
  ORM and transactions   SQLAlchemy
  Data analysis          Pandas
  Visualizations         Plotly
  Authentication         Password hashing with bcrypt, session-based login
  Configuration          Environment variables, python-dotenv
  Testing                pytest, Streamlit AppTest
  Deployment             Streamlit Community Cloud and Supabase PostgreSQL
  Version control        Git and GitHub

## 5. Architecture

LeaveFlow separates presentation, business logic, workflow decisions,
and persistence.

``` text
leaveflow/
├── app.py                  # Streamlit entry point and role-based navigation
├── config.py               # Environment-driven configuration
├── pages/                  # Employee, manager, and HR interfaces
├── auth/                   # Authentication, sessions, role guards
├── database/               # SQLAlchemy models, connections, initialization
├── services/               # Leave, balance, rules, admin, notifications, audit
├── workflows/              # State transitions and approval orchestration
├── analytics/              # Reporting and operational metrics
├── utils/                  # Shared utilities and date handling
├── seed/                   # Synthetic demonstration data generation
├── tests/                  # Automated tests
├── requirements.txt
└── schema.sql              # PostgreSQL schema definition
```

**Design principles:** - UI pages delegate business operations to
service-layer functions. - Workflow transitions are managed centrally
rather than scattered across UI code. - SQLAlchemy transactions keep
related updates consistent. - Authorization is enforced through roles
and service-level checks. - Configurable policies are stored in the
database.

## 6. Database Design

The relational model includes **13 core tables**.

  -----------------------------------------------------------------------
  Table(s)                            Purpose
  ----------------------------------- -----------------------------------
  `roles`, `users`                    Authentication and role assignment

  `departments`, `employees`          Organization structure and
                                      reporting relationships

  `leave_types`                       Leave categories and policy
                                      configuration

  `leave_balances`                    Allocated, carried-forward, used,
                                      and pending leave

  `leave_requests`                    Leave applications, dates, status,
                                      and decisions

  `approval_steps`                    Individual workflow stages,
                                      approvers, and timestamps

  `approval_rules`                    Configurable approval thresholds
                                      and stage routing

  `system_settings`                   Operational policy settings

  `holidays`                          Non-working company holidays

  `notifications`, `audit_logs`       User notifications and change
                                      history
  -----------------------------------------------------------------------

See [`schema.sql`](schema.sql) for the database schema.

### Leave Balance Model

``` text
Available leave = Allocated + Carried forward - Used - Pending
```

Reserving leave while a request is pending helps prevent the same
balance from being committed to multiple requests.

## 7. Process Analytics

LeaveFlow provides operational visibility beyond basic leave totals,
including:

-   Request volume and status distribution
-   Average and median approval turnaround
-   Time spent in each approval stage
-   Pending request aging and SLA breaches
-   Department-level leave utilization
-   Approval bottlenecks and approver response patterns

These metrics support analysis of workflow efficiency and staffing
patterns.

## 8. Live Demo

**[Open LeaveFlow](https://leaveflow-demo.streamlit.app/)**

The application supports Employee, Manager, and HR/Administrator roles
and uses demonstration data.

> **Demo note:** This is a portfolio application, not a production HR
> system. Do not enter real employee, medical, or confidential
> organizational information. Public demo access and available actions
> may be limited.

## 9. Run Locally

### Prerequisites

-   Python 3.11 or newer
-   PostgreSQL
-   Git

### Clone and install

``` bash
git clone https://github.com/RiyaNigam22/leaveflow.git
cd leaveflow
python -m venv .venv
```

Activate the virtual environment:

**Windows PowerShell**

``` powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

``` bash
source .venv/bin/activate
```

Install dependencies:

``` bash
pip install -r requirements.txt
```

### Configure the database

Create a local `.env` file based on `.env.example`, and configure a
PostgreSQL connection:

``` dotenv
DATABASE_URL=postgresql+psycopg2://YOUR_USER:YOUR_PASSWORD@localhost:5432/YOUR_DATABASE
```

**Never commit `.env`, hosted database credentials, or database backups
to Git.**

Create missing tables in the configured database:

``` bash
python -m database.init_db
```

> **Warning:** Initialization and reset operations are different. Do not
> run commands with `--reset` against a database containing data you
> need to keep.

If you want synthetic sample records, review the seed script and its
required environment variables before running it against a **disposable
local database**.

### Start the application

``` bash
python -m streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## 10. Testing

The repository includes automated tests for business rules, workflow
transitions, authorization, database-backed services, and Streamlit page
behavior.

``` bash
python -m pytest -q
```

Some tests require a separately configured PostgreSQL test database.
**Never point `TEST_DATABASE_URL` to your deployed Supabase database or
to a database containing valuable data.**

## 11. Current Limitations

-   Streamlit sessions are not persisted across browser refreshes.
-   Notifications are in-app; email and messaging integrations are not
    implemented.
-   Team visibility is primarily based on direct reporting
    relationships.
-   Leave requests spanning calendar years require separate handling.
-   SLA calculations use elapsed hours rather than a full business-hours
    calendar.
-   Uploaded documents are stored in the database; external object
    storage would be preferable at scale.
-   The application is a demonstration system and is not intended to
    manage real employee information.

## 12. Future Enhancements

-   Single sign-on and stronger production identity management
-   Email, Teams, or Slack notifications
-   Delegated approvers and automatic escalation
-   Half-day and hourly leave requests
-   Calendar integration and export
-   Alembic-managed schema migrations
-   External document storage
-   Forecasting of absence peaks and workforce coverage

------------------------------------------------------------------------

**LeaveFlow** combines business-process design with practical software
engineering to demonstrate how structured workflows, relational data,
and analytics can improve operational decision-making.
