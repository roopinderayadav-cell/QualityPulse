"""QualityPulse – quality audit demo (Ops Suite).   Streamlit main file: app.py

All files sit in ONE folder so the whole app can be uploaded to GitHub in one drag-and-drop.
"""
import hmac
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
st.set_page_config(page_title="QualityPulse", page_icon=str(ROOT / "qp_icon.svg"), layout="wide",
                   initial_sidebar_state="auto")

import qp_db as D  # noqa: E402
import qp_repo as R  # noqa: E402
import qp_ui as U  # noqa: E402
import qp_views as V  # noqa: E402

U.apply()
st.logo(str(ROOT / "qp_logo.svg"), icon_image=str(ROOT / "qp_icon.svg"), size="large")


def secret(name):
    v = os.environ.get(name)
    if v:
        return v
    try:
        return st.secrets.get(name)
    except Exception:
        return None


@st.cache_resource(show_spinner="Preparing the demo data…")
def boot():
    D.ensure()
    return True


# ---- optional shared access code for private demos
code = secret("APP_ACCESS_CODE")
if code and not st.session_state.get("gate_ok"):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### QualityPulse")
        st.caption("Private demonstration. Enter the access code you were given.")
        with st.form("gate"):
            entered = st.text_input("Access code", type="password")
            if st.form_submit_button("Continue", type="primary", width="stretch"):
                if hmac.compare_digest(entered.encode(), str(code).encode()):
                    st.session_state.gate_ok = True
                    st.rerun()
                st.error("That code is not correct.")
    st.stop()

boot()
people = R.users()
by_id = {u["id"]: u for u in people}
if st.session_state.get("viewer") not in by_id:
    st.session_state.viewer = people[0]["id"]

with st.sidebar:
    st.caption("DEMO SIGN-IN · view the app as")

    # labels must stay the same between reruns (a changing label resets the choice)
    st.selectbox("Person", list(by_id), key="viewer", format_func=lambda uid: by_id[uid]["name"],
                 label_visibility="collapsed")
viewer = by_id[st.session_state.viewer]
role = viewer["role"]


def page(fn, title, icon, url, default=False):
    def run():
        fn(viewer)
    run.__name__ = url.replace("-", "_")
    return st.Page(run, title=title, icon=icon, url_path=url, default=default)


unread = R.unread_count(viewer["id"])
inbox_title = f"Inbox ({unread})" if unread else "Inbox"
if role == "agent":
    pages = [page(V.inbox, inbox_title, ":material/notifications:", "inbox", True),
             page(V.my_audits, "My audits", ":material/fact_check:", "my-audits"),
             page(V.how_it_works, "How it works", ":material/help:", "how")]
elif role == "auditor":
    pages = [page(V.new_audit, "New audit", ":material/edit_note:", "new-audit", True),
             page(V.all_audits, "Audits", ":material/fact_check:", "audits"),
             page(V.inbox, inbox_title, ":material/notifications:", "inbox"),
             page(V.how_it_works, "How it works", ":material/help:", "how")]
elif role == "team_lead":
    pages = [page(V.dashboard, "Quality dashboard", ":material/monitoring:", "dashboard", True),
             page(V.disputes, "Disputes", ":material/gavel:", "disputes"),
             page(V.all_audits, "Audits", ":material/fact_check:", "audits"),
             page(V.inbox, inbox_title, ":material/notifications:", "inbox"),
             page(V.how_it_works, "How it works", ":material/help:", "how")]
else:  # qa_admin
    pages = [page(V.dashboard, "Quality dashboard", ":material/monitoring:", "dashboard", True),
             page(V.new_audit, "New audit", ":material/edit_note:", "new-audit"),
             page(V.all_audits, "Audits", ":material/fact_check:", "audits"),
             page(V.disputes, "Disputes", ":material/gavel:", "disputes"),
             page(V.form_builder, "Form builder", ":material/tune:", "forms"),
             page(V.inbox, inbox_title, ":material/notifications:", "inbox"),
             page(V.how_it_works, "How it works", ":material/help:", "how")]

nav = st.navigation(pages)
with st.sidebar:
    st.caption(f"Role: {U.ROLE_LABEL[role]}" + (f" · {viewer.get('process') or ''}" if role == 'agent' else ""))
    st.divider()
    st.caption(":material/science: Synthetic demo data · Ops Suite")
    if role == "qa_admin":
        if st.button("Reset demo data", icon=":material/restart_alt:"):
            D.ensure(force=True)
            st.session_state.clear()
            st.rerun()
nav.run()
