# Telltale — 03 Track C: Agent Investigates, Checker Verifies (suggested tool: Claude Code)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Work only in worktree `../telltale-c` (branch `track-c`). Allowed folders: `telltale/verify/`, `telltale/agent/`, `telltale/report/`, `tests/verify/`, `tests/agent/`, `tests/report/`. Import only `telltale.core.schema` and `telltale.evidence.store` from other packages. Physics, witness recheck and the LLM are **injected as callables/clients**, so tests never touch the network or other tracks.

**Goal:**
- **Muse Wonder does the investigation and decides the primary cause.** It uses tools for every number and never sees the checker's answers.
- **The checker (plain code) verifies every claim and independently recomputes the verdict.** Unproven claims are blocked. A disagreeing verdict is rejected and flagged for human review.
- A printable report.

**Why this design (for the README and video):** "Meta's models do the investigation; the checker makes it auditable. Nothing reaches the report until it's proven."

### Bundle fields used by the report (built in `05-integration.md`)
```json
{"case_id": "...", "profile": "car", "digest": "sha256...",
 "verdict": {"agent_label": "PERCEPTION_LATE", "independent_label": "PERCEPTION_LATE", "status": "VERIFIED",
             "reason": "", "noncausal_faults": [], "excess_s": {"perception": 1.05}},
 "claims": [{"claim": {"text": "...", "type": "timing", "evidence": ["..."], "assertion": {}}, "status": "VERIFIED", "reasons": []}],
 "counts": {"VERIFIED": 6, "UNCORROBORATED": 1, "BLOCKED": 1},
 "facts": [{"id": "...", "value": 1.35, "unit": "s", "source": "AV", "derivation": "...", "kind": "measurement"}]}
```

---

### Task C1: Deterministic checker (claims + verdict)

**Files:**
- Create: `telltale/verify/checker.py`
- Test: `tests/verify/test_checker.py`

**Claim rules (in this order):**
1. **R1:** every evidence ID exists, and at least one is cited.
2. **R4:** no legal conclusions, and no driver-state claims without a driver camera.
3. **R2:** the assertion is recomputed from the store and only uses cited facts.
4. **R3:** every number in the text matches a supported number (conversions allowed: ms, km/h, mph).
5. **R5:** a visual observation needs an independent second source (an `agree` or `same` assertion); otherwise it's UNCORROBORATED.

**Verdict rule:** the agent's label must equal `ATTR:label`, which deterministic code computed independently from the same evidence. Otherwise the verdict is REJECTED, with both labels shown.

- [ ] **Step 1: Write the failing test `tests/verify/test_checker.py`**

