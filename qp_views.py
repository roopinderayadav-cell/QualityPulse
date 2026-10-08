"""QualityPulse pages."""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import qp_repo as R
import qp_scoring as S
import qp_ui as U
from qp_ui import e


# =============================================================================== audit detail (shared)
def audit_detail(audit_id: int, viewer: dict, key: str) -> None:
    try:
        d = R.audit_detail(audit_id)
    except LookupError:
        st.warning("That audit no longer exists.")
        return
    a, f, lines = d["audit"], d["form"], d["lines"]
    R.mark_read(viewer["id"], audit_id)
    dispute = d["disputes"][-1] if d["disputes"] else None
    disputed_ids = set(json.loads(dispute["param_ids"])) if dispute else set()

    with st.container(border=True):
        top_l, top_r = st.columns([2.2, 1])
        with top_l:
            st.markdown(f'<div class="qp-title" style="font-size:1.35rem">{e(a["txn_ref"])} · {e(a["form"])} '
                        f'<span style="color:#64748B;font-weight:500">v{a["form_version"]}</span></div>'
                        f'<div class="qp-sub">Agent <b>{e(a["agent"])}</b> · Auditor {e(a["auditor"])} · {e(a["process"])}'
                        f' · transaction date {e(a["txn_date"])} · audited {e(U.when(a["created_at"]))}</div>'
                        f'{U.status_chip(a["status"], a["overdue"])}'
                        + (U.chip(a["outcome"], "#334155", "#F1F5F9") if a["outcome"] else ""),
                        unsafe_allow_html=True)
            if a["status"] == "feedback_sent":
                st.caption(f"Acknowledge or dispute by {a['ack_due_at'][:16]}" + (" – overdue, team lead alerted." if a["overdue"] else "."))
        with top_r:
            fatal = U.chip("FATAL ERROR", "#FFFFFF", "#7F1D1D") if a["fatal_failed"] else ""
            score = "—" if a["score"] is None else f"{a['score']:.1f}%"
            hist = d["history"]
            earned = sum(l["weight"] for l in lines if l["answer"] == "yes")
            applicable = sum(l["weight"] for l in lines if l["answer"] != "na")
            pts = f"{earned:g} of {applicable:g} applicable points"
            st.markdown(f'<div style="text-align:right"><div class="qp-score">{score}</div>'
                        f'<div style="margin-top:6px">{U.result_chip(a["result"])}{fatal}</div>'
                        f'<div class="qp-sub" style="margin:6px 0 0 0">{pts} · pass mark {f["pass_mark"]:g}%'
                        + (f' · version {a["version"]}' if a["version"] > 1 else "") + '</div></div>',
                        unsafe_allow_html=True)
            if len(hist) > 1:
                st.caption(f"Originally {hist[0]['score']}% · {hist[0]['result']}")

        rows = []
        for ln in lines:
            label, fg, bg = U.ANSWER_CHIP[ln["answer"]]
            pts = "—" if ln["answer"] == "na" else (f"{ln['weight']:g}" if ln["answer"] == "yes" else "0")
            cls = []
            if ln["answer"] == "no":
                cls.append("miss")
            if ln["param_id"] in disputed_ids:
                cls.append("disp")
            fatal = U.chip("FATAL", "#991B1B", "#FEE2E2") if ln["is_fatal"] else ""
            disp = U.chip("DISPUTED", "#9A3412", "#FFEDD5") if ln["param_id"] in disputed_ids else ""
            rows.append(f'<tr class="{" ".join(cls)}"><td style="color:#64748B">{e(ln["section"])}</td>'
                        f'<td title="{e(ln["guidance"])}"><b>{e(ln["name"])}</b> {fatal}{disp}</td>'
                        f'<td style="font-family:IBM Plex Mono,monospace">{ln["weight"]:g}</td>'
                        f'<td>{U.chip(label, fg, bg)}</td><td style="font-family:IBM Plex Mono,monospace">{pts}</td>'
                        f'<td>{e(ln["comment"]) or "<span style=color:#94A3B8>–</span>"}</td></tr>')
        st.markdown('<table class="qp-t"><tr><th style="width:110px">Section</th><th style="width:26%">Parameter</th>'
                    '<th>Weight</th><th>Answer</th><th>Points</th><th style="width:40%">QA comment</th></tr>' + "".join(rows) + "</table>", unsafe_allow_html=True)
        if d["overall"]:
            st.markdown(f'<div class="qp-note" style="margin-top:12px"><b>Auditor\'s overall feedback:</b> {e(d["overall"])}</div>',
                        unsafe_allow_html=True)

    # ---- dispute box
    if dispute:
        with st.container(border=True):
            st.markdown(f"**Dispute** · raised by {dispute['raised_by_name']} · {U.when(dispute['created_at'])} · "
                        f"status **{dispute['status'].title()}**")
            st.markdown(f'<div class="qp-note">{e(dispute["reason"])}</div>', unsafe_allow_html=True)
            if dispute["status"] != "open":
                st.markdown(f"**Decision by {dispute['decided_by_name']}:** {dispute['decision_note']}")

    # ---- actions
    if viewer["role"] == "agent" and viewer["id"] == a["agent_id"] and a["status"] == "feedback_sent":
        _agent_actions(a, lines, viewer, key)
    if viewer["role"] in R.REVIEWER_ROLES and dispute and dispute["status"] == "open":
        _decision_panel(dispute, lines, viewer, key)

    # ---- conversation
    with st.container(border=True):
        st.markdown("**Discussion**")
        if not d["messages"]:
            st.caption("No messages yet.")
        for m in d["messages"]:
            bg = U.ROLE_BG.get(m["role"], "#F8FAFC")
            st.markdown(f'<div class="qp-msg" style="background:{bg}"><span class="who">{e(m["author"])}</span>'
                        f'<span class="when">{e(U.ROLE_LABEL.get(m["role"], ""))} · {e(U.when(m["created_at"]))}</span>'
                        f'<div>{e(m["body"])}</div></div>', unsafe_allow_html=True)
        involved = viewer["id"] in (a["agent_id"], a["auditor_id"]) or viewer["role"] in R.REVIEWER_ROLES
        if involved and a["status"] != "acknowledged":
            with st.form(f"msg_{key}_{audit_id}", clear_on_submit=True):
                body = st.text_area("Add to the discussion", height=80, placeholder="Write a message…")
                if st.form_submit_button("Send", icon=":material/send:"):
                    try:
                        R.add_message(audit_id, viewer["id"], body)
                        st.toast("Message sent")
                        st.rerun()
                    except ValueError as ex:
                        st.error(str(ex))

    if len(d["history"]) > 1:
        with st.expander("Score history (every change is kept)"):
            st.dataframe(pd.DataFrame([{"Version": h["version"], "Score %": h["score"], "Result": h["result"],
                                        "Changed by": h["changed_by_name"], "Reason": h["reason"], "When": h["created_at"]}
                                       for h in d["history"]]), hide_index=True, width="stretch")


