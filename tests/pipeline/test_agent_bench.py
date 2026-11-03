from telltale.pipeline.agent_bench import summarize

ROWS = [
    {
        "expected": "PERCEPTION_LATE",
        "agent": "PERCEPTION_LATE",
        "independent": "PERCEPTION_LATE",
        "status": "VERIFIED",
        "counts": {"VERIFIED": 5, "UNCORROBORATED": 1, "BLOCKED": 0},
    },
    {
        "expected": "BRAKE_ACTUATION_LATE",
        "agent": "PERCEPTION_LATE",
        "independent": "BRAKE_ACTUATION_LATE",
        "status": "REJECTED",
        "counts": {"VERIFIED": 3, "UNCORROBORATED": 0, "BLOCKED": 2},
    },
]


def test_agent_alone_versus_agent_plus_checker():
    s = summarize(ROWS)
    assert s["n"] == 2
    assert s["agent_accuracy"] == 0.5
    assert s["independent_accuracy"] == 1.0
    assert s["agent_wrong"] == 1
    assert s["agent_wrong_flagged"] == 1
    assert s["verified_but_wrong"] == 0


def test_claim_totals():
    s = summarize(ROWS)
    assert s["claims_total"] == 11
    assert s["claims_blocked"] == 2
    assert s["claims_uncorroborated"] == 1


def test_empty_run_does_not_divide_by_zero():
    s = summarize([])
    assert s["n"] == 0
    assert s["agent_accuracy"] == 0.0
