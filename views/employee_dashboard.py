import pandas as pd
# import plotly.express as px
# import streamlit as st

# from analytics import metrics as mt
# from auth.session import require_login
# from database.connection import session_scope
# from services import balance_service
# from utils import ui
# from utils.components import format_requests
# from utils.dates import today_local

# user = require_login()
# ui.page_header("My Dashboard", f"Leave overview for {user['full_name']}")
# today, year = today_local(), today_local().year

# with ui.guard():
#     with session_scope() as s:
#         req = mt.requests_df(s, [user["employee_id"]], year)
#         balances = balance_service.list_for_employee(s, user["employee_id"], year)
#         bal_rows = [{"Leave type": b.leave_type.name, "Entitled": float(b.total), "Used": float(b.used),
#                      "Pending": float(b.pending), "Available": float(b.available)} for b in balances]
#     counts = mt.status_counts(req)
#     bal = pd.DataFrame(bal_rows)
#     ui.kpi_cards([("Available leave", f"{bal['Available'].sum():g} days" if not bal.empty else "—", f"Across balance-tracked types, {year}", "good"),
#                   ("Pending requests", counts["pending"], "Awaiting approval", "warn" if counts["pending"] else ""),
#                   ("Approved requests", counts["approved"], f"In {year}"),
#                   ("Rejected requests", counts["rejected"], f"In {year}", "bad" if counts["rejected"] else "")])
#     ui.page_link("views/request_leave.py", "Request leave", ":material/add_circle:")

#     left, right = st.columns(2)
#     with left:
#         by_type = mt.leave_by_type(req)
#         if by_type.empty:
#             st.info("No approved leave yet this year.")
#         else:
#             ui.chart(px.pie(by_type, names="Leave type", values="Days", hole=0.55, title="Leave usage by type (approved days)"))
#     with right:
#         trend = mt.monthly_trend(req, year)
#         ui.chart(px.bar(trend, x="Month", y="Approved leave days", title=f"Monthly leave history {year}"))

#     ui.section("Leave balances")
#     if not bal.empty:
#         st.dataframe(bal, hide_index=True, width="stretch", column_config={
#             "Available": st.column_config.ProgressColumn("Available", min_value=0, max_value=float(bal["Entitled"].max() or 1), format="%g")})

#     c1, c2 = st.columns(2)
#     with c1:
#         ui.section("Recent requests")
#         recent = req.sort_values("submitted_at", ascending=False).head(8)
#         ui.show_table(format_requests(recent).drop(columns=["Submitted"]), "Status")
#     with c2:
#         ui.section("Upcoming approved leave")
#         up = req[(req["status"] == "APPROVED") & (req["end_date"].dt.date >= today)].sort_values("start_date")
#         ui.show_table(format_requests(up.head(8))[["ID", "Leave type", "From", "To", "Days"]])
import pandas as pd
import streamlit as st

from analytics import metrics as mt
from auth.session import require_login
from database.connection import session_scope
from services import balance_service
from utils import ui
from utils.components import format_requests
from utils.dates import today_local

user = require_login()
ui.page_header("My Dashboard", f"Leave overview for {user['full_name']}")
today, year = today_local(), today_local().year

with ui.guard():
    with session_scope() as s:
        req = mt.requests_df(s, [user["employee_id"]], year)
        balances = balance_service.list_for_employee(s, user["employee_id"], year)
        bal_rows = [{"Leave type": b.leave_type.name, "Entitled": float(b.total), "Used": float(b.used),
                     "Pending": float(b.pending), "Available": float(b.available)} for b in balances]
    
    counts = mt.status_counts(req)
    bal = pd.DataFrame(bal_rows)
    
    # 1. Clean KPI Cards for high-level overview
    ui.kpi_cards([
        ("Available leave", f"{bal['Available'].sum():g} days" if not bal.empty else "—", f"Across tracked types, {year}", "good"),
        ("Pending requests", counts.get("pending", 0), "Awaiting approval", "warn" if counts.get("pending", 0) else ""),
        ("Approved requests", counts.get("approved", 0), f"In {year}", ""),
        ("Rejected requests", counts.get("rejected", 0), f"In {year}", "bad" if counts.get("rejected", 0) else "")
    ])
    
    st.write("")
    ui.page_link("views/request_leave.py", "Request leave", ":material/add_circle:")
    st.write("")

    # 2. Balances with Progress Bars (Replaces Pie/Bar charts)
    ui.section("Leave balances")
    if not bal.empty:
        max_entitled = float(bal["Entitled"].max() or 1)
        st.dataframe(
            bal, 
            hide_index=True, 
            use_container_width=True, 
            column_config={
                "Available": st.column_config.ProgressColumn(
                    "Available Days", 
                    min_value=0, 
                    max_value=max_entitled, 
                    format="%g"
                )
            }
        )
    else:
        st.info("No leave balance records found for this year.")

    # 3. Clean, tabular recent history
    c1, c2 = st.columns(2)
    with c1:
        ui.section("Recent requests")
        if not req.empty:
            recent = req.sort_values("submitted_at", ascending=False).head(5)
            ui.show_table(format_requests(recent).drop(columns=["Submitted"], errors="ignore"), "Status")
        else:
            st.info("No recent requests.")
            
    with c2:
        ui.section("Upcoming approved leave")
        if not req.empty:
            up = req[(req["status"] == "APPROVED") & (req["end_date"].dt.date >= today)].sort_values("start_date")
            if not up.empty:
                ui.show_table(format_requests(up.head(5))[["ID", "Leave type", "From", "To", "Days"]])
            else:
                st.info("No upcoming approved leave.")
        else:
            st.info("No upcoming approved leave.")