def _agent_actions(a, lines, viewer, key):
    with st.container(border=True):
        st.markdown("**Your response**")
        c1, c2 = st.columns(2)
        with c1:
            with st.form(f"ack_{key}_{a['id']}"):
                note = st.text_input("Comment (optional)", placeholder="e.g. Understood, will add the remark going forward")
                if st.form_submit_button("Acknowledge feedback", type="primary", icon=":material/check_circle:", width="stretch"):
                    try:
                        R.acknowledge(a["id"], viewer["id"], note)
                        st.toast("Acknowledged – thank you")
                        st.rerun()
                    except (ValueError, PermissionError) as ex:
                        st.error(str(ex))
        with c2:
            with st.form(f"disp_{key}_{a['id']}"):
                names = {l["param_id"]: f"{l['name']} ({S.ANSWER_LABEL[l['answer']]})" for l in lines}
                default = [l["param_id"] for l in lines if l["answer"] == "no"][:1]
                pick = st.multiselect("Parameters you disagree with", list(names), default=default, format_func=names.get)
                reason = st.text_area("Why? Add facts the auditor can check", height=80)
                if st.form_submit_button("Raise dispute", icon=":material/gavel:", width="stretch"):
                    try:
                        R.raise_dispute(a["id"], viewer["id"], reason, pick)
                        st.toast("Dispute sent to QA")
                        st.rerun()
                    except (ValueError, PermissionError) as ex:
                        st.error(str(ex))


