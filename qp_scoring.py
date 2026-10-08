"""QualityPulse scoring rules - pure functions, no AI, same answer every time.

    Score % = points earned / applicable points x 100
      * Yes  -> parameter weight is earned
      * No   -> 0 earned (weight still applicable)
      * N/A  -> removed from applicable points (never counts against the agent)
    Result
      * any FATAL parameter answered No  -> Fail
          (form setting "zero_score": the score also becomes 0)
      * otherwise Pass when score >= the form's pass mark
"""
from __future__ import annotations

from dataclasses import dataclass

ANSWERS = ("yes", "no", "na")
ANSWER_LABEL = {"yes": "Yes", "no": "No", "na": "N/A"}


@dataclass
class ScoreResult:
    earned: float
    applicable: float
    score: float | None           # percentage, 1 decimal; None when nothing is applicable
    fatal_failed: bool
    fatal_params: list
    result: str                   # "Pass" / "Fail" / "Not scorable"
    missed: list                  # names of parameters answered No


def calculate(params: list[dict], answers: dict, pass_mark: float, fatal_rule: str = "fail_only") -> ScoreResult:
    """params: [{"id","name","weight","is_fatal"}]; answers: {param_id: "yes"|"no"|"na"}."""
    missing = [p["name"] for p in params if answers.get(p["id"]) not in ANSWERS]
    if missing:
        raise ValueError("Answer every parameter before scoring: " + ", ".join(missing))
    earned = applicable = 0.0
    fatal_params, missed = [], []
    for p in params:
        a = answers[p["id"]]
        w = float(p["weight"])
        if a == "na":
            continue
        applicable += w
        if a == "yes":
            earned += w
        else:
            missed.append(p["name"])
            if p.get("is_fatal"):
                fatal_params.append(p["name"])
    if applicable == 0:
        return ScoreResult(earned, applicable, None, False, [], "Not scorable", missed)
    score = round(earned / applicable * 100, 1)
    fatal = bool(fatal_params)
    if fatal and fatal_rule == "zero_score":
        score = 0.0
    result = "Fail" if fatal or score < float(pass_mark) else "Pass"
    return ScoreResult(earned, applicable, score, fatal, fatal_params, result, missed)