```python
import pytest

from telltale.core.schema import Claim, Fact
from telltale.evidence.store import EvidenceStore
from telltale.verify.checker import check_all, check_claim, check_verdict


@pytest.fixture
def store():
    return EvidenceStore(
        [
            Fact("VID:lane_entry_t", 2.0, "s", "VID", "sam"),
            Fact("AV:first_seen_t", 3.35, "s", "AV", "mcap"),
            Fact("PROFILE:perception_threshold_s", 0.3, "s", "PROFILE", "car"),
            Fact("ATTR:label", "PERCEPTION_LATE", "", "ATTR", "attr", "derived"),
            Fact("ATTR:noncausal_faults", "none", "", "ATTR", "attr", "derived"),
            Fact("CF:run1_impact_speed_mps", 2.5, "m/s", "CF", "simulate(...)", "derived"),
            Fact("WIT:other_vehicle_lane_change_t", 2.2, "s", "WIT", "spark", "observation"),
            Fact("WIT:other_vehicle_turn_signal", "no", "", "WIT", "spark", "observation"),
            Fact("WIT2:turn_signal", "no", "", "WIT2", "spark recheck", "observation"),
        ]
    )


DIFF = {"op": "diff", "a": "AV:first_seen_t", "b": "VID:lane_entry_t", "equals": 1.35}
EV = ["AV:first_seen_t", "VID:lane_entry_t"]


def test_verified_timing_claim_with_unit_conversion(store):
    c = Claim("Detection came 1.35 s (1350 ms) after the vehicle entered the lane.", "timing", EV, DIFF)
    assert check_claim(c, store).status == "VERIFIED"


def test_unsupported_number_is_blocked(store):
    r = check_claim(Claim("Detection lagged by 0.9 s.", "timing", EV, DIFF), store)
    assert r.status == "BLOCKED" and "0.9" in r.reasons[0]


def test_false_assertion_is_blocked(store):
    assert check_claim(Claim("Detection lagged.", "timing", EV, {**DIFF, "equals": 0.5}), store).status == "BLOCKED"


def test_unknown_evidence_is_blocked(store):
    r = check_claim(Claim("The driver braked.", "timing", ["CAN:driver_brake_t"]), store)
    assert r.status == "BLOCKED" and "unknown evidence" in r.reasons[0]


def test_legal_conclusion_is_blocked(store):
    r = check_claim(Claim("The other driver is at fault.", "attribution", ["VID:lane_entry_t"]), store)
    assert r.status == "BLOCKED" and "legal" in r.reasons[0]


def test_driver_state_is_blocked(store):
    r = check_claim(Claim("The driver was distracted.", "other", ["VID:lane_entry_t"]), store)
    assert r.status == "BLOCKED" and "driver-state" in r.reasons[0]


def test_single_source_observation_is_uncorroborated(store):
    r = check_claim(Claim("The other vehicle did not signal.", "observation", ["WIT:other_vehicle_turn_signal"]), store)
    assert r.status == "UNCORROBORATED"


def test_independent_recheck_corroborates(store):
    c = Claim(
        "The other vehicle did not signal.",
        "observation",
        ["WIT:other_vehicle_turn_signal", "WIT2:turn_signal"],
        {"op": "same", "a": "WIT:other_vehicle_turn_signal", "b": "WIT2:turn_signal"},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_witness_time_agrees_with_sam(store):
    c = Claim(
        "The witness saw the lane change at about 2.2 s, consistent with SAM's 2.0 s.",
        "observation",
        ["WIT:other_vehicle_lane_change_t", "VID:lane_entry_t"],
        {"op": "agree", "a": "WIT:other_vehicle_lane_change_t", "b": "VID:lane_entry_t", "within": 0.5},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_threshold_comparison_and_model_names_ok(store):
    c = Claim(
        "Per SAM 3.1, detection at 3.35 s vs entry at 2.0 s exceeded the 0.3 s tolerance.",
        "timing",
        ["AV:first_seen_t", "VID:lane_entry_t", "PROFILE:perception_threshold_s"],
        DIFF,
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_counterfactual_claim_kmh(store):
    c = Claim(
        "With nominal detection the impact would drop to 9 km/h.",
        "physics",
        ["CF:run1_impact_speed_mps"],
        {"op": "value", "fact": "CF:run1_impact_speed_mps", "equals": 2.5},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_assertion_must_only_use_cited_facts(store):
    assert check_claim(Claim("Lag 1.35 s.", "timing", ["AV:first_seen_t"], DIFF), store).status == "BLOCKED"


def test_verdict_verified_and_rejected(store):
    assert check_verdict("PERCEPTION_LATE", store)["status"] == "VERIFIED"
    r = check_verdict("BRAKE_ACTUATION_LATE", store)
    assert r["status"] == "REJECTED" and "PERCEPTION_LATE" in r["reason"]


def test_check_all_counts(store):
    res = check_all([Claim("The driver was distracted.", "other", ["VID:lane_entry_t"])], store)
    assert res["counts"] == {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 1}
```

- [ ] **Step 2: Run it and confirm it fails.** `pytest tests/verify -v`

- [ ] **Step 3: Write `telltale/verify/checker.py`**