def _decision_panel(dispute, lines, viewer, key):
    ids = json.loads(dispute["param_ids"])
    by_id = {l["param_id"]: l for l in lines}
    with st.container(border=True):
        st.markdown("**Decide this dispute**")
        with st.form(f"decide_{key}_{dispute['id']}"):
            decision = st.radio("Decision", ["upheld", "overturned"], horizontal=True,
                                format_func={"upheld": "Uphold – score stands", "overturned": "Overturn – change the answer"}.get)
            changes = {}
            for pid in ids:
                ln = by_id.get(pid)
                if not ln:
                    continue
                opts = list(S.ANSWERS)
                changes[pid] = st.selectbox(f"New answer for '{ln['name']}' (only used when overturning)", opts,
                                            index=0 if ln["answer"] != "yes" else 1, format_func=S.ANSWER_LABEL.get,
                                            key=f"chg_{key}_{dispute['id']}_{pid}")
            note = st.text_area("Reason for the decision (the agent will see this)", height=80)
            if st.form_submit_button("Submit decision", type="primary", icon=":material/task_alt:"):
                try:
                    R.decide_dispute(dispute["id"], viewer["id"], decision, note,
                                     changes if decision == "overturned" else None)
                    st.toast("Decision saved – agent notified")
                    st.rerun()
                except (ValueError, PermissionError) as ex:
                    st.error(str(ex))


def _pick_audit(d: pd.DataFrame, key: str) -> int | None:
    """Clickable table; returns the chosen audit id."""
    if d.empty:
        return None
    show = pd.DataFrame({
        "Transaction": d["txn_ref"], "Process": d["process"], "Agent": d["agent"],
        "Audited": d["created_at"].dt.strftime("%d %b %H:%M"), "Score %": d["score"], "Result": d["result"],
        "Fatal": d["fatal_failed"].map({1: "Yes", 0: ""}),
        "Status": [("Overdue" if o else U.STATUS[s][0]) for s, o in zip(d["status"], d["overdue"])],
    })
    ev = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key=f"tbl_{key}", height=min(420, 38 + 35 * len(show)),
                      column_config={"Score %": st.column_config.NumberColumn(format="%.1f")})
    rows = ev.selection.rows if ev and ev.selection else []
    if rows:
        st.session_state[f"sel_{key}"] = int(d.iloc[rows[0]]["id"])
    sel = st.session_state.get(f"sel_{key}")
    return sel if sel in set(d["id"].astype(int)) else None


# =============================================================================== agent pages
def inbox(viewer: dict) -> None:
    U.header("Inbox", "Audit results, dispute decisions and new comments")
    notes = R.notifications(viewer["id"])
    if not notes:
        st.info("Nothing here yet.", icon=":material/inbox:")
        return
    left, right = st.columns([1, 2.1])
    with left:
        if st.button("Mark all as read", icon=":material/done_all:"):
            R.mark_read(viewer["id"])
            st.rerun()
        for n in notes[:30]:
            unread = n["read_at"] is None
            label = ("● " if unread else "") + n["title"]
            if st.button(f"{label}\n\n{n['txn_ref'] or ''} · {U.when(n['created_at'])}", key=f"n_{n['id']}",
                         width="stretch", type="primary" if unread else "secondary"):
                st.session_state["inbox_audit"] = n["audit_id"]
                st.rerun()
    with right:
        aid = st.session_state.get("inbox_audit") or notes[0]["audit_id"]
        if aid:
            audit_detail(int(aid), viewer, "inbox")


