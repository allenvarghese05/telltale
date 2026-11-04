"""Deterministic checker: recomputes every agent claim, and the verdict, from the evidence store.

Nothing here calls a model. The agent's text is untrusted data: each claim must cite real evidence ids,
every assertion is recomputed, and every number in the prose must trace back to a cited fact.
"""

from __future__ import annotations

import contextlib
import re

from telltale.core.schema import CheckResult, Claim
from telltale.evidence.store import EvidenceStore

TOL_ABS, TOL_REL = 0.05, 0.05
CONVERSIONS = (1.0, 1000.0, 3.6, 2.23694)  # base, ms, km/h, mph
LEGAL = re.compile(r"\b(at[- ]fault|fault of|liab(le|ility)|negligen\w*|reckless\w*|culpab\w*|guilty|to blame)\b", re.I)
DRIVER_STATE = re.compile(
    r"\b(distract\w*|inattentiv\w*|not paying attention|asleep|drows\w*|fatigu\w*|drunk|"
    r"intoxicat\w*|impaired|texting|on (?:his|her|their) phone)\b",
    re.I,
)
ID_TOKEN = re.compile(r"\b[A-Z0-9]+:[\w.@-]+")
NAMES = re.compile(r"\b(?:SAM|Muse Spark|Spark|Muse Wonder|Wonder|Class|J)\s*\d+(?:\.\d+)?", re.I)
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
WITNESS_SOURCES = {"WIT", "WIT2"}
# R6, interval meaning (added after the robustness benchmark): each threshold judges one specific interval.
# A claim comparing a different interval with it can be arithmetically true and still misleading, e.g. the human's
# brake request after a handoff measured against the system's command threshold.
THRESHOLD_INTERVALS = {
    "PROFILE:perception_threshold_s": (("AV:first_seen_t", "VID:hazard_onset_t"),),
    "PROFILE:command_threshold_s": (("AV:brake_request_t", "AV:first_seen_t"),),
    "PROFILE:actuation_threshold_s": (("CAN:pressure_reached_t", "CAN:brake_request_t"),),
    # The handoff margin is judged against human reaction time, and so is the human's actual reaction after it.
    "PROFILE:human_prt_s": (("VID:impact_t", "AV:handoff_t"), ("CAN:brake_request_t", "AV:handoff_t")),
}


def _close(x: float, y: float) -> bool:
    return abs(x - y) <= max(TOL_ABS, TOL_REL * abs(y))


def _num(store: EvidenceStore, fact_id: str) -> float:
    value = store.get(fact_id).value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{fact_id} is not numeric")
    return float(value)


def _eval(assertion: dict, store: EvidenceStore) -> tuple[bool, set[float], list[str], str]:
    """Recompute one assertion. Returns (holds, numbers it licenses, fact ids it used, human-readable detail)."""
    op = assertion.get("op")
    try:
        if op == "value":
            v = _num(store, assertion["fact"])
            return (
                _close(v, float(assertion["equals"])),
                {v},
                [assertion["fact"]],
                f"{assertion['fact']}={v}, claimed {assertion['equals']}",
            )
        if op == "diff":
            va, vb = _num(store, assertion["a"]), _num(store, assertion["b"])
            return (
                _close(va - vb, float(assertion["equals"])),
                {va, vb, va - vb},
                [assertion["a"], assertion["b"]],
                f"recomputed {va - vb:.3f}, claimed {assertion['equals']}",
            )
        if op in ("lt", "gt"):
            value, ids = _num(store, assertion["fact"]), [assertion["fact"]]
            if "than_fact" in assertion:
                threshold = _num(store, assertion["than_fact"])
                ids.append(assertion["than_fact"])
                numbers = {value, threshold}
            else:
                threshold = float(assertion["than"])
                numbers = {value}
            holds = value < threshold if op == "lt" else value > threshold
            return holds, numbers, ids, f"{value} {op} {threshold} is {holds}"
        if op == "agree":
            va, vb = _num(store, assertion["a"]), _num(store, assertion["b"])
            return (
                abs(va - vb) <= float(assertion["within"]),
                {va, vb, abs(va - vb)},
                [assertion["a"], assertion["b"]],
                f"|{va}-{vb}| vs {assertion['within']}",
            )
        if op == "same":
            va, vb = store.get(assertion["a"]).value, store.get(assertion["b"]).value
            return str(va).lower() == str(vb).lower(), set(), [assertion["a"], assertion["b"]], f"{va!r} vs {vb!r}"
        if op == "is":
            value = store.get(assertion["fact"]).value
            return (
                str(value).lower() == str(assertion["equals"]).lower(),
                set(),
                [assertion["fact"]],
                f"{value!r} vs {assertion['equals']!r}",
            )
    except (KeyError, TypeError, ValueError) as exc:
        return False, set(), [], f"assertion could not be evaluated: {exc}"
    return False, set(), [], f"unknown assertion op {op!r}"


