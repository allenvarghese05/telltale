import json

import pytest

from telltale.pipeline.red_team import RED_TEAM_NOTE, alter_run, make_red_team_case

RUN = {
    "verdict": "PERCEPTION_LATE",
    "digest": "abc",
    "model": "muse-wonder",
    "tool_calls": [],
    "agent_facts": [],
    "claims": [
        {
            "text": "The hazard-to-impact interval was 1.8667 s.",
            "type": "timing",
            "evidence": ["VID:impact_t", "VID:hazard_onset_t"],
            "assertion": {"op": "diff", "a": "VID:impact_t", "b": "VID:hazard_onset_t", "equals": 1.8667},
        },
        {
            "text": "Perception took 1.1023 s from hazard onset to first detection, above the 0.3 s threshold.",
            "type": "timing",
            "evidence": ["AV:first_seen_t", "VID:hazard_onset_t"],
            "assertion": {"op": "diff", "a": "AV:first_seen_t", "b": "VID:hazard_onset_t", "equals": 1.1023},
        },
    ],
}


def test_alters_one_claims_number_in_both_its_text_and_its_assertion():
    altered = alter_run(RUN, claim_index=1, value=0.25, verdict="NO_FAULT_FOUND")
    claim = altered["claims"][1]
    assert claim["assertion"]["equals"] == 0.25
    assert claim["text"].startswith("Perception took 0.25 s")
    assert "0.3 s threshold" in claim["text"]
    assert altered["claims"][0] == RUN["claims"][0]


def test_replaces_the_verdict_and_records_exactly_what_changed():
    altered = alter_run(RUN, claim_index=1, value=0.25, verdict="NO_FAULT_FOUND")
    assert altered["verdict"] == "NO_FAULT_FOUND"
    assert altered["red_team"] == {
        "claim_index": 1,
        "original_value": 1.1023,
        "altered_value": 0.25,
        "original_verdict": "PERCEPTION_LATE",
        "altered_verdict": "NO_FAULT_FOUND",
    }


def test_never_modifies_the_real_run():
    before = json.dumps(RUN, sort_keys=True)
    alter_run(RUN, claim_index=1, value=0.25, verdict="NO_FAULT_FOUND")
    assert json.dumps(RUN, sort_keys=True) == before


def test_rejects_a_verdict_that_is_not_a_label():
    with pytest.raises(ValueError, match="not a verdict label"):
        alter_run(RUN, claim_index=1, value=0.25, verdict="GUILTY")


def test_rejects_a_claim_without_a_numeric_assertion():
    run = {**RUN, "claims": [{"text": "Lighting was daylight.", "assertion": {"op": "same", "a": "x", "b": "y"}}]}
    with pytest.raises(ValueError, match="no numeric assertion"):
        alter_run(run, claim_index=0, value=0.25, verdict="NO_FAULT_FOUND")


def test_rejects_a_claim_whose_text_does_not_quote_the_figure():
    run = {**RUN, "claims": [{**RUN["claims"][1], "text": "Perception was slow."}]}
    with pytest.raises(ValueError, match="does not quote"):
        alter_run(run, claim_index=0, value=0.25, verdict="NO_FAULT_FOUND")


def test_makes_a_labelled_copy_of_a_real_case(tmp_path):
    cases, agent = tmp_path / "cases", tmp_path / "agent"
    (cases / "cand36-car-s1775").mkdir(parents=True)
    (cases / "cand36-car-s1775" / "case.json").write_text(
        json.dumps({"case_id": "cand36-car-s1775", "clip_id": "cand36", "profile": "car"})
    )
    (cases / "cand36-car-s1775" / "vehicle.can.log").write_text("log")
    agent.mkdir()
    (agent / "cand36-car-s1775.json").write_text(json.dumps(RUN))

    made = make_red_team_case(
        "cand36-car-s1775", "cand36-redteam", 1, 0.25, "NO_FAULT_FOUND", cases_dir=cases, agent_dir=agent
    )

    assert made == "cand36-redteam"
    case = json.loads((cases / made / "case.json").read_text())
    assert case == {"case_id": made, "clip_id": "cand36", "profile": "car", "red_team": RED_TEAM_NOTE}
    assert (cases / made / "vehicle.can.log").read_text() == "log"
    assert json.loads((agent / f"{made}.json").read_text())["verdict"] == "NO_FAULT_FOUND"
    assert json.loads((agent / "cand36-car-s1775.json").read_text()) == RUN


def test_refuses_to_overwrite_a_case_that_is_not_red_team(tmp_path):
    cases, agent = tmp_path / "cases", tmp_path / "agent"
    for name in ("cand36-car-s1775", "cand36-car-s2775"):
        (cases / name).mkdir(parents=True)
        (cases / name / "case.json").write_text(json.dumps({"case_id": name, "clip_id": "cand36", "profile": "car"}))
    agent.mkdir()
    (agent / "cand36-car-s1775.json").write_text(json.dumps(RUN))
    with pytest.raises(FileExistsError, match="not a red-team case"):
        make_red_team_case(
            "cand36-car-s1775", "cand36-car-s2775", 1, 0.25, "NO_FAULT_FOUND", cases_dir=cases, agent_dir=agent
        )
