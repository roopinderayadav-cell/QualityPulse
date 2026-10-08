"""All reads and writes for QualityPulse.  Pages never write SQL themselves."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

import qp_db as D
import qp_scoring as S

REVIEWER_ROLES = ("qa_admin", "team_lead")


def now() -> str:
    return D.ts(datetime.now().replace(microsecond=0))


def q(sql: str, args=()) -> list[dict]:
    with D.connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def df(sql: str, args=()) -> pd.DataFrame:
    with D.connect() as c:
        return pd.read_sql_query(sql, c, params=args)


def notify(c, user_id, audit_id, title, body=""):
    c.execute("insert into notifications (user_id, audit_id, title, body, created_at) values (?,?,?,?,?)",
              (user_id, audit_id, title, body, now()))


# --------------------------------------------------------------------------- people & processes
def users() -> list[dict]:
    return q("select u.*, p.name as process from users u left join processes p on p.id = u.process_id order by "
             "case u.role when 'qa_admin' then 1 when 'auditor' then 2 when 'team_lead' then 3 else 4 end, u.name")


def user(uid: int) -> dict:
    return q("select * from users where id = ?", (uid,))[0]


def processes() -> list[dict]:
    return q("select * from processes order by name")


def agents(process_id: int | None = None) -> list[dict]:
    if process_id:
        return q("select * from users where role='agent' and process_id=? order by name", (process_id,))
    return q("select * from users where role='agent' order by name")


def create_process(name: str, client: str, location: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Process name is required.")
    with D.connect() as c:
        if c.execute("select 1 from processes where lower(name)=lower(?)", (name,)).fetchone():
            raise ValueError("A process with this name already exists.")
        return c.execute("insert into processes (name, client, location) values (?,?,?)",
                         (name, client.strip(), location.strip())).lastrowid


# --------------------------------------------------------------------------- forms
def active_form(process_id: int) -> dict | None:
    r = q("select * from forms where process_id=? and is_active=1 order by version desc limit 1", (process_id,))
    return r[0] if r else None


def form(form_id: int) -> dict:
    return q("select * from forms where id=?", (form_id,))[0]


def form_params(form_id: int) -> list[dict]:
    return q("select * from form_params where form_id=? order by position", (form_id,))


def save_form_version(process_id: int, name: str, pass_mark: float, fatal_rule: str, params: list[dict], by: int) -> int:
    """Saves a NEW version; earlier audits keep the version they were scored with."""
    clean = []
    for p in params:
        pname = str(p.get("name") or "").strip()
        if not pname:
            continue
        w = float(p.get("weight") or 0)
        if w <= 0:
            raise ValueError(f"Weight for '{pname}' must be more than 0.")
        clean.append({"section": str(p.get("section") or "General").strip() or "General", "name": pname,
                      "weight": w, "is_fatal": 1 if p.get("is_fatal") else 0, "guidance": str(p.get("guidance") or "")})
    if not clean:
        raise ValueError("Add at least one parameter.")
    if len({p["name"].lower() for p in clean}) != len(clean):
        raise ValueError("Two parameters have the same name.")
    if not 0 < float(pass_mark) <= 100:
        raise ValueError("Pass mark must be between 1 and 100.")
    with D.connect() as c:
        v = (c.execute("select max(version) from forms where process_id=?", (process_id,)).fetchone()[0] or 0) + 1
        c.execute("update forms set is_active=0 where process_id=?", (process_id,))
        fid = c.execute("insert into forms (process_id, name, version, pass_mark, fatal_rule, is_active, created_by, created_at)"
                        " values (?,?,?,?,?,1,?,?)", (process_id, name.strip() or "Audit form", v, float(pass_mark),
                                                      fatal_rule, by, now())).lastrowid
        for i, p in enumerate(clean):
            c.execute("insert into form_params (form_id, section, name, weight, is_fatal, guidance, position)"
                      " values (?,?,?,?,?,?,?)", (fid, p["section"], p["name"], p["weight"], p["is_fatal"], p["guidance"], i))
        return fid


# --------------------------------------------------------------------------- audits
def submit_audit(form_id: int, agent_id: int, auditor_id: int, txn_ref: str, txn_date: str,
                 answers: dict, comments: dict, overall: str) -> int:
    f = form(form_id)
    params = form_params(form_id)
    if not txn_ref.strip():
        raise ValueError("Enter the transaction reference (PNR / ticket / call ID).")
    for p in params:
        if answers.get(p["id"]) == "no" and not (comments.get(p["id"]) or "").strip():
            raise ValueError(f"Add a comment for '{p['name']}' - every 'No' needs a reason for the agent.")
    r = S.calculate(params, answers, f["pass_mark"], f["fatal_rule"])
    created = datetime.now().replace(microsecond=0)
    with D.connect() as c:
        aid = c.execute(
            "insert into audits (form_id, process_id, agent_id, auditor_id, txn_ref, txn_date, overall_comment, earned,"
            " applicable, score, fatal_failed, result, status, version, created_at, ack_due_at) values"
            " (?,?,?,?,?,?,?,?,?,?,?,?,'feedback_sent',1,?,?)",
            (form_id, f["process_id"], agent_id, auditor_id, txn_ref.strip().upper(), txn_date, overall.strip(),
             r.earned, r.applicable, r.score, int(r.fatal_failed), r.result, D.ts(created),
             D.ts(created + timedelta(hours=D.ACK_HOURS)))).lastrowid
        for p in params:
            c.execute("insert into audit_answers (audit_id, param_id, answer, comment) values (?,?,?,?)",
                      (aid, p["id"], answers[p["id"]], (comments.get(p["id"]) or "").strip()))
        c.execute("insert into audit_history (audit_id, version, score, result, answers, changed_by, reason, created_at)"
                  " values (?,?,?,?,?,?,?,?)", (aid, 1, r.score, r.result, json.dumps({str(k): v for k, v in answers.items()}),
                                                auditor_id, "Audit submitted", now()))
        fatal = " · fatal error" if r.fatal_failed else ""
        notify(c, agent_id, aid, f"New audit: {r.score}% · {r.result}{fatal}",
               f"{f['name']} · {txn_ref.strip().upper()} · please acknowledge or dispute within {D.ACK_HOURS} hours")
        return aid


AUDIT_LIST_SQL = """
select a.id, a.txn_ref, a.created_at, a.txn_date, a.score, a.result, a.fatal_failed, a.status, a.outcome,
       a.ack_due_at, a.acknowledged_at, a.version, a.agent_id, a.auditor_id, a.process_id,
       p.name as process, ag.name as agent, au.name as auditor, f.name as form, f.version as form_version,
       ag.team_lead_id