```python
from __future__ import annotations

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


def _close(x: float, y: float) -> bool:
    return abs(x - y) <= max(TOL_ABS, TOL_REL * abs(y))


def _num(store: EvidenceStore, fid: str) -> float:
    v = store.get(fid).value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TypeError(f"{fid} is not numeric")
    return float(v)


def _eval(a: dict, store: EvidenceStore) -> tuple[bool, set[float], list[str], str]:
    op = a.get("op")
    try:
        if op == "value":
            v = _num(store, a["fact"])
            return _close(v, float(a["equals"])), {v}, [a["fact"]], f"{a['fact']}={v}, claimed {a['equals']}"
        if op == "diff":
            va, vb = _num(store, a["a"]), _num(store, a["b"])
            return (
                _close(va - vb, float(a["equals"])),
                {va, vb, va - vb},
                [a["a"], a["b"]],
                f"recomputed {va - vb:.3f}, claimed {a['equals']}",
            )
        if op in ("lt", "gt"):
            v, ids = _num(store, a["fact"]), [a["fact"]]
            if "than_fact" in a:
                th = _num(store, a["than_fact"])
                ids.append(a["than_fact"])
                nums = {v, th}
            else:
                th = float(a["than"])
                nums = {v}
            ok = v < th if op == "lt" else v > th
            return ok, nums, ids, f"{v} {op} {th} is {ok}"
        if op == "agree":
            va, vb = _num(store, a["a"]), _num(store, a["b"])
            return (
                abs(va - vb) <= float(a["within"]),
                {va, vb, abs(va - vb)},
                [a["a"], a["b"]],
                f"|{va}-{vb}| vs {a['within']}",
            )
        if op == "same":
            va, vb = store.get(a["a"]).value, store.get(a["b"]).value
            return str(va).lower() == str(vb).lower(), set(), [a["a"], a["b"]], f"{va!r} vs {vb!r}"
        if op == "is":
            v = store.get(a["fact"]).value
            return str(v).lower() == str(a["equals"]).lower(), set(), [a["fact"]], f"{v!r} vs {a['equals']!r}"
    except (KeyError, TypeError, ValueError) as e:
        return False, set(), [], f"assertion could not be evaluated: {e}"
    return False, set(), [], f"unknown assertion op {op!r}"


def check_claim(claim: Claim, store: EvidenceStore) -> CheckResult:
    def blocked(why: str) -> CheckResult:
        return CheckResult(claim, "BLOCKED", [why])

    if not claim.evidence:
        return blocked("no evidence cited")
    missing = [e for e in claim.evidence if not store.has(e)]
    if missing:
        return blocked(f"unknown evidence ids (possible hallucination): {', '.join(missing)}")
    if LEGAL.search(claim.text):
        return blocked("legal conclusion: Telltale reconstructs evidence and does not assign legal fault")
    if DRIVER_STATE.search(claim.text) and not store.has("VID:driver_camera"):
        return blocked("driver-state claim: no driver-facing camera evidence exists for this case")

    allowed: set[float] = set()
    corroborated = False
    if claim.assertion:
        ok, nums, ids, detail = _eval(claim.assertion, store)
        if not ids:
            return blocked(detail)
        if not set(ids) <= set(claim.evidence):
            return blocked(f"assertion uses facts that are not cited: {sorted(set(ids) - set(claim.evidence))}")
        if not ok:
            return blocked(f"assertion failed on recomputation: {detail}")
        allowed |= nums
        corroborated = claim.assertion.get("op") in ("agree", "same") and len({i.split(":")[0] for i in ids}) == 2
    for e in claim.evidence:  # cited numeric facts may also be quoted directly
        try:
            allowed.add(_num(store, e))
        except TypeError:
            pass

    text = NAMES.sub(" ", ID_TOKEN.sub(" ", claim.text))
    for tok in NUMBER.findall(text):
        if not any(_close(float(tok), a * c) for a in allowed for c in CONVERSIONS):
            return blocked(f"number {tok} in the text is not supported by the cited evidence")

    if claim.type == "observation" and {e.split(":")[0] for e in claim.evidence} & WITNESS_SOURCES and not corroborated:
        return CheckResult(claim, "UNCORROBORATED", ["single-source visual observation; not independently confirmed"])
    return CheckResult(claim, "VERIFIED", [])


def check_verdict(agent_label: str, store: EvidenceStore) -> dict:
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
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/verify -v` → 14 passed.

