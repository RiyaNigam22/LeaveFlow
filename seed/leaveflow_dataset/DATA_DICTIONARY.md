# LeaveFlow stress-test dataset - data dictionary

**All data is simulated.** Company ("Meridian Tech Pvt Ltd"), people, e-mails (`@meridiantech.example`) and every
number are fictional. Label any result you derive from it as *simulated*.

Snapshot time: **2026-10-07 12:00 IST**. Submissions run **2025-01-01 -> 2026-10-07**. Seed: `20261007`.
Columns match your `schema.sql` exactly (verified by loading into PostgreSQL 16 with all FKs and CHECKs enforced).

## Files and row counts

| File | Rows | Notes |
|---|---:|---|
| roles.csv | 3 | EMPLOYEE, MANAGER, HR |
| departments.csv | 8 | each has a head |
| employees.csv | 2,500 | 56 inactive (leavers), 1 CEO, manager hierarchy |
| users.csv | 2,500 | one per employee; `users.id = employees.id` |
| leave_types.csv | 8 | AL, CL, SICK, ML, PL, CO, WFH, LOP |
| holidays.csv | 28 | 2025-2026, one inactive; movable festival dates are approximate |
| approval_rules.csv | 3 | `min_days` 0 / 2 / 7, applied as "working days **>** min_days" |
| system_settings.csv | 7 | weekend, back-date limit 7, advance limit 180, SLA 48h ... |
| leave_balances.csv | 24,295 | per employee / tracked type / year (2025, 2026) |
| leave_requests.csv | 49,998 | all 8 statuses |
| approval_steps.csv | 56,535 | per-stage `activated_at` / `decided_at` |
| audit_logs.csv | 225,198 | JSON old/new values |
| notifications.csv | 172,539 | read / unread |
| event_log.csv | 221,384 | flat process-mining log (not a DB table) |
| **Total** | **755,006** | ~102 MB uncompressed |

## Demo accounts (from your README)

| Role | Username | Password | Person |
|---|---|---|---|
| Employee | `employee` | `Employee@123` | Ananya Iyer, Engineering |
| Manager | `manager` | `Manager@123` | Karthik Rao, Engineering Team Lead (exactly 4 reports; has pending approvals) |
| HR / Admin | `hr` | `HrAdmin@123` | Priya Sharma, Head of HR |

Everyone else: `firstname.lastname` / `Welcome@123` (e.g. `rohan.das`, `vikram.nair`). Hashes are real bcrypt (cost 12).
**Demo only - never ship these credentials.** 12 users have role HR, 283 have role MANAGER.

## Modelling choices you should know about

| Topic | What the data does |
|---|---|
| Approval routing | >0 d Manager, >2 d +HR, >7 d +Dept Head (matches README) |
| Auto-approval | `WFH` has `requires_approval=false`: status APPROVED immediately, **no approval_steps rows** |
| Manager stage approver | `employees.manager_id`; the CEO has none, so an HR user is assigned |
| HR stage approver | A specific HR user is pre-assigned (never the requester). `approver_employee_id` is set from the start |
| Dept-Head stage | `SKIPPED` if the requester is the head (approver = NULL) or the head already approved an earlier stage |
| After reject / cancel | Remaining steps become `CANCELLED`; steps skipped by an HR override become `SKIPPED` |
| HR override | Approve/reject when a stage waits >72h; cancel of already-approved leave. Shown in `comments`, `decision_reason`, `audit_logs.action` (`HR_OVERRIDE_*`) and `acted_by_user_id` differing from the approver |
| Balances | Replayed from request history: `used` = sum of APPROVED days, `pending` = sum of in-flight days. `carried_forward` is a simulated opening balance |
| Documents | `document_name` is set when required; `document_content` is NULL (no binary files) |
| Roles / stage text | Role names `EMPLOYEE/MANAGER/HR` and `approval_rules.stages` as `MANAGER,HR,...` are assumptions. Edit the constants in the generator if your code differs |
| Gender, ML/PL | Not stored. ML is only granted to women, PL only to men (internal eligibility) |

## Planted behaviour for process mining

* Slow approvers (about 8% of managers, 2 HR users, 2 department heads) with several-times longer response times
* HR slower at month-end (days >=26 or <=2) and during an **HR backlog window 2025-08-11 -> 2025-08-22**
* Seasonality: December 2025 peak, Diwali clusters, month-end submission spike, Monday bias
* Year-end / Diwali leave clusters that raise **team-coverage rejections**
* HR overrides (approve / reject / cancel), skipped Dept-Head stages, employee cancellations
* **Resubmissions** after rejection (see `event_log.resubmission_of_request_id`)
* A few long-stuck requests (approver forgot / on leave) and an in-flight queue at the snapshot time
* Security noise in `audit_logs`: failed logins and 150 lockout incidents

## event_log.csv (for PM4Py)

`case_id` = `leave_requests.id`, `activity`, `timestamp`, `resource` (employee_code or SYSTEM), `resource_role`,
`leave_type`, `department`, `working_days`, `case_status`, `stage_hours` (wait time on review-complete events),
`sla_breach` (stage_hours > 48), `resubmission_of_request_id`.
Drafts are excluded. In-flight cases have no terminal event.

```python
import pandas as pd, pm4py
df = pd.read_csv("event_log.csv")
df = pm4py.format_dataframe(df, case_id="case_id", activity_key="activity", timestamp_key="timestamp")
dfg, start, end = pm4py.discover_dfg(df)
```

## Loading into PostgreSQL

Load order matters only for `departments` (its `head_employee_id` points at `employees`, which points back at departments).

```sql
-- 1. staging for departments, then insert without the head
CREATE TEMP TABLE dh(id int, name text, head int, c timestamptz, u timestamptz);
\copy dh FROM 'departments.csv' CSV HEADER
\copy roles FROM 'roles.csv' CSV HEADER
INSERT INTO departments(id,name,created_at,updated_at) SELECT id,name,c,u FROM dh;
-- 2. everything else, in this order
\copy employees FROM 'employees.csv' CSV HEADER
UPDATE departments d SET head_employee_id = dh.head FROM dh WHERE dh.id = d.id;
\copy users FROM 'users.csv' CSV HEADER
\copy leave_types FROM 'leave_types.csv' CSV HEADER
\copy holidays FROM 'holidays.csv' CSV HEADER
\copy approval_rules FROM 'approval_rules.csv' CSV HEADER
\copy system_settings FROM 'system_settings.csv' CSV HEADER
\copy leave_balances FROM 'leave_balances.csv' CSV HEADER
\copy leave_requests FROM 'leave_requests.csv' CSV HEADER
\copy approval_steps FROM 'approval_steps.csv' CSV HEADER
\copy audit_logs FROM 'audit_logs.csv' CSV HEADER
\copy notifications FROM 'notifications.csv' CSV HEADER
-- 3. IMPORTANT: ids were loaded explicitly, so reset every SERIAL sequence
SELECT setval(pg_get_serial_sequence('employees','id'), max(id)) FROM employees;
-- repeat for: departments, users, roles, leave_types, holidays, approval_rules,
--             leave_balances, leave_requests, approval_steps, audit_logs, notifications
```

## Regenerating / resizing

```bash
pip install bcrypt pandas
python generate_leaveflow_data.py --out leaveflow_dataset --employees 2500 --requests 50000 --validate
```

The `--validate` flag runs ~40 integrity checks: PK/FK, enums, balance reconciliation, no overlaps, routing vs rules,
working-day recomputation, document and max-length rules, in-flight consistency.
