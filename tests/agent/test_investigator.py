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
        Fact("VID:hazard_onset_t", 2.0, "s", "VID", "sam"),
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
        "evidence": ["AV:first_seen_t", "VID:hazard_onset_t"],
        "assertion": {"op": "diff", "a": "AV:first_seen_t", "b": "VID:hazard_onset_t", "equals": 1.35},
    }
]


def recheck(question, t0, t1, slug):
    return Fact(f"WIT2:{slug}", "no", "", "WIT2", f"recheck {t0}-{t1}: {question}", "observation")


def cf(perception_s, _command_s, _tau_s):
    return {"contact": perception_s > 1.0, "impact_speed_mps": 3.0 if perception_s > 1.0 else 0.0, "min_gap_m": 0.4}


def test_full_investigation_flow():
    llm = FakeLLM(
        [
            resp(calls=[call("1", "list_evidence", {})]),
            resp(
                calls=[
                    call("2", "measure", {"a": "AV:first_seen_t", "b": "VID:hazard_onset_t"}),
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
    assert run["verdict"] == "PERCEPTION_LATE"
    assert run["claims"] == CLAIMS
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
    listed = json.loads(next(m for m in llm.seen[1]["messages"] if m["role"] == "tool")["content"])
    assert {f["id"] for f in listed} == {"VID:hazard_onset_t", "AV:first_seen_t"}  # checker facts hidden
    measured = json.loads([m for m in llm.seen[2]["messages"] if m["role"] == "tool"][1]["content"])
    assert measured["a_minus_b"] == pytest.approx(1.35)


def test_measure_refuses_hidden_facts():
    llm = FakeLLM(
        [
            resp(calls=[call("1", "measure", {"a": "PHYS:perception_latency_s", "b": "VID:hazard_onset_t"})]),
            resp(calls=[call("2", "submit_findings", {"verdict": "PERCEPTION_LATE", "claims": CLAIMS})]),
        ]
    )
    investigate(STORE, llm, model="m")
    assert "error" in json.loads(next(m for m in llm.seen[1]["messages"] if m["role"] == "tool")["content"])


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


def test_a_repeated_recheck_slug_gets_an_error_instead_of_crashing_the_run():
    """A live run crashed when the agent rechecked the same slug twice (duplicate WIT2 fact id)."""
    calls = []

    def counting_recheck(question, t0, t1, slug):
        calls.append(slug)
        return recheck(question, t0, t1, slug)

    ask = {"question": "Brake lights?", "t0": 1, "t1": 3, "slug": "brake_lights"}
    llm = FakeLLM(
        [
            resp(calls=[call("1", "witness_recheck", ask)]),
            resp(calls=[call("2", "witness_recheck", ask)]),
            resp(calls=[call("3", "submit_findings", {"verdict": "PERCEPTION_LATE", "claims": CLAIMS})]),
        ]
    )
    run = investigate(STORE, llm, recheck_fn=counting_recheck, model="m")
    assert run["verdict"] == "PERCEPTION_LATE"
    assert calls == ["brake_lights"]  # the repeat is refused before a second (paid) video upload
    second = json.loads([m for m in llm.seen[2]["messages"] if m["role"] == "tool"][1]["content"])
    assert "already" in second["error"]
    assert "WIT2:brake_lights" in second["error"]
    assert [f["id"] for f in run["agent_facts"]] == ["WIT2:brake_lights"]


def test_two_slugs_that_map_to_one_fact_id_do_not_crash_the_run():
    def same_id_recheck(question, t0, t1, slug):
        return Fact("WIT2:lights", "no", "", "WIT2", f"recheck {t0}-{t1}: {question}", "observation")

    llm = FakeLLM(
        [
            resp(calls=[call("1", "witness_recheck", {"question": "a", "t0": 1, "t1": 2, "slug": "Lights"})]),
            resp(calls=[call("2", "witness_recheck", {"question": "b", "t0": 1, "t1": 2, "slug": "lights!"})]),
            resp(calls=[call("3", "submit_findings", {"verdict": "PERCEPTION_LATE", "claims": CLAIMS})]),
        ]
    )
    run = investigate(STORE, llm, recheck_fn=same_id_recheck, model="m")
    second = json.loads([m for m in llm.seen[2]["messages"] if m["role"] == "tool"][1]["content"])
    assert "already" in second["error"]
    assert [f["id"] for f in run["agent_facts"]] == ["WIT2:lights"]
