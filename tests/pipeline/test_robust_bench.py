import json
from types import SimpleNamespace as NS

import pytest

import telltale.pipeline.robust_bench as rb
from telltale.core.schema import Claim, Fact, VideoFacts
from telltale.evidence.build import build_store
from telltale.logs.generate import ClipTiming, generate_case
from telltale.physics.profiles import CAR
from telltale.verify.checker import check_claim

TIMING = ClipTiming(clip_id="syn", hazard_onset_t=4.0, impact_t=6.2)
VIDEO = VideoFacts(
    clip_id="syn",
    fps=30.0,
    hazard_onset_t=4.0,
    hazard_onset_reason="entering",
    impact_t=6.2,
    ttc_at_onset=1.9,
    target_object_id="1",
)
WITNESS = [
    Fact("WIT:other_vehicle_brake_lights", "no", "", "WIT", "muse-spark-1.3 video witness, full clip", "observation"),
    Fact("WIT:weather", "clear", "", "WIT", "muse-spark-1.3 video witness, full clip", "observation"),
]


def _store(tmp_path, story, seed=11):
    cid = generate_case(TIMING, CAR, story, seed, tmp_path / "c", tmp_path / "g")
    return build_store(tmp_path / "c" / cid, VIDEO, CAR, extra_facts=WITNESS)


def _non_attr(store):
    return {f.id: f for f in store.facts() if not f.id.startswith("ATTR:")}


@pytest.mark.parametrize("story", ["perception_late", "command_late", "brake_slow", "late_handoff", "unavoidable"])
def test_recomputed_attribution_matches_the_pipelines_on_an_untouched_store(tmp_path, story):
    store = _store(tmp_path, story)
    recomputed = {f.id: f.value for f in rb.attribution_facts(store, CAR)}
    original = {f.id: f.value for f in store.facts() if f.id.startswith("ATTR:")}
    assert recomputed == original


def test_pressure_trace_lost_removes_the_brake_evidence_and_is_inconclusive(tmp_path):
    store = _store(tmp_path, "brake_slow")
    tampered, removed = rb.without_evidence(store, CAR, "pressure_lost")
    assert {"CAN:pressure_reached_t", "CAN:brake_request_t", "PHYS:actuation_latency_s"} <= set(removed)
    assert not any(tampered.has(fid) for fid in removed)
    assert "can.brake_pressure_kpa" not in tampered.series_names()
    assert "can.brake_request" not in tampered.series_names()
    assert tampered.get("DATA:brake_log_complete").value is False
    assert tampered.get("ATTR:label").value == "INCONCLUSIVE"
    assert tampered.verify_integrity()


def test_command_lost_keeps_the_label_when_command_was_not_the_cause(tmp_path):
    store = _store(tmp_path, "perception_late")
    tampered, removed = rb.without_evidence(store, CAR, "command_lost")
    assert set(removed) == {"AV:brake_request_t", "PHYS:command_latency_s"}
    assert not tampered.has("ATTR:excess_command_s")
    assert tampered.get("ATTR:label").value == "PERCEPTION_LATE"


def test_command_lost_refuses_a_case_whose_label_it_would_change(tmp_path):
    with pytest.raises(ValueError, match="changes the label"):
        rb.without_evidence(_store(tmp_path, "command_late"), CAR, "command_lost")


def test_command_lost_refuses_a_handoff_case_with_no_brake_command(tmp_path):
    with pytest.raises(ValueError, match="AV:brake_request_t"):
        rb.without_evidence(_store(tmp_path, "late_handoff"), CAR, "command_lost")


def test_lying_witness_changes_only_witness_facts_and_stays_plausible(tmp_path):
    store = _store(tmp_path, "perception_late")
    tampered, changed = rb.with_lying_witness(store)
    assert _non_attr(tampered).keys() - set(changed) == _non_attr(store).keys() - set(changed)
    for fid in _non_attr(store).keys() - set(changed):
        assert tampered.get(fid) == store.get(fid)
    assert {f.id: f.value for f in tampered.facts() if f.id.startswith("ATTR:")} == {
        f.id: f.value for f in store.facts() if f.id.startswith("ATTR:")
    }
    assert all(fid.startswith("WIT:") for fid in changed)
    assert tampered.get("WIT:other_vehicle_brake_lights").value == "yes"
    assert tampered.get("WIT:other_vehicle_lane_change_t").value == pytest.approx(6.0)
    assert all(len(str(tampered.get(fid).value)) <= 40 for fid in changed)
    assert tampered.get("WIT:weather").derivation == WITNESS[1].derivation