- [ ] **Step 5: Commit.** `git add telltale/verify tests/verify && git commit -m "feat(verify): claim checker + independent verdict check"`

---

### Task C2: Investigator agent (Muse Wonder decides)

**Files:**
- Create: `telltale/agent/investigator.py`
- Test: `tests/agent/test_investigator.py`

**Tools the agent gets:**
- `list_evidence`: visible facts only; `PHYS:*` and `ATTR:*` are hidden.
- `get_series`
- `measure(a, b)`: exact subtraction, so there's no mental math.
- `run_counterfactual(perception_s, command_s, tau_s)`: creates `CF:run<k>_*` facts.
- `witness_recheck(question, t0, t1, slug)`: creates a `WIT2:*` fact.
- `submit_findings(verdict, claims)`

- [ ] **Step 1: Write the failing test `tests/agent/test_investigator.py`**

```python
import copy
import json
from types import SimpleNamespace as NS

import pytest

from telltale.agent.investigator import investigate
from telltale.core.schema import Fact
from telltale.evidence.store import EvidenceStore


def call(cid, name, args):
    return NS(id=cid, function=NS(name=name, arguments=json.dumps(args)))


def resp(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))])


class FakeLLM:
    def __init__(self, script):
        self.script, self.seen = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.seen.append(copy.deepcopy(kw))  # snapshot: the agent keeps mutating its messages list
        return self.script.pop(0)


STORE = EvidenceStore(
    [
        Fact("VID:lane_entry_t", 2.0, "s", "VID", "sam"),
        Fact("AV:first_seen_t", 3.35, "s", "AV", "mcap"),
        Fact("ATTR:label", "PERCEPTION_LATE", "", "ATTR", "attr", "derived"),
        Fact("PHYS:perception_latency_s", 1.35, "s", "PHYS", "diff", "derived"),
    ],
    {"can.speed_mps": {"t": list(range(500)), "v": [20.0] * 500, "unit": "m/s", "source": "CAN"}},
)
CLAIMS = [
    {
        "text": "Detection came 1.35 s after lane entry.",
        "type": "timing",
        "evidence": ["AV:first_seen_t", "VID:lane_entry_t"],
        "assertion": {"op": "diff", "a": "AV:first_seen_t", "b": "VID:lane_entry_t", "equals": 1.35},
    }
]


def recheck(question, t0, t1, slug):
    return Fact(f"WIT2:{slug}", "no", "", "WIT2", f"recheck {t0}-{t1}: {question}", "observation")


def cf(perception_s, command_s, tau_s):
    return {"contact": perception_s > 1.0, "impact_speed_mps": 3.0 if perception_s > 1.0 else 0.0, "min_gap_m": 0.4}


def test_full_investigation_flow():
    llm = FakeLLM(
        [
            resp(calls=[call("1", "list_evidence", {})]),
            resp(
                calls=[
                    call("2", "measure", {"a": "AV:first_seen_t", "b": "VID:lane_entry_t"}),
                    call("3", "get_series", {"name": "can.speed_mps"}),
                ]
            ),
            resp(calls=[call("4", "run_counterfactual", {"perception_s": 0.2, "command_s": 0.05, "tau_s": 0.15})]),
            resp(
                calls=[
                    call(
                        "5", "witness_recheck", {"question": "Did it signal?", "t0": 1, "t1": 3, "slug": "turn_signal"}
                    )
                ]
            ),
            resp(calls=[call("6", "submit_findings", {"verdict": "PERCEPTION_LATE", "claims": CLAIMS})]),
        ]
    )
    run = investigate(STORE, llm, counterfactual_fn=cf, recheck_fn=recheck, model="m")
    assert run["verdict"] == "PERCEPTION_LATE" and run["claims"] == CLAIMS
    assert [t["name"] for t in run["tool_calls"]] == [
        "list_evidence",
        "measure",
        "get_series",
        "run_counterfactual",
        "witness_recheck",
        "submit_findings",
    ]
    ids = {f["id"] for f in run["agent_facts"]}
    assert {"CF:run1_contact", "CF:run1_impact_speed_mps", "CF:run1_min_gap_m", "WIT2:turn_signal"} <= ids
    listed = json.loads([m for m in llm.seen[1]["messages"] if m["role"] == "tool"][0]["content"])
    assert {f["id"] for f in listed} == {"VID:lane_entry_t", "AV:first_seen_t"}  # checker facts hidden
    measured = json.loads([m for m in llm.seen[2]["messages"] if m["role"] == "tool"][1]["content"])
    assert measured["a_minus_b"] == pytest.approx(1.35)


def test_measure_refuses_hidden_facts():
    llm = FakeLLM(
        [
            resp(calls=[call("1", "measure", {"a": "PHYS:perception_latency_s", "b": "VID:lane_entry_t"})]),
            resp(calls=[call("2", "submit_findings", {"verdict": "PERCEPTION_LATE", "claims": CLAIMS})]),
        ]
    )
    investigate(STORE, llm, model="m")
    assert "error" in json.loads([m for m in llm.seen[1]["messages"] if m["role"] == "tool"][0]["content"])


def test_invalid_verdict_must_be_resubmitted():
    llm = FakeLLM(
        [
            resp(calls=[call("1", "submit_findings", {"verdict": "SOMEONE_ELSE", "claims": CLAIMS})]),
            resp(calls=[call("2", "submit_findings", {"verdict": "UNAVOIDABLE", "claims": CLAIMS})]),
        ]
    )
    assert investigate(STORE, llm, model="m")["verdict"] == "UNAVOIDABLE"


def test_nudged_when_answering_in_prose_and_fails_if_never_submits():
    llm = FakeLLM(
        [
            resp(content="analysis..."),
            resp(calls=[call("1", "submit_findings", {"verdict": "UNAVOIDABLE", "claims": []})]),
        ]
    )
    assert investigate(STORE, llm, model="m")["verdict"] == "UNAVOIDABLE"
    with pytest.raises(RuntimeError):
        investigate(STORE, FakeLLM([resp(content="x")] * 3), model="m", max_turns=3)
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/agent/investigator.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Callable

from telltale.core.schema import HIDDEN_FROM_AGENT, LABELS, Fact
from telltale.evidence.store import EvidenceStore

SYSTEM = """You are Telltale's lead forensic investigator for vehicle collisions. You determine the primary
contributing factor from evidence. You never assign legal fault.

METHOD
1. list_evidence. Build the timeline: VID:lane_entry_t (vehicle enters our lane), AV:first_seen_t (system detects),
   AV:brake_request_t or AV:handoff_t (decision), CAN:brake_request_t and CAN:pressure_reached_t (brakes engage),
   VID:impact_t.
2. Use measure for every interval. Never compute numbers yourself.
   perception = AV:first_seen_t - VID:lane_entry_t;  command = AV:brake_request_t - AV:first_seen_t
   actuation = CAN:pressure_reached_t - CAN:brake_request_t;  handoff margin = VID:impact_t - AV:handoff_t
3. Compare each with its PROFILE threshold (perception/command/actuation threshold, human_prt for handoff margin).
4. But-for test: call run_counterfactual with PROFILE nominal values (nominal_perception_s, nominal_command_s,
   nominal_tau_s). If contact is still true, the verdict is UNAVOIDABLE. If it's avoided, the primary factor is the
   layer whose measured value exceeds its threshold by the most. If the counterfactual avoids the crash and nothing
   exceeds a threshold, the verdict is NO_FAULT_FOUND.
5. If DATA:brake_log_complete is false, the verdict is INCONCLUSIVE.
6. Witness facts (WIT:*) are single-source. For important visual observations, call witness_recheck on a short window
   and cite both facts with a 'same' or 'agree' assertion.
7. submit_findings with verdict (one of: PERCEPTION_LATE, COMMAND_LATE, BRAKE_ACTUATION_LATE, LATE_HANDOFF,
   UNAVOIDABLE, NO_FAULT_FOUND, INCONCLUSIVE) and 5-10 claims.

CLAIM FORMAT: each claim cites existing evidence ids and includes an assertion the checker can recompute:
  {"op":"diff","a":ID,"b":ID,"equals":n} | {"op":"value","fact":ID,"equals":n} | {"op":"gt"|"lt","fact":ID,"than_fact":ID}
  {"op":"agree","a":ID,"b":ID,"within":n} | {"op":"same","a":ID,"b":ID} | {"op":"is","fact":ID,"equals":value}
Every number in claim text must come from the cited facts (you may convert s->ms, m/s->km/h or mph; round to 2 decimals).
Example: {"text":"The system detected the vehicle 1.35 s after it entered the lane.","type":"timing",
 "evidence":["AV:first_seen_t","VID:lane_entry_t"],"assertion":{"op":"diff","a":"AV:first_seen_t","b":"VID:lane_entry_t","equals":1.35}}
An independent deterministic checker verifies every claim and your verdict. Unsupported, legal or driver-state claims
are blocked."""


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


NUM = {"type": "number"}
TOOLS = [
    _fn("list_evidence", "List visible evidence facts (id, value, unit, source, derivation).", {}, []),
    _fn(
        "get_series",
        "Time series in video seconds, at most 200 points.",
        {"name": {"type": "string"}, "t0": NUM, "t1": NUM},
        ["name"],
    ),
    _fn(
        "measure",
        "Exact a minus b for two numeric fact ids.",
        {"a": {"type": "string"}, "b": {"type": "string"}},
        ["a", "b"],
    ),
    _fn(
        "run_counterfactual",
        "Replay the crash physics with given timings. Creates citable CF:run<k>_* facts.",
        {"perception_s": NUM, "command_s": NUM, "tau_s": NUM},
        ["perception_s", "command_s", "tau_s"],
    ),
    _fn(
        "witness_recheck",
        "Independent vision model answers a yes/no question about a short video window. Creates a WIT2 fact.",
        {"question": {"type": "string"}, "t0": NUM, "t1": NUM, "slug": {"type": "string"}},
        ["question", "t0", "t1", "slug"],
    ),
    _fn(
        "submit_findings",
        "Submit the verdict and structured claims.",
        {
            "verdict": {"type": "string", "enum": list(LABELS)},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["timing", "physics", "observation", "attribution", "other"],
                        },
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "assertion": {"type": "object"},
                    },
                    "required": ["text", "type", "evidence"],
                },
            },
        },
        ["verdict", "claims"],
    ),
]


def _downsample(s: dict, n: int = 200) -> dict:
    step = -(-len(s["t"]) // n) or 1
    return {**s, "t": s["t"][::step], "v": s["v"][::step]}


def _assistant_dict(msg) -> dict:
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
            }
            for c in msg.tool_calls
        ]
    return d


def investigate(
    store: EvidenceStore,
    llm,
    counterfactual_fn: Callable[[float, float, float], dict] | None = None,
    recheck_fn: Callable[..., Fact] | None = None,
    model: str = "muse-wonder-1.0",
    max_turns: int = 16,
) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Investigate this case. Evidence store digest: {store.digest}."},
    ]
    tool_calls: list[dict] = []
    agent_facts: list[Fact] = []
    cf_runs = 0

    def visible_num(fid: str) -> float:
        if fid.startswith(HIDDEN_FROM_AGENT) or not store.has(fid):
            raise KeyError(f"{fid} is not available")
        v = store.get(fid).value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError(f"{fid} is not numeric")
        return float(v)

    for _ in range(max_turns):
        msg = llm.chat.completions.create(model=model, messages=messages, tools=TOOLS).choices[0].message
        messages.append(_assistant_dict(msg))
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Call submit_findings with your verdict and claims now."})
            continue
        for c in msg.tool_calls:
            name, args = c.function.name, json.loads(c.function.arguments or "{}")
            tool_calls.append(
                {
                    "name": name,
                    "args": args
                    if name != "submit_findings"
                    else {"verdict": args.get("verdict"), "n_claims": len(args.get("claims", []))},
                }
            )
            if name == "submit_findings":
                if args.get("verdict") in LABELS:
                    return {
                        "model": model,
                        "digest": store.digest,
                        "verdict": args["verdict"],
                        "claims": args.get("claims", []),
                        "tool_calls": tool_calls,
                        "agent_facts": [asdict(f) for f in agent_facts],
                    }
                out = {"error": f"verdict must be one of {list(LABELS)}"}
            elif name == "list_evidence":
                out = [asdict(f) for f in store.agent_facts()]
            elif name == "get_series":
                try:
                    out = _downsample(store.series(args["name"], args.get("t0"), args.get("t1")))
                except KeyError:
                    out = {"error": f"unknown series; available: {store.series_names()}"}
            elif name == "measure":
                try:
                    a, b = visible_num(args["a"]), visible_num(args["b"])
                    out = {"a": args["a"], "b": args["b"], "a_minus_b": round(a - b, 4)}
                except (KeyError, TypeError) as e:
                    out = {"error": str(e)}
            elif name == "run_counterfactual" and counterfactual_fn is not None:
                cf_runs += 1
                p, cmd, tau = float(args["perception_s"]), float(args["command_s"]), float(args["tau_s"])
                r = counterfactual_fn(p, cmd, tau)
                how = f"simulate(perception={p}, command={cmd}, tau={tau})"
                new = [
                    Fact(f"CF:run{cf_runs}_contact", bool(r["contact"]), "", "CF", how, "derived"),
                    Fact(
                        f"CF:run{cf_runs}_impact_speed_mps",
                        round(float(r["impact_speed_mps"]), 4),
                        "m/s",
                        "CF",
                        how,
                        "derived",
                    ),
                    Fact(f"CF:run{cf_runs}_min_gap_m", round(float(r["min_gap_m"]), 4), "m", "CF", how, "derived"),
                ]
                store = store.extended(new)
                agent_facts.extend(new)
                out = [asdict(f) for f in new]
            elif name == "witness_recheck" and recheck_fn is not None:
                f = recheck_fn(args["question"], float(args["t0"]), float(args["t1"]), args["slug"])
                store = store.extended([f])
                agent_facts.append(f)
                out = asdict(f)
            else:
                out = {"error": f"tool {name} unavailable in this run"}
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(out)})
    raise RuntimeError("investigator did not submit findings within the turn limit")
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/agent -v` → 4 passed.

