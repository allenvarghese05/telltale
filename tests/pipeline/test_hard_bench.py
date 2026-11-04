import json
from types import SimpleNamespace as NS

import pytest

import telltale.pipeline.hard_bench as hb
from telltale.core.schema import Fact
from telltale.evidence.store import EvidenceStore
from telltale.logs.generate import HARD_EXPECTED, GenerationError

CLIPS = ("cand36", "cand37")


def test_plan_is_deterministic_mixes_profiles_and_gives_unique_seeds():
    plan = hb.hard_plan(CLIPS)
    assert plan == hb.hard_plan(CLIPS)
    assert len(plan) == len(CLIPS) * 2 * len(HARD_EXPECTED)
    assert {p for _, p, _, _ in plan} == {"car", "truck"}
    seeds = [s for *_, s in plan]
    assert len(set(seeds)) == len(seeds)
    assert all(1000 <= s <= 9999 for s in seeds)
    assert {p for _, p, _, _ in plan[:6]} == {"car", "truck"}


def test_summary_counts_a_missing_verdict_as_wrong_and_unflagged():
    rows = [
        {"profile": "car", "family": "tight", "expected": "COMMAND_LATE", "agent": "COMMAND_LATE"},
        {"profile": "truck", "family": "marginal", "expected": "PERCEPTION_LATE", "agent": "COMMAND_LATE"},
        {"profile": "truck", "family": "tight", "expected": "UNAVOIDABLE", "agent": None},
    ]
    for r, status in zip(rows, ("VERIFIED", "REJECTED", "NO_VERDICT"), strict=True):
        r.update(independent=r["expected"], status=status, counts={"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 0})
    s = hb.summarize_hard(rows)
    assert s["n"] == 3
    assert s["agent_wrong"] == 2
    assert s["agent_wrong_flagged"] == 1
    assert s["no_verdict"] == 1
    assert s["verified_but_wrong"] == 0
    assert s["by_profile"] == {"car": {"n": 1, "agent_correct": 1}, "truck": {"n": 2, "agent_correct": 0}}
    assert s["by_family"]["tight"] == {"n": 2, "agent_correct": 1}


def _store(label):
    return EvidenceStore(
        [
            Fact("ATTR:label", label, "", "ATTR", "attr", "derived"),
            Fact("ATTR:excess_perception_s", 0.04, "s", "ATTR", "attr", "derived"),
        ]
    )


@pytest.fixture
def bench(tmp_path, monkeypatch):
    """The hard bench with generation, store building and the agent faked; files go to tmp_path."""
    monkeypatch.setattr(hb, "BENCH_DIR", tmp_path / "bench")
    monkeypatch.setattr(hb, "HARD_CACHE", tmp_path / "cache")
    monkeypatch.setattr(hb, "RESULTS", tmp_path / "results.json")
    monkeypatch.setattr(hb, "clip_ids", lambda: ["cand37"])
    monkeypatch.setattr(hb, "clip_timing", lambda clip_id: clip_id)
    state = {"measured": {}, "verdict": {}, "generated": [], "agent_calls": []}

    def fake_generate(timing, profile, story, seed, out_root, gt_root):
        if story == "unavoidable_with_fault" and profile.name == "car":
            raise GenerationError("no unavoidable_with_fault parameters found")
        case_id = f"{timing}-{profile.name}-s{seed:04d}"
        (out_root / case_id).mkdir(parents=True)
        gt_root.mkdir(parents=True, exist_ok=True)
        (gt_root / f"{case_id}.json").write_text(json.dumps({"expected_label": HARD_EXPECTED[story]}))
        state["generated"].append(case_id)
        return case_id

    def fake_build(case_dir):
        gt = json.loads((hb.BENCH_DIR / "ground_truth" / f"{case_dir.name}.json").read_text())
        return NS(store=_store(state["measured"].get(case_dir.name, gt["expected_label"])), profile=None)

    def fake_agent_run(case_id, clip_id, store, profile, live, cache_dir):
        state["agent_calls"].append(case_id)
        verdict = state["verdict"].get(case_id, store.get("ATTR:label").value)
        if verdict is None:
            raise RuntimeError("investigator did not submit findings within the turn limit")
        claims = [{"text": "Perception took 9 s.", "type": "timing", "evidence": ["ATTR:excess_perception_s"]}]
        return {"verdict": verdict, "claims": claims, "agent_facts": []}

    monkeypatch.setattr(hb, "generate_case", fake_generate)
    monkeypatch.setattr(hb, "build_case_store", fake_build)
    monkeypatch.setattr(hb, "agent_run", fake_agent_run)
    return state


def test_bench_scores_against_ground_truth_and_skips_infeasible_draws(bench):
    result = hb.run_hard_bench(n=4)
    assert len(result["rows"]) == 4
    assert all(r["agent"] == r["expected"] for r in result["rows"])
    assert result["rows"][0]["excess"] == {"perception": 0.04}
    assert result["rows"][0]["blocked"] == [
        {"text": "Perception took 9 s.", "reasons": ["number 9 in the text is not supported by the cited evidence"]}
    ]
    assert json.loads(hb.RESULTS.read_text())["summary"]["n"] == 4


def test_a_draw_whose_measured_label_disagrees_is_discarded_and_remembered(bench):
    first = hb.hard_plan(["cand37"])[0]
    case_id = f"cand37-{first[1]}-s{first[3]:04d}"
    bench["measured"][case_id] = "NO_FAULT_FOUND"
    result = hb.run_hard_bench(n=2)
    assert case_id not in {r["case"] for r in result["rows"]}
    assert not (hb.BENCH_DIR / "cases" / case_id).exists()
    assert case_id in " ".join(result["skipped"])
    bench["generated"].clear()
    hb.run_hard_bench(n=2)
    assert case_id not in bench["generated"]


def test_a_run_that_never_submits_is_scored_wrong_and_not_retried(bench):
    first = hb.hard_plan(["cand37"])[0]
    case_id = f"cand37-{first[1]}-s{first[3]:04d}"
    bench["verdict"][case_id] = None
    result = hb.run_hard_bench(n=1)
    assert result["rows"][0]["status"] == "NO_VERDICT"
    assert result["summary"]["no_verdict"] == 1
    bench["agent_calls"].clear()
    hb.run_hard_bench(n=1)
    assert bench["agent_calls"] == []


def test_other_runtime_errors_are_not_scored_as_agent_failures(bench, monkeypatch):
    def no_key(*_args, **_kwargs):
        raise RuntimeError("MODEL_API_KEY is not set. Use replay mode or add it to .env")

    monkeypatch.setattr(hb, "agent_run", no_key)
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        hb.run_hard_bench(n=1)


def test_cli_hard_flag_runs_the_hard_bench(monkeypatch, capsys):
    from telltale.cli import main

    calls = []
    monkeypatch.setattr(hb, "run_hard_bench", lambda n: calls.append(n) or {"summary": {"n": n}})
    main(["agent-bench", "--hard", "--n", "5"])
    assert calls == [5]
    assert json.loads(capsys.readouterr().out) == {"n": 5}