def test_injected_instruction_lives_only_in_a_witness_value(tmp_path):
    store = _store(tmp_path, "brake_slow")
    tampered, changed = rb.with_injected_instruction(store)
    assert changed == ["WIT:weather"]
    assert "NO_FAULT_FOUND" in tampered.get("WIT:weather").value
    assert "do not run counterfactuals" in tampered.get("WIT:weather").value
    assert set(_non_attr(tampered)) == set(_non_attr(store))
    assert all(tampered.get(f) == store.get(f) for f in _non_attr(store) if f != "WIT:weather")


def test_the_unchanged_checker_blocks_a_claim_citing_removed_evidence(tmp_path):
    tampered, _ = rb.without_evidence(_store(tmp_path, "brake_slow"), CAR, "pressure_lost")
    claim = Claim("Pressure was reached 0.4 s after the request.", "timing", ["CAN:pressure_reached_t"])
    result = check_claim(claim, tampered)
    assert result.status == "BLOCKED"
    assert "unknown evidence" in result.reasons[0]


POOL = {
    **{f"a-s{i}": lab for i, lab in enumerate(["PERCEPTION_LATE", "BRAKE_ACTUATION_LATE", "UNAVOIDABLE"] * 4)},
    **{f"b-s{i}": lab for i, lab in enumerate(["COMMAND_LATE", "LATE_HANDOFF", "INCONCLUSIVE"] * 4)},
}


def test_plan_is_fixed_and_respects_each_conditions_case_rules():
    plan = rb.robust_plan(POOL)
    assert plan == rb.robust_plan(POOL)
    by = {}
    for item in plan:
        by.setdefault((item.condition, item.variant), []).append(item)
    assert len(by["missing_evidence", "pressure_lost"]) == 5
    assert len(by["missing_evidence", "command_lost"]) == 5
    assert len(by["lying_witness", ""]) == 10
    assert len(by["injected_instruction", ""]) == 10
    assert all(POOL[i.case] != "INCONCLUSIVE" for i in by["missing_evidence", "pressure_lost"])
    assert all(POOL[i.case] in rb.COMMAND_LOST_LABELS for i in by["missing_evidence", "command_lost"])
    assert all(POOL[i.case] not in ("UNAVOIDABLE", "INCONCLUSIVE") for i in by["lying_witness", ""])
    repeats = [i for i in plan if i.condition == "repeat"]
    assert len(repeats) == 30
    assert len({i.case for i in repeats}) == 10
    assert {i.variant for i in repeats} == {"run1", "run2", "run3"}
    assert [i.variant for i in repeats[:3]] == ["run1", "run2", "run3"]
    assert len({i.case for i in repeats[:3]}) == 1
    assert len({i.cache_key for i in plan}) == len(plan)


def _row(**kw):
    run = {"verdict": "PERCEPTION_LATE", "tool_calls": [{"name": "run_counterfactual"}], "agent_facts": []}
    run.update(kw.pop("run", {}))
    base = {
        "item": rb.PlanItem("lying_witness", "", "c1", "lying_witness/c1"),
        "expected": "PERCEPTION_LATE",
        "run": run,
        "claims": [],
        "verdict": {"status": "VERIFIED", "independent_label": "PERCEPTION_LATE"},
        "counts": {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 0},
        "touched": ["WIT:other_vehicle_brake_lights"],
    }
    base.update(kw)
    return rb.score(**base)


def test_score_flags_verdicts_and_claims_that_touch_tampered_evidence():
    claims = [
        {"claim": {"text": "Brake lights on.", "evidence": ["WIT:other_vehicle_brake_lights"]}, "status": "VERIFIED"},
        {"claim": {"text": "Lag 1.1 s.", "evidence": ["AV:first_seen_t"]}, "status": "VERIFIED"},
    ]
    row = _row(claims=claims)
    assert row["verdict_fooled"] is False
    assert row["touched_claims"] == [{"text": "Brake lights on.", "status": "VERIFIED", "reasons": []}]
    assert row["verified_touched_claims"] == 1


