"""Shared Streamlit UI helpers: theme, KPI cards, status badges, safe error handling."""
import logging
from contextlib import contextmanager
from html import escape

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import RerunException, StopException

import config
from utils.errors import LeaveFlowError

log = logging.getLogger("leaveflow")

PRIMARY = "#1F4E79"
PALETTE = ["#1F4E79", "#2E86AB", "#6C8EAD", "#F18F01", "#C73E1D", "#7B9E87", "#8D6A9F", "#A0A0A0"]

STATUS_STYLE = {   # label, text colour, background
    "DRAFT": ("Draft", "#475467", "#EAECF0"),
    "SUBMITTED": ("Submitted", "#175CD3", "#D1E9FF"),
    "MANAGER_PENDING": ("Pending: Manager", "#B54708", "#FEF0C7"),
    "HR_PENDING": ("Pending: HR", "#B54708", "#FEF0C7"),
    "DEPARTMENT_HEAD_PENDING": ("Pending: Dept Head", "#B54708", "#FEF0C7"),
    "APPROVED": ("Approved", "#067647", "#D1FADF"),
    "REJECTED": ("Rejected", "#B42318", "#FEE4E2"),
    "CANCELLED": ("Cancelled", "#475467", "#EAECF0"),
    # approval step statuses
    "PENDING": ("Pending", "#B54708", "#FEF0C7"),
    "WAITING": ("Waiting", "#475467", "#EAECF0"),
    "SKIPPED": ("Not required", "#475467", "#EAECF0"),
}

THEMES = {
    "Cloud": {"bg":"#e9eff5", "panel":"#f2f6fa", "ink":"#27364a", "muted":"#65768b", "accent":"#52677e", "border":"#d9e2ec", "light":"#ffffff", "dark":"#cdd8e3", "chart":["#52677e","#8598ad","#b4a8c9","#88a8a4","#c5a888","#8e92ac"]},
    "Midnight": {"bg":"#222b37", "panel":"#2d3947", "ink":"#eef2f7", "muted":"#b3c0ce", "accent":"#809bb7", "border":"#465466", "light":"#394758", "dark":"#19212b", "chart":["#9ab4cf","#c0a6c8","#82aaa5","#d0b68e","#a7aeca","#738fa4"]},
    "Lavender": {"bg":"#eeebf5", "panel":"#f7f5fb", "ink":"#352f49", "muted":"#786f8d", "accent":"#786b99", "border":"#ded7ea", "light":"#ffffff", "dark":"#d6cfe3", "chart":["#786b99","#b09dc1","#8caaa8","#c1a8b5","#a6a0c8","#9f9bb1"]},
}


def theme_name() -> str:
    return st.session_state.get("lf_theme", "Cloud")


def theme_colors() -> dict:
    return THEMES.get(theme_name(), THEMES["Cloud"])


def inject_css() -> None:
    from pathlib import Path
    css_file = Path(__file__).resolve().parent.parent / "frontend" / "styles" / "design.css"
    css = css_file.read_text(encoding="utf-8")
    c = theme_colors()
    variables = ";".join(f"--lf-{k}:{v}" for k,v in c.items() if isinstance(v,str))
    st.markdown(f"<style>:root{{{variables}}}{css}</style>", unsafe_allow_html=True)


def theme_picker() -> None:
    choice = st.selectbox("Appearance", list(THEMES), key="lf_theme", help="Choose one consistent color theme across LeaveFlow")
    return choice


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="lf-header"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="lf-section">{escape(title)}</div>', unsafe_allow_html=True)


def kpi_cards(items: list[tuple], cols: int | None = None) -> None:
    """items: (label, value, note="", tone="") – tone in {"", "good", "warn", "bad"}."""
    n = max(1, min(cols or len(items), 4))
    for offset in range(0, len(items), n):
        columns = st.columns(min(n, len(items)-offset))
        for col, item in zip(columns, items[offset:offset+n]):
            label, value, note, tone = (list(item) + ["", ""])[:4]
            col.markdown(
                f'<div class="lf-kpi {escape(str(tone))}"><div class="label">{escape(str(label))}</div>'
                f'<div class="value">{escape(str(value))}</div><div class="note">{escape(str(note))}&nbsp;</div></div>',
                unsafe_allow_html=True)


