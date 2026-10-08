"""QualityPulse demo database (SQLite) and SYNTHETIC seed data.

Every person, PNR and audit here is fictional.  Dates are generated relative to
the moment the database is built, so "overdue" examples always look current.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import qp_scoring as S

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "qualitypulse_demo.db"
ACK_HOURS = 48
_lock = threading.Lock()

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS processes (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, client TEXT, location TEXT);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('qa_admin','auditor','team_lead','agent')),
  process_id INTEGER REFERENCES processes(id), team_lead_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY, process_id INTEGER NOT NULL REFERENCES processes(id), name TEXT NOT NULL,
  version INTEGER NOT NULL, pass_mark REAL NOT NULL, fatal_rule TEXT NOT NULL DEFAULT 'fail_only',
  is_active INTEGER NOT NULL DEFAULT 1, created_by INTEGER, created_at TEXT NOT NULL,
  UNIQUE (process_id, version));
CREATE TABLE IF NOT EXISTS form_params (
  id INTEGER PRIMARY KEY, form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
  section TEXT NOT NULL, name TEXT NOT NULL, weight REAL NOT NULL CHECK (weight > 0),
  is_fatal INTEGER NOT NULL DEFAULT 0, guidance TEXT, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audits (
  id INTEGER PRIMARY KEY, form_id INTEGER NOT NULL REFERENCES forms(id), process_id INTEGER NOT NULL REFERENCES processes(id),
  agent_id INTEGER NOT NULL REFERENCES users(id), auditor_id INTEGER NOT NULL REFERENCES users(id),
  txn_ref TEXT NOT NULL, txn_date TEXT NOT NULL, overall_comment TEXT,
  earned REAL, applicable REAL, score REAL, fatal_failed INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('feedback_sent','acknowledged','disputed','closed')),
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, ack_due_at TEXT NOT NULL,
  acknowledged_at TEXT, closed_at TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS audit_answers (
  id INTEGER PRIMARY KEY, audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
  param_id INTEGER NOT NULL REFERENCES form_params(id), answer TEXT NOT NULL CHECK (answer IN ('yes','no','na')),
  comment TEXT, UNIQUE (audit_id, param_id));
CREATE TABLE IF NOT EXISTS disputes (
  id INTEGER PRIMARY KEY, audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
  raised_by INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, param_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','upheld','overturned')),
  decided_by INTEGER REFERENCES users(id), decision_note TEXT, created_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), audit_id INTEGER REFERENCES audits(id) ON DELETE CASCADE,
  title TEXT NOT NULL, body TEXT, created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE IF NOT EXISTS audit_history (
  id INTEGER PRIMARY KEY, audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE, version INTEGER NOT NULL,
  score REAL, result TEXT, answers TEXT NOT NULL, changed_by INTEGER, reason TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audits_agent_idx ON audits (agent_id, created_at);
CREATE INDEX IF NOT EXISTS notif_user_idx ON notifications (user_id, read_at);
"""


def ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def ensure(path: Path | str | None = None, force: bool = False) -> bool:
    """Create and seed the demo database if it is missing. Returns True if (re)built."""
    path = Path(path or DB_PATH)
    with _lock:
        if path.exists() and not force:
            try:
                with connect(path) as c:
                    if c.execute("select count(*) from audits").fetchone()[0] > 0:
                        return False
            except sqlite3.DatabaseError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".building-{os.getpid()}")
        tmp.unlink(missing_ok=True)
        con = connect(tmp)
        con.executescript(SCHEMA)
        seed(con)
        con.commit()
        con.close()
        os.replace(tmp, path)
        return True