def my_audits(viewer: dict) -> None:
    U.header("My audits", "Every audit of your work, with full feedback")
    d = R.audits("a.agent_id = ?", (viewer["id"],))
    if d.empty:
        st.info("No audits yet.")
        return
    c = st.columns(4)
    U.kpi(c[0], "Audits", f"{len(d)}")
    U.kpi(c[1], "Average score", f"{d['score'].mean():.1f}%")
    U.kpi(c[2], "Pass rate", f"{(d['result'] == 'Pass').mean():.0%}")
    U.kpi(c[3], "Waiting for you", f"{int((d['status'] == 'feedback_sent').sum())}")
    st.write("")
    aid = _pick_audit(d, "mine")
    st.caption("Select a row to open the full feedback.")
    if aid:
        audit_detail(aid, viewer, "mine")


# =============================================================================== QA pages
def new_audit(viewer: dict) -> None:
    U.header("New audit", "Choose the process, answer every parameter, and the system calculates the result")
    procs = R.processes()
    pmap = {p["id"]: p for p in procs}
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
    pid = c1.selectbox("Process", list(pmap), format_func=lambda i: f"{pmap[i]['name']} · {pmap[i]['location']}")
    f = R.active_form(pid)
    if not f:
        st.warning("This process has no audit form yet. A QA admin can create one in Form builder.")
        return
    agents = R.agents(pid)
    if not agents:
        st.warning("No agents are mapped to this process.")
        return
    amap = {a["id"]: a["name"] for a in agents}
    agent_id = c2.selectbox("Agent", list(amap), format_func=amap.get)
    txn = c3.text_input("Transaction ref", placeholder="PNR / ticket / call ID", max_chars=30)
    txn_date = c4.date_input("Transaction date", value=date.today(), max_value=date.today())
    params = R.form_params(f["id"])
    st.caption(f"Form: **{f['name']} v{f['version']}** · pass mark {f['pass_mark']:g}% · "
               f"{'fatal error fails the audit' if f['fatal_rule'] == 'fail_only' else 'fatal error sets the score to 0'}")

    answers, comments = {}, {}
    left, right = st.columns([2.2, 1])
    with left:
        section = None
        for p in params:
            if p["section"] != section:
                section = p["section"]
                st.markdown(f"##### {section}")
            with st.container(border=True):
                a, b = st.columns([1.3, 1])
                with a:
                    st.markdown(f"**{p['name']}**" + ("  :red-background[FATAL]" if p["is_fatal"] else "") +
                                f"  \n:gray[{p['guidance'] or ''} · weight {p['weight']:g}]")
                with b:
                    answers[p["id"]] = st.segmented_control("Answer", list(S.ANSWERS), format_func=S.ANSWER_LABEL.get,
                                                            key=f"ans_{f['id']}_{p['id']}", label_visibility="collapsed")
                comments[p["id"]] = st.text_input(
                    "QA comment", key=f"com_{f['id']}_{p['id']}", label_visibility="collapsed",
                    placeholder="Comment for the agent (required when No; optional praise or tips when Yes)")
        overall = st.text_area("Overall feedback for the agent", height=90, key=f"overall_{f['id']}")
    with right:
        with st.container(border=True):
            st.markdown("**Live result**")
            done = {k: v for k, v in answers.items() if v}
            if len(done) < len(params):
                st.caption(f"{len(done)} of {len(params)} parameters answered")
                st.progress(len(done) / len(params))
            if done:
                part = [p for p in params if p["id"] in done]
                r = S.calculate(part, done, f["pass_mark"], f["fatal_rule"])
                score = "—" if r.score is None else f"{r.score:.1f}%"
                st.markdown(f'<div class="qp-score">{score}</div><div style="margin-top:6px">{U.result_chip(r.result)}'
                            + (U.chip("FATAL", "#FFFFFF", "#7F1D1D") if r.fatal_failed else "") +
                            f'</div><div class="qp-sub">{r.earned:g} of {r.applicable:g} applicable points</div>',
                            unsafe_allow_html=True)
                if r.missed:
                    st.caption("Missed: " + ", ".join(r.missed))
            ready = len(done) == len(params)
            if st.button("Submit audit & notify agent", type="primary", disabled=not ready, width="stretch",
                         icon=":material/send:"):
                try:
                    aid = R.submit_audit(f["id"], agent_id, viewer["id"], txn, txn_date.isoformat(), answers, comments, overall)
                    for p in params:
                        for k in (f"ans_{f['id']}_{p['id']}", f"com_{f['id']}_{p['id']}"):
                            st.session_state.pop(k, None)
                    st.session_state.pop(f"overall_{f['id']}", None)
                    st.session_state["last_submitted"] = aid
                    st.rerun()
                except ValueError as ex:
                    st.error(str(ex))
            if not ready:
                st.caption("Answer every parameter to submit.")
    last = st.session_state.get("last_submitted")
    if last:
        st.success(f"Audit saved and sent to {R.audit_detail(last)['audit']['agent']}. They have been notified.",
                   icon=":material/mark_email_read:")