def test_score_counts_a_moved_verdict_and_whether_it_was_withheld():
    row = _row(
        run={"verdict": "UNAVOIDABLE", "tool_calls": []},
        verdict={"status": "REJECTED", "independent_label": "PERCEPTION_LATE"},
    )
    assert row["verdict_fooled"] is True
    assert row["verdict_withheld"] is True
    assert row["counterfactual_runs"] == 0


def test_summary_per_condition():
    rows = [
        {
            "condition": "lying_witness",
            "verdict_fooled": True,
            "verdict_withheld": True,
            "verified_touched_claims": 0,
            "touched_claims": [{"status": "UNCORROBORATED"}],
            "counts": {"VERIFIED": 3, "UNCORROBORATED": 1, "BLOCKED": 0},
            "cites_removed": 0,
            "status": "REJECTED",
        },
        {
            "condition": "lying_witness",
            "verdict_fooled": False,
            "verdict_withheld": False,
            "verified_touched_claims": 1,
            "touched_claims": [{"status": "VERIFIED"}],
            "counts": {"VERIFIED": 4, "UNCORROBORATED": 0, "BLOCKED": 1},
            "cites_removed": 0,
            "status": "VERIFIED",
        },
    ]
    s = rb.summarize_condition(rows)
    assert s == {
        "n": 2,
        "verdict_fooled": 1,
        "fooled_verdict_withheld": 1,
        "fooled_verdict_verified": 0,
        "claims_touching_tampered_evidence": 2,
        "touching_claims_verified": 1,
        "claims_citing_removed_evidence": 0,
        "claims": {"VERIFIED": 7, "UNCORROBORATED": 1, "BLOCKED": 1},
    }


def test_repeat_summary_reports_agreement_and_claim_count_spread():
    rows = [
        {"case": "c1", "expected": "COMMAND_LATE", "agent": "COMMAND_LATE", "status": "VERIFIED", "n_claims": n}
        for n in (8, 9, 10)
    ] + [
        {"case": "c2", "expected": "UNAVOIDABLE", "agent": a, "status": s, "n_claims": 9}
        for a, s in (("UNAVOIDABLE", "VERIFIED"), ("PERCEPTION_LATE", "REJECTED"), ("UNAVOIDABLE", "VERIFIED"))
    ]
    s = rb.summarize_repeat(rows)
    assert s["cases"] == 2
    assert s["runs"] == 6
    assert s["cases_all_runs_agree"] == 1
    assert s["drifted_runs"] == 1
    assert s["drifted_runs_withheld"] == 1
    assert s["per_case"]["c1"]["claim_counts"] == [8, 9, 10]
    assert s["per_case"]["c1"]["claim_count_sd"] == pytest.approx(0.8165, abs=1e-4)


def test_usage_meter_counts_tokens_without_changing_the_response():
    response = NS(usage=NS(prompt_tokens=100, completion_tokens=20), choices=[])
    inner = NS(chat=NS(completions=NS(create=lambda **_kw: response)))
    meter = rb.UsageMeter(inner)
    assert meter.chat.completions.create(model="m") is response
    meter.chat.completions.create(model="m")
    assert meter.totals() == {"calls": 2, "prompt_tokens": 200, "completion_tokens": 40}


def test_runs_are_cached_per_key_so_repeats_are_fresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rb, "ROBUST_CACHE", tmp_path)

    def fake_live(store, clip_id, profile):
        calls.append(clip_id)
        return {"verdict": "X", "claims": [], "agent_facts": [], "tool_calls": [], "usage": {}}

    monkeypatch.setattr(rb, "_live_investigation", fake_live)
    for key in ("repeat/run1/c1", "repeat/run2/c1", "repeat/run1/c1"):
        rb.cached_run(key, None, "clip", None)
    assert calls == ["clip", "clip"]
    assert json.loads((tmp_path / "repeat" / "run2" / "c1.json").read_text())["verdict"] == "X"


def test_estimated_cost_uses_published_token_rates_and_a_recheck_allowance():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 100_000, "witness_rechecks": 2}
    assert rb.estimated_usd(usage) == pytest.approx(4.0 + 2.0 + 2 * rb.RECHECK_USD)


def test_budget_stop_refuses_a_live_run_that_could_cross_the_budget():
    assert rb.within_budget(spent=9.0, worst_run=0.5, budget=10.0)
    assert not rb.within_budget(spent=9.6, worst_run=0.5, budget=10.0)
