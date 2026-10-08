"""QualityPulse tests.  Run:  pip install pytest  then  pytest -q"""
import json
import pytest
import qp_scoring as S

P = [{"id": 1, "name": "A", "weight": 20, "is_fatal": 0}, {"id": 2, "name": "B", "weight": 25, "is_fatal": 1},
     {"id": 3, "name": "C", "weight": 15, "is_fatal": 0}, {"id": 4, "name": "D", "weight": 15, "is_fatal": 0},
     {"id": 5, "name": "E", "weight": 15, "is_fatal": 0}, {"id": 6, "name": "F", "weight": 10, "is_fatal": 0}]


def test_example_from_infographic():
    r = S.calculate(P, {1: "yes", 2: "yes", 3: "yes", 4: "no", 5: "na", 6: "yes"}, 90)
    assert (r.earned, r.applicable, r.score, r.result, r.fatal_failed) == (70, 85, 82.4, "Fail", False)


def test_all_yes_passes_and_na_is_not_a_miss():
    assert S.calculate(P, {i: "yes" for i in range(1, 7)}, 90).score == 100.0
    r = S.calculate(P, {1: "yes", 2: "yes", 3: "na", 4: "na", 5: "yes", 6: "yes"}, 90)
    assert r.score == 100.0 and r.result == "Pass"


def test_fatal_fails_even_with_high_score():
    r = S.calculate(P, {1: "yes", 2: "no", 3: "yes", 4: "yes", 5: "yes", 6: "yes"}, 70)
    assert r.score == 75.0 and r.result == "Fail" and r.fatal_params == ["B"]
    assert S.calculate(P, {1: "yes", 2: "no", 3: "yes", 4: "yes", 5: "yes", 6: "yes"}, 70, "zero_score").score == 0.0


def test_pass_mark_boundary_and_validation():
    r = S.calculate(P[:2], {1: "no", 2: "yes"}, 55.6)
    assert r.score == 55.6 and r.result == "Pass"
    with pytest.raises(ValueError):
        S.calculate(P, {1: "yes"}, 90)
    assert S.calculate(P[:1], {1: "na"}, 90).result == "Not scorable"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    import qp_db as D
    monkeypatch.setattr(D, "DB_PATH", tmp_path / "t.db")
    D.ensure()
    import qp_repo as R
    return D, R


def test_seed_is_synthetic_and_has_examples(repo):
    D, R = repo
    d = R.audits()
    assert len(d) > 40
    assert {"6XK2LQ", "Q7MZP4", "L2VN8C", "9HD3KW", "CALL-20418"} <= set(d["txn_ref"])
    assert d[d["txn_ref"] == "Q7MZP4"]["overdue"].iloc[0]
    x = R.audit_detail(int(d[d["txn_ref"] == "6XK2LQ"]["id"].iloc[0]))
    assert x["audit"]["score"] == 100.0 and len(x["history"]) == 2 and x["history"][0]["score"] == 82.4


def test_full_flow_submit_notify_dispute_overturn(repo):
    D, R = repo
    proc = [p for p in R.processes() if p["name"] == "Refunds"][0]
    f = R.active_form(proc["id"])
    params = R.form_params(f["id"])
    agent = R.agents(proc["id"])[0]
    auditor = [u for u in R.users() if u["role"] == "auditor"][0]
    admin = [u for u in R.users() if u["role"] == "qa_admin"][0]
    ans = {p["id"]: "yes" for p in params}
    miss = [p for p in params if not p["is_fatal"]][0]
    ans[miss["id"]] = "no"
    with pytest.raises(ValueError):        # a No needs a comment
        R.submit_audit(f["id"], agent["id"], auditor["id"], "TEST01", "2026-10-01", ans, {}, "")
    before = R.unread_count(agent["id"])
    aid = R.submit_audit(f["id"], agent["id"], auditor["id"], "test01", "2026-10-01", ans,
                         {miss["id"]: "Missed it", params[1]["id"]: "Great work here"}, "Overall ok")
    assert R.unread_count(agent["id"]) == before + 1
    det = R.audit_detail(aid)
    assert det["audit"]["txn_ref"] == "TEST01" and det["audit"]["result"] == "Fail"
    assert any(l["comment"] == "Great work here" for l in det["lines"])      # comment on a Yes is kept
    with pytest.raises(PermissionError):
        R.raise_dispute(aid, auditor["id"], "x", [miss["id"]])
    R.raise_dispute(aid, agent["id"], "It was done", [miss["id"]])
    with pytest.raises(ValueError):
        R.acknowledge(aid, agent["id"])
    disp = [d for d in R.open_disputes() if d["audit_id"] == aid][0]
    with pytest.raises(PermissionError):
        R.decide_dispute(disp["id"], auditor["id"], "overturned", "ok", {miss["id"]: "yes"})
    R.decide_dispute(disp["id"], admin["id"], "overturned", "Checked, it was done", {miss["id"]: "yes"})
    det = R.audit_detail(aid)
    assert det["audit"]["score"] == 100.0 and det["audit"]["status"] == "closed" and det["audit"]["version"] == 2
    assert [h["version"] for h in det["history"]] == [1, 2]


def test_acknowledge_and_form_versioning(repo):
    D, R = repo
    d = R.audits()
    row = d[d["txn_ref"] == "L2VN8C"].iloc[0]
    R.acknowledge(int(row["id"]), int(row["agent_id"]), "Thanks")
    assert R.audit_detail(int(row["id"]))["audit"]["status"] == "acknowledged"
    proc = R.processes()[0]
    old = R.active_form(proc["id"])
    R.save_form_version(proc["id"], "New form", 85, "zero_score",
                        [{"section": "S", "name": "Only one", "weight": 5, "is_fatal": True}], 1)
    new = R.active_form(proc["id"])
    assert new["version"] == old["version"] + 1 and len(R.form_params(new["id"])) == 1
    with pytest.raises(ValueError):
        R.save_form_version(proc["id"], "Bad", 90, "fail_only", [{"name": "x", "weight": 0}], 1)
