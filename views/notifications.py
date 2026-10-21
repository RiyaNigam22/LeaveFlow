from html import escape

import streamlit as st

from auth.session import require_login
from database.connection import session_scope
from services import notification_service as ns
from utils import ui
from utils.dates import fmt_dt

user = require_login()
ui.page_header("Notifications", "Updates about your requests and approvals")

with ui.guard():
    with session_scope() as s:
        items = [(n.id, n.title, n.message, n.is_read, fmt_dt(n.created_at))
                 for n in ns.list_for_user(s, user["user_id"], limit=100)]
    unread = sum(1 for i in items if not i[3])
    top = st.columns([3, 1])
    only_unread = top[0].toggle(f"Show unread only ({unread})", value=False)
    if top[1].button("Mark all as read", disabled=not unread, width="stretch"):
        ui.run_action(lambda s: ns.mark_all_read(s, user["user_id"]))
        st.rerun()
    shown = [i for i in items if not (only_unread and i[3])]
    if not shown:
        st.info("You have no notifications.")
    for nid, title, message, is_read, when in shown:
        c1, c2 = st.columns([8, 1])
        c1.markdown(
            f'<div class="lf-note {"" if is_read else "unread"}"><div class="title">{escape(title)}'
            f'{"" if is_read else " &nbsp;<span class=lf-badge style=color:#175CD3;background:#D1E9FF>New</span>"}</div>'
            f'<div>{escape(message)}</div><div class="meta">{when}</div></div>', unsafe_allow_html=True)
        if not is_read and c2.button("Mark read", key=f"read_{nid}"):
            ui.run_action(lambda s, nid=nid: ns.mark_read(s, user["user_id"], nid))
            st.rerun()
