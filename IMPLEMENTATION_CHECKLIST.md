# LeaveFlow – Implementation Checklist

| Phase | Component | Status |
|---|---|---|
| 1 | Project structure, requirements, .env.example, .gitignore, Streamlit theme | DONE |
| 2 | config, models (13 tables), connection, init_db, schema.sql, seed (35 employees, ~200 requests) | DONE |
| 3 | Auth: bcrypt, lockout, idle timeout, session state, page-level RBAC | DONE |
| 4 | Rules/validation service + leave submission | DONE |
| 5 | Workflow engine (states, steps, transitions, permissions, override) | DONE |
| 6 | Notifications + audit logging | DONE |
| 7 | Employee dashboard, request form, my requests, notifications | DONE |
| 8 | Manager dashboard, approval queue, team history, team calendar | DONE |
| 9 | HR dashboard + employees, policies, balances, requests/override, audit | DONE |
| 10 | Analytics / process intelligence (turnaround, SLA, bottleneck, absenteeism) | DONE |
| 11 | Tests (136 passing) + user-safe error handling | DONE |
| 12 | UI polish, README, final consistency audit | DONE |

## Final consistency audit (all verified by execution)
- Imports/paths: pyflakes clean; every nav entry maps to an existing page; no orphan pages
- Auth/RBAC: every page has a guard; cross-role and anonymous access refused (tested)
- DB: schema.sql loads into an empty DB and is in sync with models; balances reconcile with request history (SQL invariant check)
- Workflow/validation/notifications/audit: covered by tests; seed generated via real services
- Env vars: all documented in .env.example and README; README commands and demo credentials executed successfully