# --------------------------------------------------------------------------------------- seed
FORMS = {
    "Refunds": ("Refunds – Transaction Audit", 90, [
        ("Accuracy", "Correct fare rule applied", 20, 0, "Refund calculated under the fare rules of the ticket"),
        ("Accuracy", "Refund amount accurate", 25, 1, "Amount refunded matches the calculation - FATAL if wrong"),
        ("Accuracy", "Taxes refunded correctly", 15, 0, "Refundable taxes returned, non-refundable retained"),
        ("Compliance", "Documentation in PNR", 15, 0, "Refund remark and reference added to PNR history"),
        ("Customer", "Customer communication", 15, 0, "Refund confirmation sent with amount and timeline"),
        ("Timeliness", "Processed within TAT", 10, 0, "Completed within the agreed turnaround time"),
    ]),
    "Ticketing and Exchanges": ("Ticketing & Exchanges – Transaction Audit", 90, [
        ("Accuracy", "Correct fare and class booked", 20, 0, "Matches traveller request and travel policy"),
        ("Accuracy", "Exchange fare difference correct", 20, 1, "Additional collection / residual value correct - FATAL"),
        ("Compliance", "Travel policy followed", 15, 0, "Lowest logical fare or approved exception"),
        ("Compliance", "Documentation in PNR", 15, 0, "Remarks, approvals and form of payment recorded"),
        ("Customer", "Itinerary sent to traveller", 15, 0, "Correct itinerary and e-ticket shared"),
        ("Timeliness", "Ticketed before time limit", 15, 1, "Issued before ticketing time limit - FATAL if missed"),
    ]),
    "Corporate Travel Support": ("Travel Support – Call Audit", 85, [
        ("Opening", "Greeting and verification", 10, 0, "Standard greeting, traveller and company verified"),
        ("Resolution", "Need understood correctly", 20, 0, "Probing questions, need confirmed back"),
        ("Resolution", "Accurate information given", 25, 1, "No wrong information on fares, visas or rules - FATAL"),
        ("Resolution", "First contact resolution", 15, 0, "Resolved without needing a call-back"),
        ("Soft skills", "Empathy and tone", 15, 0, "Professional, empathetic tone throughout"),
        ("Closing", "Summary and closing", 15, 0, "Summary of actions, next steps and closing"),
    ]),
}

POSITIVE = ["Clear and complete.", "Good attention to detail.", "Correctly handled.", "Well documented."]
NEGATIVE = {
    "Documentation in PNR": "Refund remark missing in PNR history.",
    "Customer communication": "Confirmation mail did not mention the refund timeline.",
    "Processed within TAT": "Completed 6 hours after the agreed TAT.",
    "Correct fare rule applied": "Applied the refundable rule; ticket fare basis was non-refundable after departure.",
    "Taxes refunded correctly": "YQ refunded although the ticket was used partially.",
    "Refund amount accurate": "Refund issued INR 4,200 higher than the calculated amount.",
    "Correct fare and class booked": "Booked Y class; lower logical fare in M class was available.",
    "Exchange fare difference correct": "Residual value not applied to the new ticket.",
    "Travel policy followed": "No approval recorded for out-of-policy fare.",
    "Itinerary sent to traveller": "Itinerary sent without the updated return flight.",
    "Ticketed before time limit": "Ticketed after the time limit; fare had to be re-quoted.",
    "Greeting and verification": "Company ID not verified before sharing booking details.",
    "Need understood correctly": "Assumed date change instead of confirming the new route.",
    "Accurate information given": "Told traveller the visa is on arrival; it is not for this passport.",
    "First contact resolution": "Traveller had to call back for the seat request.",
    "Empathy and tone": "Interrupted the traveller twice.",
    "Summary and closing": "No summary of the changes made.",
}