from audits a join processes p on p.id=a.process_id join users ag on ag.id=a.agent_id
join users au on au.id=a.auditor_id join forms f on f.id=a.form_id
"""


def audits(where: str = "", args=()) -> pd.DataFrame:
    d = df(AUDIT_LIST_SQL + (" where " + where if where else "") + " order by a.created_at desc", args)
    if not d.empty:
        d["created_at"] = pd.to_datetime(d["created_at"])
        d["overdue"] = (d["status"] == "feedback_sent") & (pd.to_datetime(d["ack_due_at"]) < datetime.now())
    else:
        d["overdue"] = []
    return d


def audit_detail(audit_id: int) -> dict:
    a = q(AUDIT_LIST_SQL + " where a.id=?", (audit_id,))
    if not a:
        raise LookupError("Audit not found.")
    a = a[0]
    f = form(q("select form_id from audits where id=?", (audit_id,))[0]["form_id"])
    lines = q("""select fp.id as param_id, fp.section, fp.name, fp.weight, fp.is_fatal, fp.guidance, aa.answer, aa.comment
                 from audit_answers aa join form_params fp on fp.id=aa.param_id where aa.audit_id=? order by fp.position""",
              (audit_id,))
    msgs = q("""select m.*, u.name as author, u.role from messages m join users u on u.id=m.author_id
                where m.audit_id=? order by m.created_at""", (audit_id,))
    disputes = q("""select d.*, u.name as raised_by_name, v.name as decided_by_name from disputes d
                    join users u on u.id=d.raised_by left join users v on v.id=d.decided_by where d.audit_id=? order by d.created_at""",
                 (audit_id,))
    history = q("""select h.*, u.name as changed_by_name from audit_history h left join users u on u.id=h.changed_by
                   where h.audit_id=? order by h.version""", (audit_id,))
    a["overdue"] = a["status"] == "feedback_sent" and a["ack_due_at"] < now()
    return {"audit": a, "form": f, "lines": lines, "messages": msgs, "disputes": disputes, "history": history,
            "overall": q("select overall_comment from audits where id=?", (audit_id,))[0]["overall_comment"]}


def acknowledge(audit_id: int, agent_id: int, note: str = "") -> None:
    with D.connect() as c:
        a = c.execute("select * from audits where id=?", (audit_id,)).fetchone()
        if a["agent_id"] != agent_id:
            raise PermissionError("Only the audited agent can acknowledge.")
        if a["status"] != "feedback_sent":
            raise ValueError("This audit is no longer waiting for acknowledgement.")
        t = now()
        c.execute("update audits set status='acknowledged', acknowledged_at=?, closed_at=?, outcome='Acknowledged' where id=?",
                  (t, t, audit_id))
        if note.strip():
            c.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)",
                      (audit_id, agent_id, note.strip(), t))
        notify(c, a["auditor_id"], audit_id, f"Acknowledged: {a['txn_ref']}", "The agent accepted the feedback.")


def raise_dispute(audit_id: int, agent_id: int, reason: str, param_ids: list[int]) -> None:
    if not reason.strip():
        raise ValueError("Explain why you are disputing.")
    if not param_ids:
        raise ValueError("Choose at least one parameter you are disputing.")
    with D.connect() as c:
        a = c.execute("select * from audits where id=?", (audit_id,)).fetchone()
        if a["agent_id"] != agent_id:
            raise PermissionError("Only the audited agent can dispute.")
        if a["status"] != "feedback_sent":
            raise ValueError("This audit can no longer be disputed.")
        if c.execute("select 1 from disputes where audit_id=?", (audit_id,)).fetchone():
            raise ValueError("A dispute was already raised on this audit.")
        t = now()
        c.execute("insert into disputes (audit_id, raised_by, reason, param_ids, created_at) values (?,?,?,?,?)",
                  (audit_id, agent_id, reason.strip(), json.dumps([int(p) for p in param_ids]), t))
        c.execute("update audits set status='disputed' where id=?", (audit_id,))
        c.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)",
                  (audit_id, agent_id, "Dispute raised: " + reason.strip(), t))
        reviewers = [r[0] for r in c.execute("select id from users where role in ('qa_admin','team_lead')")]
        for u in set(reviewers + [a["auditor_id"]]):
            notify(c, u, audit_id, f"Dispute raised on {a['txn_ref']}", reason.strip()[:140])


def add_message(audit_id: int, author_id: int, body: str) -> None:
    if not body.strip():
        raise ValueError("Write a message first.")
    with D.connect() as c:
        a = c.execute("select * from audits where id=?", (audit_id,)).fetchone()
        c.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)",
                  (audit_id, author_id, body.strip(), now()))
        targets = {a["agent_id"], a["auditor_id"]} - {author_id}
        author = c.execute("select name from users where id=?", (author_id,)).fetchone()[0]
        for u in targets:
            notify(c, u, audit_id, f"New comment on {a['txn_ref']}", f"{author}: {body.strip()[:140]}")


def decide_dispute(dispute_id: int, decider_id: int, decision: str, note: str, changes: dict | None = None) -> None:
    """decision 'upheld' (score stands) or 'overturned' (changes = {param_id: new answer}, score recalculated)."""
    if decision not in ("upheld", "overturned"):
        raise ValueError("Unknown decision.")
    if not note.strip():
        raise ValueError("Write the reason for the decision - the agent will see it.")
    with D.connect() as c:
        decider = c.execute("select * from users where id=?", (decider_id,)).fetchone()
        if decider["role"] not in REVIEWER_ROLES:
            raise PermissionError("Only a QA admin or team lead can decide disputes.")
        d = c.execute("select * from disputes where id=?", (dispute_id,)).fetchone()
        if d["status"] != "open":
            raise ValueError("This dispute is already decided.")
        a = c.execute("select * from audits where id=?", (d["audit_id"],)).fetchone()
        t = now()
        outcome = "Dispute upheld"
        if decision == "overturned":
            changes = {int(k): v for k, v in (changes or {}).items()}
            current = {r["param_id"]: r["answer"] for r in c.execute(
                "select param_id, answer from audit_answers where audit_id=?", (a["id"],))}
            real = {k: v for k, v in changes.items() if current.get(k) != v}
            if not real:
                raise ValueError("Change at least one answer to overturn, or choose 'Uphold'.")
            current.update(real)
            f = c.execute("select * from forms where id=?", (a["form_id"],)).fetchone()
            params = [dict(r) for r in c.execute("select * from form_params where form_id=? order by position", (a["form_id"],))]
            r = S.calculate(params, current, f["pass_mark"], f["fatal_rule"])
            for pid, ans in real.items():
                old = c.execute("select answer, comment from audit_answers where audit_id=? and param_id=?",
                                (a["id"], pid)).fetchone()
                c.execute("update audit_answers set answer=?, comment=? where audit_id=? and param_id=?",
                          (ans, f"Changed from {S.ANSWER_LABEL[old['answer']]} after dispute. {note.strip()} "
                                f"(Original comment: {old['comment'] or '-'})", a["id"], pid))
            v = a["version"] + 1
            c.execute("update audits set score=?, earned=?, applicable=?, result=?, fatal_failed=?, version=? where id=?",
                      (r.score, r.earned, r.applicable, r.result, int(r.fatal_failed), v, a["id"]))
            c.execute("insert into audit_history (audit_id, version, score, result, answers, changed_by, reason, created_at)"
                      " values (?,?,?,?,?,?,?,?)", (a["id"], v, r.score, r.result,
                                                    json.dumps({str(k): x for k, x in current.items()}), decider_id,
                                                    "Dispute overturned: " + note.strip(), t))
            outcome = "Dispute overturned"
            headline = f"Dispute overturned: {r.score}% · {r.result}"
        else:
            headline = f"Dispute upheld: score stays {a['score']}% · {a['result']}"
        c.execute("update disputes set status=?, decided_by=?, decision_note=?, decided_at=? where id=?",
                  (decision, decider_id, note.strip(), t, dispute_id))
        c.execute("update audits set status='closed', closed_at=?, outcome=? where id=?", (t, outcome, a["id"]))
        c.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)",
                  (a["id"], decider_id, f"{headline}. {note.strip()}", t))
        for u in {a["agent_id"], a["auditor_id"]}:
            notify(c, u, a["id"], headline, note.strip()[:140])


# --------------------------------------------------------------------------- notifications
def notifications(user_id: int, limit: int = 50) -> list[dict]:
    return q("""select n.*, a.txn_ref from notifications n left join audits a on a.id=n.audit_id
                where n.user_id=? order by n.created_at desc limit ?""", (user_id, limit))


def unread_count(user_id: int) -> int:
    return q("select count(*) as n from notifications where user_id=? and read_at is null", (user_id,))[0]["n"]


def mark_read(user_id: int, audit_id: int | None = None) -> None:
    with D.connect() as c:
        if audit_id:
            c.execute("update notifications set read_at=? where user_id=? and audit_id=? and read_at is null",
                      (now(), user_id, audit_id))
        else:
            c.execute("update notifications set read_at=? where user_id=? and read_at is null", (now(), user_id))


def open_disputes() -> list[dict]:
    return q("""select d.*, a.txn_ref, a.score, a.result, ag.name as agent, p.name as process from disputes d
                join audits a on a.id=d.audit_id join users ag on ag.id=a.agent_id join processes p on p.id=a.process_id
                where d.status='open' order by d.created_at""")


def failing_parameters(audit_ids: list[int]) -> pd.DataFrame:
    if not audit_ids:
        return pd.DataFrame(columns=["parameter", "process", "checked", "missed", "miss_rate"])
    marks = ",".join("?" * len(audit_ids))
    d = df(f"""select fp.name as parameter, p.name as process, aa.answer from audit_answers aa
               join form_params fp on fp.id=aa.param_id join audits a on a.id=aa.audit_id
               join processes p on p.id=a.process_id where aa.audit_id in ({marks}) and aa.answer!='na'""", audit_ids)
    if d.empty:
        return pd.DataFrame(columns=["parameter", "process", "checked", "missed", "miss_rate"])
    g = d.groupby(["parameter", "process"]).agg(checked=("answer", "size"),
                                                 missed=("answer", lambda s: int((s == "no").sum()))).reset_index()
    g["miss_rate"] = g["missed"] / g["checked"]
    return g.sort_values(["miss_rate", "missed"], ascending=False)
