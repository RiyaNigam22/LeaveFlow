"""LeaveFlow – entry point: sign-in, role-based navigation and sidebar."""

import streamlit as st

import config
from auth.session import current_user, login, logout
from database.connection import check_database, session_scope
from services import notification_service
from utils import ui
from utils.errors import AuthenticationError
import os
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url



# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="LeaveFlow",
    page_icon=":material/event_available:",
    layout="wide",
)

ui.inject_css()


# ---------------------------------------------------------
# PAGE DEFINITIONS
# ---------------------------------------------------------

PAGES = {
    "emp_dash": (
        "views/employee_dashboard.py",
        "My Dashboard",
        ":material/dashboard:",
    ),
    "request": (
        "views/request_leave.py",
        "Request Leave",
        ":material/add_circle:",
    ),
    "mine": (
        "views/my_requests.py",
        "My Requests",
        ":material/list_alt:",
    ),
    "notes": (
        "views/notifications.py",
        "Notifications",
        ":material/notifications:",
    ),

    # Manager pages
    "mgr_dash": (
        "views/manager_dashboard.py",
        "Team Dashboard",
        ":material/monitoring:",
    ),
    "queue": (
        "views/manager_approvals.py",
        "Approval Queue",
        ":material/approval:",
    ),
    "history": (
        "views/manager_history.py",
        "Team Leave History",
        ":material/history:",
    ),
    "calendar": (
        "views/team_calendar.py",
        "Team Calendar",
        ":material/calendar_month:",
    ),

    # HR pages
    "hr_dash": (
        "views/hr_dashboard.py",
        "Organization Dashboard",
        ":material/insights:",
    ),
    "hr_analytics": (
        "views/hr_analytics.py",
        "Process Analytics",
        ":material/analytics:",
    ),
    "hr_requests": (
        "views/hr_requests.py",
        "All Requests",
        ":material/fact_check:",
    ),
    "hr_employees": (
        "views/hr_employees.py",
        "Employees & Departments",
        ":material/groups:",
    ),
    "hr_policies": (
        "views/hr_policies.py",
        "Leave Policies",
        ":material/policy:",
    ),
    "hr_balances": (
        "views/hr_balances.py",
        "Leave Balances",
        ":material/account_balance:",
    ),
    "hr_audit": (
        "views/hr_audit.py",
        "Audit Log",
        ":material/manage_search:",
    ),
}


# ---------------------------------------------------------
# ROLE-BASED NAVIGATION
# Direct role string alignment: "EMPLOYEE", "MANAGER", "HR"
# ---------------------------------------------------------

# NAV = {
#     "EMPLOYEE": {
#         "My Leave": [
#             "emp_dash",
#             "request",
#             "mine",
#             "notes",
#         ],
#     },

#     "MANAGER": {
#         "Team": [
#             "mgr_dash",
#             "queue",
#             "history",
#             "calendar",
#         ],
#         "My Leave": [
#             "emp_dash",
#             "request",
#             "mine",
#             "notes",
#         ],
#     },

#     "HR": {
#         "Organization": [
#             "hr_dash",
#             "hr_analytics",
#             "hr_requests",
#             "queue",
#             "calendar",
#         ],
#         "Administration": [
#             "hr_employees",
#             "hr_policies",
#             "hr_balances",
#             "hr_audit",
#         ],
#         "My Leave": [
#             "emp_dash",
#             "request",
#             "mine",
#             "notes",
#         ],
#     },
# }
# ---------------------------------------------------------
# ROLE-BASED NAVIGATION
# ---------------------------------------------------------

NAV = {
    config.ROLE_EMPLOYEE: {
        "My Leave": [
            "emp_dash",
            "request",
            "mine",
            "notes",
        ],
    },

    config.ROLE_MANAGER: {
        "Team": [
            "mgr_dash",
            "queue",
            "history",
            "calendar",
        ],
        "My Leave": [
            "emp_dash",
            "request",
            "mine",
            "notes",
        ],
    },

    # Matches config.ROLE_HR ('HR_ADMIN') perfectly
    config.ROLE_HR: {
        "Organization": [
            "hr_dash",
            "hr_analytics",
            "hr_requests",
            "queue",
            "calendar",
        ],
        "Administration": [
            "hr_employees",
            "hr_policies",
            "hr_balances",
            "hr_audit",
        ],
        "My Leave": [
            "emp_dash",
            "request",
            "mine",
            "notes",
        ],
    },
}

# ---------------------------------------------------------
# DATABASE STATUS
# ---------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _db_status() -> str | None:
    return check_database()


# ---------------------------------------------------------
# LOGIN SCREEN
# ---------------------------------------------------------