def seed(con: sqlite3.Connection) -> None:
    rng = random.Random(20261008)
    now = datetime.now().replace(microsecond=0)
    procs = {}
    for name, client, loc in [("Refunds", "Client Aurora (Synthetic)", "Gurgaon"),
                              ("Ticketing and Exchanges", "Client Aurora (Synthetic)", "Bangalore"),
                              ("Corporate Travel Support", "Client Meridian (Synthetic)", "Visakhapatnam")]:
        procs[name] = con.execute("insert into processes (name, client, location) values (?,?,?)",
                                  (name, client, loc)).lastrowid

    def user(name, role, proc=None, tl=None):
        return con.execute("insert into users (name, role, process_id, team_lead_id) values (?,?,?,?)",
                           (name, role, procs.get(proc), tl)).lastrowid
    qa_admin = user("Neha Kapoor (QA Admin)", "qa_admin")
    auditors = [user("Arjun Mehta (Auditor)", "auditor"), user("Priya Nair (Auditor)", "auditor")]
    tl = user("Vikram Rao (Team Lead)", "team_lead")
    agents = {}
    for proc, names in {"Refunds": ["Rahul Sharma", "Sneha Iyer", "Imran Khan"],
                        "Ticketing and Exchanges": ["Kavya Reddy", "Deepak Joshi"],
                        "Corporate Travel Support": ["Ananya Das", "Rohan Gupta"]}.items():
        agents[proc] = [user(n + " (Agent)", "agent", proc, tl) for n in names]

    forms = {}
    for proc, (fname, pass_mark, params) in FORMS.items():
        fid = con.execute("insert into forms (process_id, name, version, pass_mark, fatal_rule, is_active, created_by, created_at)"
                          " values (?,?,?,?,?,?,?,?)", (procs[proc], fname, 1, pass_mark, "fail_only", 1, qa_admin,
                                                        ts(now - timedelta(days=60)))).lastrowid
        plist = []
        for i, (sec, pname, w, fatal, guide) in enumerate(params):
            pid = con.execute("insert into form_params (form_id, section, name, weight, is_fatal, guidance, position)"
                              " values (?,?,?,?,?,?,?)", (fid, sec, pname, w, fatal, guide, i)).lastrowid
            plist.append({"id": pid, "name": pname, "weight": w, "is_fatal": fatal})
        forms[proc] = (fid, pass_mark, plist)

    def pnr():
        return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))

    def make_audit(proc, agent, auditor, answers, comments, created, status, overall="", txn=None,
                   acknowledged=None, closed=None, outcome=None, notify=True):
        fid, pass_mark, plist = forms[proc]
        r = S.calculate(plist, answers, pass_mark)
        aid = con.execute(
            "insert into audits (form_id, process_id, agent_id, auditor_id, txn_ref, txn_date, overall_comment, earned,"
            " applicable, score, fatal_failed, result, status, version, created_at, ack_due_at, acknowledged_at,"
            " closed_at, outcome) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, procs[proc], agent, auditor, txn or pnr(), (created - timedelta(days=rng.randint(1, 3))).strftime("%Y-%m-%d"),
             overall, r.earned, r.applicable, r.score, int(r.fatal_failed), r.result, status, 1, ts(created),
             ts(created + timedelta(hours=ACK_HOURS)), acknowledged and ts(acknowledged), closed and ts(closed), outcome)).lastrowid
        for p in plist:
            con.execute("insert into audit_answers (audit_id, param_id, answer, comment) values (?,?,?,?)",
                        (aid, p["id"], answers[p["id"]], comments.get(p["id"], "")))
        con.execute("insert into audit_history (audit_id, version, score, result, answers, changed_by, reason, created_at)"
                    " values (?,?,?,?,?,?,?,?)", (aid, 1, r.score, r.result, json.dumps(answers), auditor,
                                                  "Audit submitted", ts(created)))
        if notify:
            con.execute("insert into notifications (user_id, audit_id, title, body, created_at, read_at) values (?,?,?,?,?,?)",
                        (agent, aid, f"New audit: {r.score}% · {r.result}",
                         f"{FORMS[proc][0]} for transaction audited by {auditor_name(auditor)}", ts(created),
                         ts(created + timedelta(hours=2)) if status != "feedback_sent" else None))
        return aid, r

    names = {r[0]: r[1] for r in con.execute("select id, name from users")}

    def auditor_name(uid):
        return names[uid]

    # --- bulk history: 6 weeks of audits (most acknowledged) -------------------------------
    for proc, agent_ids in agents.items():
        fid, pass_mark, plist = forms[proc]
        for agent in agent_ids:
            skill = rng.uniform(0.86, 0.97)
            for _ in range(rng.randint(7, 10)):
                created = now - timedelta(days=rng.randint(4, 42), hours=rng.randint(0, 9))
                answers, comments = {}, {}
                for p in plist:
                    roll = rng.random()
                    if roll < 0.07:
                        answers[p["id"]] = "na"
                    elif roll < 0.07 + (1 - skill) * (0.35 if p["is_fatal"] else 1.6):
                        answers[p["id"]] = "no"
                        comments[p["id"]] = NEGATIVE.get(p["name"], "Not as per SOP.")
                    else:
                        answers[p["id"]] = "yes"
                        if rng.random() < 0.12:
                            comments[p["id"]] = rng.choice(POSITIVE)
                ack = created + timedelta(hours=rng.randint(2, 40))
                make_audit(proc, agent, rng.choice(auditors), answers, comments, created, "acknowledged",
                           overall="", acknowledged=ack, closed=ack, outcome="Acknowledged")

    # --- curated examples (shown first in inboxes) -------------------------------------------
    ref = forms["Refunds"][2]
    P = {p["name"]: p["id"] for p in ref}
    rahul, sneha, imran = agents["Refunds"]
    arjun, priya = auditors

    # 1) Fail -> dispute -> overturned -> Pass (full conversation)
    t1 = now - timedelta(days=3, hours=4)
    ans = {P["Correct fare rule applied"]: "yes", P["Refund amount accurate"]: "yes", P["Taxes refunded correctly"]: "yes",
           P["Documentation in PNR"]: "no", P["Customer communication"]: "na", P["Processed within TAT"]: "yes"}
    com = {P["Documentation in PNR"]: "Refund remark missing in PNR history.",
           P["Customer communication"]: "Refund was requested by the travel desk, no traveller mail needed.",
           P["Refund amount accurate"]: "Penalty INR 3,500 deducted correctly."}
    a1, r1 = make_audit("Refunds", rahul, arjun, ans, com, t1, "closed", txn="6XK2LQ",
                        overall="Good accuracy. Only the PNR remark was missing.",
                        closed=now - timedelta(days=1, hours=2), outcome="Dispute overturned")
    con.execute("insert into disputes (audit_id, raised_by, reason, param_ids, status, decided_by, decision_note, created_at, decided_at)"
                " values (?,?,?,?,?,?,?,?,?)",
                (a1, rahul, "The refund remark is in the PNR history, line 7 (RF REFUND PROCESSED 3500 PENALTY). Screenshot attached.",
                 json.dumps([P["Documentation in PNR"]]), "overturned", qa_admin,
                 "Checked PNR history - remark present at line 7. Auditor looked at the active segment only.",
                 ts(t1 + timedelta(hours=5)), ts(now - timedelta(days=1, hours=2))))
    for who, body, at in [(rahul, "The refund remark is in the PNR history, line 7. Attaching screenshot.", t1 + timedelta(hours=5)),
                          (arjun, "I checked the active segment remarks only. Requesting QA admin review.", t1 + timedelta(hours=9)),
                          (qa_admin, "Verified in history. Overturned: documentation is present. Score updated to 100% · Pass.",
                           now - timedelta(days=1, hours=2))]:
        con.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)", (a1, who, body, ts(at)))
    new = dict(ans)
    new[P["Documentation in PNR"]] = "yes"
    r1b = S.calculate(ref, new, 90)
    con.execute("update audits set score=?, earned=?, applicable=?, result=?, fatal_failed=?, version=2 where id=?",
                (r1b.score, r1b.earned, r1b.applicable, r1b.result, int(r1b.fatal_failed), a1))
    con.execute("update audit_answers set answer='yes', comment=? where audit_id=? and param_id=?",
                ("Original: remark missing. Overturned after dispute - remark found in PNR history line 7.", a1,
                 P["Documentation in PNR"]))
    con.execute("insert into audit_history (audit_id, version, score, result, answers, changed_by, reason, created_at)"
                " values (?,?,?,?,?,?,?,?)", (a1, 2, r1b.score, r1b.result, json.dumps(new), qa_admin,
                                              "Dispute overturned", ts(now - timedelta(days=1, hours=2))))
    con.execute("insert into notifications (user_id, audit_id, title, body, created_at) values (?,?,?,?,?)",
                (rahul, a1, "Dispute overturned: 100.0% · Pass", "Your dispute on PNR 6XK2LQ was accepted.",
                 ts(now - timedelta(days=1, hours=2))))

    # 2) Fatal error, awaiting acknowledgement and already OVERDUE
    t2 = now - timedelta(hours=55)
    ans = {P["Correct fare rule applied"]: "yes", P["Refund amount accurate"]: "no", P["Taxes refunded correctly"]: "yes",
           P["Documentation in PNR"]: "yes", P["Customer communication"]: "yes", P["Processed within TAT"]: "yes"}
    com = {P["Refund amount accurate"]: "Refund issued INR 4,200 higher than calculated: cancellation penalty not deducted. "
                                         "Recovery raised with the airline (ADM risk).",
           P["Customer communication"]: "Nice clear mail with timeline."}
    make_audit("Refunds", sneha, priya, ans, com, t2, "feedback_sent", txn="Q7MZP4",
               overall="Fatal error: penalty not applied. Please re-read SOP 4.2 (refund calculation) before your next refund.")

    # 3) Pass with appreciation, waiting for acknowledgement (fresh)
    t3 = now - timedelta(hours=6)
    ans = {pid: "yes" for pid in P.values()}
    com = {P["Correct fare rule applied"]: "Excellent: correctly identified the no-show rule.",
           P["Customer communication"]: "Template personalised well."}
    make_audit("Refunds", rahul, priya, ans, com, t3, "feedback_sent", txn="L2VN8C",
               overall="Perfect audit - sharing this as a best-practice example in the huddle.")

    # 4) Open dispute awaiting QA review
    t4 = now - timedelta(days=1, hours=3)
    ans = {P["Correct fare rule applied"]: "yes", P["Refund amount accurate"]: "yes", P["Taxes refunded correctly"]: "no",
           P["Documentation in PNR"]: "yes", P["Customer communication"]: "yes", P["Processed within TAT"]: "no"}
    com = {P["Taxes refunded correctly"]: "YQ refunded although the ticket was partially flown.",
           P["Processed within TAT"]: "Completed 6 hours after TAT."}
    a4, _ = make_audit("Refunds", imran, arjun, ans, com, t4, "disputed", txn="9HD3KW",
                       overall="Two misses: tax handling and TAT.")
    con.execute("insert into disputes (audit_id, raised_by, reason, param_ids, status, created_at) values (?,?,?,?,?,?)",
                (a4, imran, "TAT: the request came in after shift cut-off, so the TAT clock starts next morning per SOP 1.3.",
                 json.dumps([P["Processed within TAT"]]), "open", ts(t4 + timedelta(hours=3))))
    con.execute("insert into messages (audit_id, author_id, body, created_at) values (?,?,?,?)",
                (a4, imran, "I agree on the YQ miss. Disputing only the TAT point - request arrived at 23:40.",
                 ts(t4 + timedelta(hours=3))))
    for u in (qa_admin, tl):
        con.execute("insert into notifications (user_id, audit_id, title, body, created_at) values (?,?,?,?,?)",
                    (u, a4, "Dispute raised on PNR 9HD3KW", "Imran Khan disputes 'Processed within TAT'.",
                     ts(t4 + timedelta(hours=3))))

    # 5) Call audit (other process) awaiting acknowledgement
    cts = forms["Corporate Travel Support"][2]
    C = {p["name"]: p["id"] for p in cts}
    ananya = agents["Corporate Travel Support"][0]
    ans = {pid: "yes" for pid in C.values()}
    ans[C["Need understood correctly"]] = "no"
    com = {C["Need understood correctly"]: "Assumed a date change; the traveller wanted a new route via Dubai.",
           C["Empathy and tone"]: "Calm and polite even when the traveller was upset - well done."}
    make_audit("Corporate Travel Support", ananya, arjun, ans, com, now - timedelta(hours=20), "feedback_sent",
               txn="CALL-20418", overall="Confirm the requirement back before acting.")