- [ ] **Step 5: Commit.** `git add telltale/agent tests/agent && git commit -m "feat(agent): Muse Wonder investigator decides via tools; checker facts hidden"`

---

### Task C3: Printable report

**Files:**
- Create: `telltale/report/render.py`
- Test: `tests/report/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
from telltale.report.render import render_html

BUNDLE = {
    "case_id": "nx01-car-s0101",
    "profile": "car",
    "digest": "abc123",
    "verdict": {
        "agent_label": "PERCEPTION_LATE",
        "independent_label": "PERCEPTION_LATE",
        "status": "VERIFIED",
        "reason": "",
        "noncausal_faults": [],
        "excess_s": {"perception": 1.05},
    },
    "claims": [
        {
            "claim": {"text": "Detection lagged 1.35 s.", "type": "timing", "evidence": ["AV:first_seen_t"]},
            "status": "VERIFIED",
            "reasons": [],
        },
        {
            "claim": {"text": "No signal.", "type": "observation", "evidence": ["WIT:x"]},
            "status": "UNCORROBORATED",
            "reasons": ["single-source"],
        },
        {
            "claim": {"text": "Driver <b>distracted</b>.", "type": "other", "evidence": ["VID:x"]},
            "status": "BLOCKED",
            "reasons": ["driver-state"],
        },
    ],
    "counts": {"VERIFIED": 1, "UNCORROBORATED": 1, "BLOCKED": 1},
    "facts": [
        {
            "id": "AV:first_seen_t",
            "value": 3.35,
            "unit": "s",
            "source": "AV",
            "derivation": "mcap",
            "kind": "measurement",
        }
    ],
}


def test_report_contents():
    html = render_html(BUNDLE)
    assert "Detection lagged 1.35 s." in html and "independently verified" in html
    assert "does not assign legal fault" in html and "1 claim blocked" in html
    assert "<b>distracted</b>" not in html and "abc123" in html


def test_rejected_verdict_is_withheld():
    b = {
        **BUNDLE,
        "verdict": {
            **BUNDLE["verdict"],
            "agent_label": "BRAKE_ACTUATION_LATE",
            "status": "REJECTED",
            "reason": "independent recomputation gives PERCEPTION_LATE",
        },
    }
    assert "withheld" in render_html(b).lower()
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/report/render.py`**

