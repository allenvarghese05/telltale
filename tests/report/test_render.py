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
    assert "Detection lagged 1.35 s." in html
    assert "independently verified" in html
    assert "does not assign legal fault" in html
    assert "1 claim blocked" in html
    assert "<b>distracted</b>" not in html
    assert "abc123" in html


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