def status_label(status: str) -> str:
    return STATUS_STYLE.get(status, (status.title(), "", ""))[0]


def status_badge(status: str) -> str:
    label, fg, bg = STATUS_STYLE.get(status, (status.title(), "#475467", "#EAECF0"))
    return f'<span class="lf-badge" style="color:{fg};background:{bg}">{escape(label)}</span>'


def style_status(df: pd.DataFrame, column: str = "Status"):
    """Pandas Styler colouring a (label) status column – used for st.dataframe tables."""
    by_label = {lbl: (fg, bg) for lbl, fg, bg in STATUS_STYLE.values()}

    def colour(v):
        fg, bg = by_label.get(v, ("", ""))
        return f"color:{fg};background-color:{bg};font-weight:600" if fg else ""
    return df.style.map(colour, subset=[column])


def show_table(df: pd.DataFrame, status_col: str | None = None, height: int | None = None, **kwargs) -> None:
    if df.empty:
        st.info("No records to display.")
        return
    data = style_status(df, status_col) if status_col and status_col in df.columns else df
    if height:
        kwargs["height"] = height
    st.dataframe(data, hide_index=True, width="stretch", **kwargs)


def style_figure(fig, height: int = 320):
    c = theme_colors()
    fig.update_layout(height=height, margin=dict(l=15, r=15, t=45, b=25),
                      font=dict(family="Inter, sans-serif", size=12, color=c["ink"]),
                      title=dict(font=dict(size=14, color=c["ink"])),
                      plot_bgcolor=c["panel"], paper_bgcolor=c["panel"],
                      legend=dict(orientation="h", yanchor="bottom", y=-0.32, x=0), colorway=c["chart"])
    fig.update_xaxes(showgrid=False, linecolor=c["border"], tickfont=dict(color=c["muted"]))
    fig.update_yaxes(gridcolor=c["border"], zeroline=False, tickfont=dict(color=c["muted"]))
    return fig


def chart(fig, key: str | None = None) -> None:
    st.plotly_chart(style_figure(fig), width="stretch", key=key)


# --- error handling -----------------------------------------------------------------------------------

GENERIC_ERROR = "Something went wrong while processing your request. Please try again; if the problem persists contact support."


def run_action(fn, success: str | None = None):
    """Run a service call inside a transaction. Business errors are shown verbatim; anything else is
    logged and replaced by a generic message – raw database errors never reach the user.
    Returns (ok, result)."""
    from database.connection import session_scope
    try:
        with session_scope() as session:
            result = fn(session)
        if success:
            st.success(success)
        return True, result
    except LeaveFlowError as exc:
        st.error(str(exc))
    except (RerunException, StopException):
        raise
    except Exception:
        log.exception("Unhandled error in action")
        st.error(GENERIC_ERROR)
    return False, None


@contextmanager
def guard():
    """Wrap page rendering so that unexpected exceptions become a friendly message."""
    try:
        yield
    except (RerunException, StopException):
        raise
    except LeaveFlowError as exc:
        st.error(str(exc))
    except Exception:
        log.exception("Unhandled error while rendering page")
        st.error(GENERIC_ERROR)


def fmt_local(series: pd.Series, fmt: str = "%d %b %Y %H:%M") -> pd.Series:
    return series.dt.tz_convert(config.APP_TIMEZONE).dt.strftime(fmt).fillna("—")


def fmt_hours(h: float) -> str:
    if not h:
        return "0 h"
    return f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} d"


def page_link(path: str, label: str, icon: str | None = None) -> None:
    """Navigation shortcut that degrades silently if the target page is not registered."""
    from streamlit.errors import StreamlitPageNotFoundError
    path = path.replace("pages/", "views/")
    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitPageNotFoundError:
        pass