def login_screen() -> None:

    # Center login form
    _, mid, _ = st.columns([1, 1.1, 1])

    with mid:

        st.markdown("""<div class="lf-login-intro"><div class="lf-brand"><div class="lf-brand-mark">L</div><div><div class="lf-brand-title">LeaveFlow</div><div class="lf-brand-sub">WORKFORCE INTELLIGENCE</div></div></div><h1>Welcome back</h1><p>Sign in to your workspace</p></div>""",unsafe_allow_html=True,)
        # Show session expiry message if applicable
        if st.session_state.pop("session_expired", False):
            st.warning(
                "Your session expired due to inactivity. "
                "Please sign in again."
            )

        # Login form
        with st.form(
            "login_form",
            clear_on_submit=False,
        ):
            username_or_email = st.text_input(
                "Username or Email",
                autocomplete="username",
            )

            password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )

            submitted = st.form_submit_button(
                "Sign in",
                type="primary",
                use_container_width=True,
            )

        # -------------------------------------------------
        # LOGIN VALIDATION
        # -------------------------------------------------

        if submitted:

            # Remove accidental spaces
            username_or_email = username_or_email.strip()
            password = password.strip()

            if not username_or_email or not password:
                st.error(
                    "Please enter your username/email and password."
                )
                return

            try:
                # LeaveFlow authentication system (supports username or email)
                login(username_or_email, password)

                # Refresh the application
                st.rerun()

            except AuthenticationError:
                st.error("Invalid username/email or password.")

            except Exception:
                # Do not expose internal errors
                st.error(ui.GENERIC_ERROR)


# ---------------------------------------------------------
# MAIN APPLICATION
# ---------------------------------------------------------

def main() -> None:

    # -----------------------------------------------------
    # 1. CHECK DATABASE
    # -----------------------------------------------------

    problem = _db_status()

    if problem:
        st.error(problem)

        if st.button("Retry"):
            _db_status.clear()
            st.rerun()

        st.stop()


    # -----------------------------------------------------
    # 2. CHECK CURRENT USER
    # -----------------------------------------------------

    user = current_user()

    if user is None:
        login_screen()
        st.stop()


    # -----------------------------------------------------
    # 3. CREATE STREAMLIT PAGES
    # -----------------------------------------------------

    pages = {
        key: st.Page(
            file,
            title=title,
            icon=icon,
            url_path=key,
        )
        for key, (file, title, icon) in PAGES.items()
    }


    # -----------------------------------------------------
    # 4. BUILD ROLE-BASED NAVIGATION
    # -----------------------------------------------------

    user_role = str(user["role"]).upper()

    # Safety check in case an invalid role reaches the UI
    if user_role not in NAV:
        st.error(f"Your account role ('{user_role}') does not have a valid application navigation role.")

        if st.button("Sign out"):
            logout()
            st.rerun()

        st.stop()

    nav = {
        section: [
            pages[key]
            for key in keys
        ]
        for section, keys in NAV[user_role].items()
    }


    # -----------------------------------------------------
    # 5. FETCH NOTIFICATIONS
    # -----------------------------------------------------

    with session_scope() as session:
        unread = notification_service.unread_count(
            session,
            user["user_id"],
        )


    # -----------------------------------------------------
    # 6. ROLE LABEL
    # -----------------------------------------------------

    role_label = {
        "EMPLOYEE": "Employee",
        "MANAGER": "Manager",
        config.ROLE_HR: "HR / Admin",
    }.get(user_role, user_role)


    # -----------------------------------------------------
    # 7. SIDEBAR USER INFORMATION
    # -----------------------------------------------------

    with st.sidebar:

        st.markdown('<div class="lf-brand"><div class="lf-brand-mark">L</div><div><div class="lf-brand-title">LeaveFlow</div><div class="lf-brand-sub">WORKFORCE INTELLIGENCE</div></div></div>', unsafe_allow_html=True)
        st.markdown(f"""<div class="lf-user"><div class="name">{user["full_name"]}</div><div class="meta">{role_label}</div></div>""", unsafe_allow_html=True)

        if unread:
            st.caption(
                f":material/notifications_active: "
                f"{unread} unread notification(s)"
            )


    # -----------------------------------------------------
    # 8. NAVIGATION
    # -----------------------------------------------------

    page = st.navigation(nav)


    # -----------------------------------------------------
    # 9. LOGOUT
    # -----------------------------------------------------

    with st.sidebar:

        ui.theme_picker()
        ui.inject_css()
        if st.button(
            "Sign out",
            icon=":material/logout:",
            use_container_width=True,
        ):
            logout()
            st.rerun()


    # -----------------------------------------------------
    # 10. RUN SELECTED PAGE
    # -----------------------------------------------------

    page.run()


# ---------------------------------------------------------
# APPLICATION ENTRY POINT
# ---------------------------------------------------------

if __name__ == "__main__":
    main()