```python
from html import escape

LABELS = {
    "PERCEPTION_LATE": "Perception / driver-assist detected the hazard late",
    "COMMAND_LATE": "The hazard was detected in time, but braking was commanded late",
    "BRAKE_ACTUATION_LATE": "Brakes built pressure too slowly",
    "LATE_HANDOFF": "System handed control back too late for a human to react",
    "UNAVOIDABLE": "Physically unavoidable: a nominal system would still have collided",
    "NO_FAULT_FOUND": "Avoidable, but no layer exceeded tolerance",
    "INCONCLUSIVE": "Inconclusive: evidence is incomplete",
}


def render_html(b: dict) -> str:
    v = b["verdict"]
    verified = [c for c in b["claims"] if c["status"] == "VERIFIED"]
    unc = [c for c in b["claims"] if c["status"] == "UNCORROBORATED"]
    n_blocked = sum(c["status"] == "BLOCKED" for c in b["claims"])

    def li(c):
        return (
            f"<li>{escape(c['claim']['text'])}<div class='ev'>{escape(' · '.join(c['claim']['evidence']))}</div></li>"
        )

    if v["status"] == "VERIFIED":
        head = (
            f"<b>Primary contributing factor:</b> {escape(LABELS.get(v['agent_label'], v['agent_label']))}"
            f"<div class='ok'>Concluded by the Muse Wonder investigator and independently verified by deterministic recomputation.</div>"
        )
    else:
        head = (
            f"<b>Verdict withheld pending human review.</b> Investigator concluded "
            f"{escape(LABELS.get(v['agent_label'], v['agent_label']))}; {escape(v['reason'])}."
        )
    nc = (
        f"<p>Faults present but not causal: {escape(', '.join(v['noncausal_faults']))}</p>"
        if v.get("noncausal_faults")
        else ""
    )
    facts = "".join(
        f"<tr><td>{escape(f['id'])}</td><td>{escape(str(f['value']))} {escape(f['unit'])}</td>"
        f"<td>{escape(f['derivation'])}</td></tr>"
        for f in b["facts"]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Telltale report {escape(b["case_id"])}</title>
<style>body{{font:14px/1.5 system-ui;max-width:860px;margin:24px auto;color:#111}}h1{{margin:0}}
.verdict{{border:2px solid #111;padding:12px;margin:16px 0}}.ok{{color:#1a7f37}}.ev{{color:#666;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}td{{border-top:1px solid #ddd;padding:4px}}
@media print{{button{{display:none}}}}</style></head><body>
<button onclick="window.print()">Save as PDF</button>
<h1>Telltale incident reconstruction</h1><p>Case {escape(b["case_id"])} · profile {escape(b["profile"])}</p>
<div class="verdict">{head}{nc}</div>
<h2>Verified findings</h2><ol>{"".join(li(c) for c in verified)}</ol>
<h2>Single-source observations (not independently confirmed)</h2><ul>{"".join(li(c) for c in unc) or "<li>none</li>"}</ul>
<p><b>{n_blocked} claim{"s" if n_blocked != 1 else ""} blocked</b> by the deterministic checker.</p>
<h2>Evidence</h2><table>{facts}</table>
<p class="ev">Evidence digest (SHA-256): {escape(b["digest"])}</p>
<p class="ev">This report reconstructs evidence. It does not assign legal fault. A qualified human reviewer must sign off.</p>
</body></html>"""
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/report -v`

- [ ] **Step 5: Commit.** `git add telltale/report tests/report && git commit -m "feat(report): verified-findings report with verdict status"`