def all_audits(viewer: dict) -> None:
    U.header("Audits", "Every audit with its status · select one to see the full feedback and discussion")
    d = R.audits()
    if viewer["role"] == "auditor":
        mine = st.toggle("Only my audits", value=True)
        if mine:
            d = d[d["auditor_id"] == viewer["id"]]
    c1, c2, c3 = st.columns(3)
    proc = c1.multiselect("Process", sorted(d["process"].unique()))
    status = c2.multiselect("Status", ["Awaiting agent", "Overdue", "Disputed", "Acknowledged", "Closed"])
    result = c3.multiselect("Result", ["Pass", "Fail"])
    if proc:
        d = d[d["process"].isin(proc)]
    if status:
        lab = [("Overdue" if o else U.STATUS[s][0]) for s, o in zip(d["status"], d["overdue"])]
        d = d[[x in status for x in lab]]
    if result:
        d = d[d["result"].isin(result)]
    st.caption(f"{len(d)} audits")
    aid = _pick_audit(d, "all")
    if aid:
        audit_detail(aid, viewer, "all")


def disputes(viewer: dict) -> None:
    U.header("Disputes", "Open disputes waiting for a decision")
    rows = R.open_disputes()
    if not rows:
        st.success("No open disputes.", icon=":material/verified:")
        return
    labels = {r["audit_id"]: f"{r['txn_ref']} · {r['agent']} · {r['process']} · {r['score']}% {r['result']} · "
                             f"raised {U.when(r['created_at'])}" for r in rows}
    aid = st.radio("Choose a dispute", list(labels), format_func=labels.get)
    audit_detail(int(aid), viewer, "disp")