def _interval_meaning_problem(claim: Claim, store: EvidenceStore) -> str | None:
    """Why a diff assertion cannot be judged against the thresholds it cites, or None when it measures one of them."""
    assertion = claim.assertion or {}
    cited = sorted(set(claim.evidence) & set(THRESHOLD_INTERVALS))
    if assertion.get("op") != "diff" or not cited:
        return None
    measured = (assertion.get("a"), assertion.get("b"))
    if any(measured in THRESHOLD_INTERVALS[threshold] for threshold in cited):
        return None
    if "PROFILE:command_threshold_s" in cited and store.has("AV:handoff_t"):
        return (
            "interval meaning: PROFILE:command_threshold_s judges the system's own brake command, and this case has "
            f"a handoff (AV:handoff_t), so there is no system command interval; {measured[0]} - {measured[1]} is not it"
        )
    judged = " or ".join(f"{a} - {b}" for threshold in cited for a, b in THRESHOLD_INTERVALS[threshold])
    measures = f"{measured[0]} - {measured[1]}"
    return f"interval meaning: {', '.join(cited)} judges {judged}, but the assertion measures {measures}"


def check_claim(claim: Claim, store: EvidenceStore) -> CheckResult:
    """Apply the claim rules in order and return VERIFIED, UNCORROBORATED or BLOCKED."""

    def blocked(why: str) -> CheckResult:
        return CheckResult(claim, "BLOCKED", [why])

    # R1: every cited evidence id exists, and at least one is cited.
    if not claim.evidence:
        return blocked("no evidence cited")
    missing = [e for e in claim.evidence if not store.has(e)]
    if missing:
        return blocked(f"unknown evidence ids (possible hallucination): {', '.join(missing)}")

    # R4: no legal conclusions, and no driver-state claims without a driver-facing camera.
    if LEGAL.search(claim.text):
        return blocked("legal conclusion: Telltale reconstructs evidence and does not assign legal fault")
    if DRIVER_STATE.search(claim.text) and not store.has("VID:driver_camera"):
        return blocked("driver-state claim: no driver-facing camera evidence exists for this case")

    # R2: the assertion is recomputed from the store, and may only use cited facts.
    allowed: set[float] = set()
    corroborated = False
    if claim.assertion:
        holds, numbers, ids, detail = _eval(claim.assertion, store)
        if not ids:
            return blocked(detail)
        if not set(ids) <= set(claim.evidence):
            return blocked(f"assertion uses facts that are not cited: {sorted(set(ids) - set(claim.evidence))}")
        if not holds:
            return blocked(f"assertion failed on recomputation: {detail}")
        allowed |= numbers
        corroborated = claim.assertion.get("op") in ("agree", "same") and len({i.split(":")[0] for i in ids}) == 2
    # R6 (added after the robustness benchmark): an interval compared with a threshold must be the interval that
    # threshold judges.
    problem = _interval_meaning_problem(claim, store)
    if problem:
        return blocked(problem)
    for evidence_id in claim.evidence:  # cited numeric facts may also be quoted directly
        with contextlib.suppress(TypeError):  # non-numeric facts license no numbers
            allowed.add(_num(store, evidence_id))

    # R3: every number in the prose matches a supported number, allowing ms, km/h and mph conversions.
    text = NAMES.sub(" ", ID_TOKEN.sub(" ", claim.text))
    for token in NUMBER.findall(text):
        if not any(_close(float(token), value * factor) for value in allowed for factor in CONVERSIONS):
            return blocked(f"number {token} in the text is not supported by the cited evidence")

    # R5: a visual observation needs an independent second source.
    if claim.type == "observation" and {e.split(":")[0] for e in claim.evidence} & WITNESS_SOURCES and not corroborated:
        return CheckResult(claim, "UNCORROBORATED", ["single-source visual observation; not independently confirmed"])
    return CheckResult(claim, "VERIFIED", [])


def check_verdict(agent_label: str, store: EvidenceStore) -> dict:
    """Compare the agent's verdict with `ATTR:label`, which deterministic code derived from the same evidence."""
    independent = str(store.get("ATTR:label").value)
    if agent_label == independent:
        return {"agent_label": agent_label, "independent_label": independent, "status": "VERIFIED", "reason": ""}
    return {
        "agent_label": agent_label,
        "independent_label": independent,
        "status": "REJECTED",
        "reason": f"independent recomputation from the same evidence gives {independent}; "
        f"report withheld pending human review",
    }


def check_all(claims: list[Claim], store: EvidenceStore) -> dict:
    results = [check_claim(c, store) for c in claims]
    return {
        "results": results,
        "counts": {s: sum(r.status == s for r in results) for s in ("VERIFIED", "UNCORROBORATED", "BLOCKED")},
    }
