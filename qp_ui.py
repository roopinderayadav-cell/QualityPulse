"""Look & feel and small building blocks.  All user-entered text is HTML-escaped."""
from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st

NAVY, TEAL, INK, MUTED, LINE = "#0B1F3A", "#0F766E", "#0F172A", "#64748B", "#E2E8F0"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{ font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
[data-testid="stSidebar"] {{ background-color: {NAVY}; }}
[data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color: #CBD5E1; }}
[data-testid="stSidebarNav"] a span, [data-testid="stSidebarNav"] span {{ color: #E2E8F0; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background-color: #134E4A; }}
.qp-title {{ font-size: 1.7rem; font-weight: 700; color: {INK}; line-height: 1.2; }}
.qp-sub {{ color: {MUTED}; font-size: .92rem; margin: 2px 0 12px 0; }}
.qp-chip {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:700; margin-right:4px; }}
.qp-card {{ background:#fff; border:1px solid {LINE}; border-radius:14px; padding:16px 18px; }}
.qp-kpi .l {{ color:{MUTED}; font-size:.74rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
.qp-kpi .v {{ font-family:'IBM Plex Mono', monospace; font-size:1.8rem; color:{INK}; margin-top:4px; }}
.qp-kpi .f {{ color:{MUTED}; font-size:.78rem; margin-top:2px; }}
.qp-score {{ font-family:'IBM Plex Mono', monospace; font-size:2.6rem; font-weight:600; line-height:1; color:{INK}; }}
table.qp-t {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
table.qp-t th {{ text-align:left; color:{MUTED}; font-size:.72rem; letter-spacing:.06em; text-transform:uppercase;
  padding:8px 10px; border-bottom:1px solid {LINE}; }}
table.qp-t td {{ padding:10px; border-bottom:1px solid #EEF2F6; vertical-align:top; }}
table.qp-t tr.miss td {{ background:#FFF7ED; }}
table.qp-t tr.disp td {{ box-shadow: inset 3px 0 0 #EA580C; }}
.qp-msg {{ border-radius:12px; padding:10px 12px; margin-bottom:8px; font-size:.9rem; line-height:1.45; }}
.qp-msg .who {{ font-weight:700; font-size:.8rem; }}
.qp-msg .when {{ color:{MUTED}; font-size:.75rem; margin-left:6px; }}
.qp-note {{ border:1px solid {LINE}; background:#F8FAFC; border-radius:12px; padding:12px 14px; font-size:.9rem; }}
/* teal primary even when .streamlit/config.toml is missing */
button[kind="primary"], button[kind="primaryFormSubmit"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  background-color: {TEAL} !important; border-color: {TEAL} !important; color: #fff !important; }}
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background-color: #115E59 !important; border-color: #115E59 !important; }}
.stMultiSelect [data-baseweb="tag"], span[data-baseweb="tag"] {{ background-color: {TEAL} !important; }}
@media (max-width: 640px) {{ .qp-score {{ font-size:2rem; }} .block-container {{ padding-left:.8rem; padding-right:.8rem; }} }}
</style>
"""

RESULT_CHIP = {"Pass": ("#166534", "#DCFCE7"), "Fail": ("#FFFFFF", "#B91C1C"), "Not scorable": ("#334155", "#E2E8F0")}
ANSWER_CHIP = {"yes": ("Yes", "#166534", "#DCFCE7"), "no": ("No", "#9A3412", "#FED7AA"), "na": ("N/A", "#334155", "#E2E8F0")}
STATUS = {"feedback_sent": ("Awaiting agent", "#1E3A8A", "#DBEAFE"), "acknowledged": ("Acknowledged", "#166534", "#DCFCE7"),
          "disputed": ("Disputed", "#9A3412", "#FFEDD5"), "closed": ("Closed", "#334155", "#E2E8F0")}
ROLE_LABEL = {"qa_admin": "QA admin", "auditor": "Auditor", "team_lead": "Team lead", "agent": "Agent"}
ROLE_BG = {"qa_admin": "#F0FDFA", "auditor": "#F0FDFA", "team_lead": "#EFF6FF", "agent": "#FFF7ED"}


def e(v) -> str:
    return escape("" if v is None else str(v))


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def chip(text, fg, bg) -> str:
    return f'<span class="qp-chip" style="color:{fg};background:{bg}">{e(text)}</span>'


def result_chip(result: str) -> str:
    fg, bg = RESULT_CHIP.get(result, RESULT_CHIP["Not scorable"])
    return chip(result.upper(), fg, bg)


def status_chip(status: str, overdue: bool = False) -> str:
    label, fg, bg = STATUS.get(status, (status, "#334155", "#E2E8F0"))
    out = chip(label, fg, bg)
    if overdue:
        out += chip("OVERDUE", "#FFFFFF", "#B91C1C")
    return out


def header(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="qp-title">{e(title)}</div><div class="qp-sub">{e(sub)}</div>', unsafe_allow_html=True)


def kpi(col, label: str, value: str, foot: str = "") -> None:
    col.markdown(f'<div class="qp-card qp-kpi"><div class="l">{e(label)}</div><div class="v">{e(value)}</div>'
                 f'<div class="f">{e(foot)}</div></div>', unsafe_allow_html=True)


def when(s: str | None) -> str:
    if not s:
        return "—"
    d = datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    secs = (datetime.now() - d).total_seconds()
    if 0 <= secs < 3600:
        return f"{max(1, int(secs // 60))} min ago"
    if 0 <= secs < 86400:
        return f"{int(secs // 3600)} h ago"
    return d.strftime("%d %b %Y, %H:%M")