# =============================================================================== dashboard
def dashboard(viewer: dict) -> None:
    U.header("Quality dashboard", "Calculated from submitted audits · synthetic demo data")
    d = R.audits()
    c1, c2 = st.columns([2, 1])
    procs = c1.multiselect("Process", sorted(d["process"].unique()))
    days = c2.selectbox("Period", [7, 30, 60, 90], index=2, format_func=lambda x: f"Last {x} days")
    d = d[d["created_at"] >= datetime.now() - timedelta(days=days)]
    if procs:
        d = d[d["process"].isin(procs)]
    if d.empty:
        st.info("No audits in this selection.")
        return
    disp = R.q("select d.status, d.audit_id from disputes d")
    ids = set(d["id"].astype(int))
    dd = [x for x in disp if x["audit_id"] in ids]
    decided = [x for x in dd if x["status"] != "open"]
    responded = d[d["acknowledged_at"].notna()]
    on_time = (pd.to_datetime(responded["acknowledged_at"]) <= pd.to_datetime(responded["ack_due_at"])).mean() if len(responded) else None

    k = st.columns(4)
    U.kpi(k[0], "Audits", f"{len(d)}", f"{d['agent'].nunique()} agents · {d['process'].nunique()} processes")
    U.kpi(k[1], "Average score", f"{d['score'].mean():.1f}%", "current score after disputes")
    U.kpi(k[2], "Pass rate", f"{(d['result'] == 'Pass').mean():.1%}", "audits passed ÷ audits")
    U.kpi(k[3], "Fatal error rate", f"{d['fatal_failed'].mean():.1%}", "audits with a fatal error")
    k = st.columns(4)
    U.kpi(k[0], "Acknowledged on time", "—" if on_time is None else f"{on_time:.0%}", "within 48 hours")
    U.kpi(k[1], "Overdue now", f"{int(d['overdue'].sum())}", "waiting longer than 48 hours")
    U.kpi(k[2], "Open disputes", f"{sum(1 for x in dd if x['status'] == 'open')}", f"{len(dd)} raised in period")
    U.kpi(k[3], "Overturn rate", "—" if not decided else
          f"{sum(1 for x in decided if x['status'] == 'overturned') / len(decided):.0%}", "of decided disputes")
    st.write("")

    left, right = st.columns([1.2, 1])
    with left, st.container(border=True):
        st.markdown("**Average score by week**")
        w = d.assign(week=d["created_at"].dt.to_period("W-SUN").dt.start_time).groupby("week").agg(
            score=("score", "mean"), n=("id", "size")).reset_index()
        fig = go.Figure(go.Scatter(x=w["week"], y=w["score"], mode="lines+markers+text", line=dict(color=U.TEAL, width=3),
                                   text=[f"{v:.1f}" for v in w["score"]], textposition="top center",
                                   customdata=w["n"], hovertemplate="Week of %{x|%d %b}<br>%{y:.1f}% · %{customdata} audits<extra></extra>"))
        fig.update_layout(height=280, margin=dict(l=8, r=8, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[max(0, w["score"].min() - 8), 101], gridcolor="#EEF2F7"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right, st.container(border=True):
        st.markdown("**Most-missed parameters**")
        fp = R.failing_parameters(list(ids)).head(7)
        fp = fp.iloc[::-1]
        fig = go.Figure(go.Bar(x=fp["miss_rate"] * 100, y=[f"{a} · {b}" for a, b in zip(fp["parameter"], fp["process"])],
                               orientation="h", marker_color="#EA580C", text=[f"{v:.0%}" for v in fp["miss_rate"]],
                               textposition="outside", cliponaxis=False,
                               customdata=fp[["missed", "checked"]].values,
                               hovertemplate="%{y}<br>missed %{customdata[0]} of %{customdata[1]}<extra></extra>"))
        fig.update_layout(height=280, margin=dict(l=8, r=30, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(showticklabels=False, showgrid=False))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with st.container(border=True):
        st.markdown("**By agent**")
        g = d.groupby(["agent", "process"]).agg(audits=("id", "size"), avg=("score", "mean"),
                                                 pass_rate=("result", lambda s: (s == "Pass").mean()),
                                                 fatal=("fatal_failed", "sum"),
                                                 waiting=("status", lambda s: int((s == "feedback_sent").sum()))).reset_index()
        g = g.sort_values("avg")
        g["pass_rate"] = g["pass_rate"] * 100
        st.dataframe(g, hide_index=True, width="stretch", column_config={
            "agent": "Agent", "process": "Process", "audits": "Audits",
            "avg": st.column_config.NumberColumn("Average score", format="%.1f%%"),
            "pass_rate": st.column_config.NumberColumn("Pass rate", format="%.0f%%"),
            "fatal": "Fatal errors", "waiting": "Awaiting response"})

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        out = d.drop(columns=["agent_id", "auditor_id", "process_id", "team_lead_id"]).copy()
        out["created_at"] = out["created_at"].astype(str)
        out.to_excel(xw, sheet_name="Audits", index=False)
        g.to_excel(xw, sheet_name="By agent", index=False)
        R.failing_parameters(list(ids)).to_excel(xw, sheet_name="Parameters", index=False)
        pd.DataFrame({"Note": ["SYNTHETIC DEMO DATA - all people, PNRs and audits are fictional."]}).to_excel(
            xw, sheet_name="About", index=False)
    st.download_button("Export to Excel", buf.getvalue(), "QualityPulse_audits.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")


# =============================================================================== form builder
def form_builder(viewer: dict) -> None:
    U.header("Form builder", "Create or change the audit form for a process. Saving creates a new version; "
                             "past audits keep the version they were scored with.")
    procs = R.processes()
    pmap = {p["id"]: p for p in procs}
    c1, c2 = st.columns([2, 1])
    pid = c1.selectbox("Process", list(pmap), format_func=lambda i: f"{pmap[i]['name']} · {pmap[i]['location']}",
                       key="fb_proc")
    with c2.popover("Add a new process", icon=":material/add:"):
        with st.form("newproc"):
            n = st.text_input("Process name")
            cl = st.text_input("Client")
            lo = st.text_input("Location")
            if st.form_submit_button("Create"):
                try:
                    R.create_process(n, cl, lo)
                    st.toast("Process created – now build its form")
                    st.rerun()
                except ValueError as ex:
                    st.error(str(ex))
    f = R.active_form(pid)
    params = R.form_params(f["id"]) if f else []
    base = pd.DataFrame([{"section": p["section"], "name": p["name"], "weight": p["weight"],
                          "is_fatal": bool(p["is_fatal"]), "guidance": p["guidance"]} for p in params]) if params else \
        pd.DataFrame([{"section": "Accuracy", "name": "", "weight": 10.0, "is_fatal": False, "guidance": ""}])
    with st.form(f"fb_{pid}_{f['id'] if f else 0}"):
        a, b, c = st.columns([2, 1, 1.4])
        name = a.text_input("Form name", value=f["name"] if f else f"{pmap[pid]['name']} – Audit")
        pass_mark = b.number_input("Pass mark %", 1.0, 100.0, float(f["pass_mark"]) if f else 90.0, step=1.0)
        rule = c.selectbox("When a fatal parameter is No", ["fail_only", "zero_score"],
                           index=0 if not f or f["fatal_rule"] == "fail_only" else 1,
                           format_func={"fail_only": "Fail the audit, keep the score", "zero_score": "Fail and set score to 0"}.get)
        edited = st.data_editor(base, num_rows="dynamic", width="stretch", hide_index=True, key=f"ed_{pid}",
                                column_config={
                                    "section": st.column_config.TextColumn("Section", width="small"),
                                    "name": st.column_config.TextColumn("Parameter", width="medium", required=True),
                                    "weight": st.column_config.NumberColumn("Weight", min_value=0.5, step=0.5, width="small"),
                                    "is_fatal": st.column_config.CheckboxColumn("Fatal", width="small"),
                                    "guidance": st.column_config.TextColumn("Guidance for auditors", width="large")})
        total = pd.to_numeric(edited["weight"], errors="coerce").fillna(0).sum()
        st.caption(f"Total weight {total:g}. Weights do not have to add up to 100: the score is always "
                   "points earned ÷ applicable points.")
        if st.form_submit_button("Save as new version", type="primary", icon=":material/save:"):
            try:
                R.save_form_version(pid, name, pass_mark, rule, edited.to_dict("records"), viewer["id"])
                st.toast("Saved – new audits will use this version")
                st.rerun()
            except ValueError as ex:
                st.error(str(ex))
    if f:
        st.caption(f"Currently active: version {f['version']}, saved {U.when(f['created_at'])}.")


def how_it_works(viewer: dict) -> None:
    U.header("How QualityPulse works", "Part of the Ops Suite: OpsPulse (performance) · OpsMate (knowledge) · QualityPulse (quality)")
    st.markdown("""
1. **QA admin builds the form** for each process: sections, parameters, weights, fatal flags and the pass mark.
2. **Auditor audits a transaction**: Yes / No / N/A for every parameter, a comment box on each one, and overall feedback.
   Every *No* needs a comment so the agent knows exactly what went wrong.
3. **The system scores it**: score = points earned ÷ applicable points × 100. N/A never counts against the agent.
   Any fatal parameter answered No fails the audit.
4. **The agent is notified** with the full detail: every parameter, the answer, the points and the auditor's comment.
5. **The agent acknowledges or disputes** within 48 hours. Unanswered audits show as *Overdue* to the team lead.
6. **A QA admin or team lead decides the dispute**: uphold (score stands) or overturn (answer changed and the
   score recalculated). Every version is kept in the score history.
""")
    st.info("Demo note: switch the person in the sidebar to see each role. All people, PNRs and audits are synthetic.",
            icon=":material/science:")
