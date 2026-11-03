import re

from telltale.web.narrative import incident_report

FACTS = {
    "VID:hazard_onset_t": 4.2,
    "VID:hazard_onset_reason": "entering",
    "AV:first_seen_t": 5.55,
    "AV:brake_request_t": 5.62,
    "CAN:pressure_reached_t": 5.84,
    "VID:impact_t": 7.1,
    "WIT:lighting": "daylight",
    "WIT:weather": "overcast",
    "WIT:road_surface": "dry",
    "PHYS:perception_latency_s": 1.35,
    "PROFILE:perception_threshold_s": 0.3,
    "PHYS:command_latency_s": 0.07,
    "PROFILE:command_threshold_s": 0.1,
    "PHYS:actuation_latency_s": 0.18,
    "PROFILE:actuation_threshold_s": 0.25,
    "ATTR:excess_perception_s": 1.05,
    "ATTR:excess_command_s": -0.03,
    "ATTR:excess_actuation_s": -0.07,
    "PHYS:actual_impact_speed_mps": 3.5556,
    "PHYS:cf_nominal_contact": False,
    "PHYS:cf_nominal_min_gap_m": 2.1,
    "DATA:brake_log_complete": True,
    "ATTR:label": "PERCEPTION_LATE",
}


def bundle(facts=None, **overrides):
    base = {
        "facts": [{"id": k, "value": v} for k, v in (FACTS if facts is None else facts).items()],
        "scene": {
            "tracked_vehicles": 16,
            "target_lane_changes": [{"start_t": 3.1, "end_t": 3.9, "direction": "left"}],
        },
        "verdict": {
            "agent_label": "PERCEPTION_LATE",
            "independent_label": "PERCEPTION_LATE",
            "status": "VERIFIED",
        },
        "counts": {"VERIFIED": 3, "UNCORROBORATED": 1, "BLOCKED": 1},
    }
    return {**base, **overrides}


def texts(report):
    return {s.title: [line.text for line in s.sentences] for s in report}


def test_full_report_reads_in_order():
    assert texts(incident_report(bundle())) == {
        "What the camera saw": [
            "Automatic tracking followed 16 vehicles in the dashcam footage.",
            "At 4.20 seconds, the other vehicle became a hazard: it moved into the camera car's lane.",
            "Between 3.10 and 3.90 seconds, it changed lanes to the left.",
            "A second model watching the same footage described the conditions as daylight, overcast and a dry road.",
        ],
        "What the vehicle's systems did": [
            "At 5.55 seconds, the driver-assist system first noticed the vehicle.",
            "At 5.62 seconds, it commanded the brakes.",
            "At 5.84 seconds, the brakes engaged.",
            "The collision happened at 7.10 seconds.",
        ],
        "Where the chain broke": [
            "The system took 1.35 seconds to notice the vehicle.",
            "A system performing to specification would notice within 0.30 seconds.",
            "It then took 0.07 seconds to command the brakes.",
            "The specification allows 0.10 seconds.",
            "The brakes took 0.18 seconds to engage once commanded.",
            "The specification allows 0.25 seconds.",
            "The largest overrun was in noticing the vehicle: 1.05 seconds past its limit.",
        ],
        "Would normal timing have avoided it?": [
            "As it happened, the vehicles collided at a closing speed of 12.8 km/h.",
            "Replayed with every step performing to specification, the collision is avoided.",
            "The vehicles come no closer than 2.10 metres.",
        ],
        "How this was verified": [
            "The AI investigator concluded that the system noticed the hazard too late.",
            "Separate code, with no AI involved, recomputed the conclusion from the same evidence and agreed.",
            "Of the investigator's 5 claims, 3 were confirmed by recomputation, 1 rests on a single source "
            "and 1 was blocked.",
        ],
        "What this report does not say": [
            "This report identifies which step in the vehicle's response fell outside its specification.",
            "It does not decide who is legally responsible for the collision.",
            "A qualified human reviewer signs off before it is relied on.",
        ],
    }


def test_sections_come_in_the_reading_order():
    assert [s.title for s in incident_report(bundle())] == [
        "What the camera saw",
        "What the vehicle's systems did",
        "Where the chain broke",
        "Would normal timing have avoided it?",
        "How this was verified",
        "What this report does not say",
    ]


def test_every_sentence_names_the_evidence_it_came_from():
    lines = {line.text: line.sources for s in incident_report(bundle()) for line in s.sentences}
    assert lines["The system took 1.35 seconds to notice the vehicle."] == ("PHYS:perception_latency_s",)
    assert lines["At 4.20 seconds, the other vehicle became a hazard: it moved into the camera car's lane."] == (
        "VID:hazard_onset_t",
        "VID:hazard_onset_reason",
    )
    assert lines["Automatic tracking followed 16 vehicles in the dashcam footage."] == ("scene.tracked_vehicles",)
    assert lines["As it happened, the vehicles collided at a closing speed of 12.8 km/h."] == (
        "PHYS:actual_impact_speed_mps",
    )


def test_rejected_verdict_shows_both_conclusions_and_is_withheld():
    rejected = bundle(
        facts={**FACTS, "ATTR:label": "UNAVOIDABLE"},
        verdict={"agent_label": "PERCEPTION_LATE", "independent_label": "UNAVOIDABLE", "status": "REJECTED"},
    )
    assert texts(incident_report(rejected))["How this was verified"][:3] == [
        "The AI investigator concluded that the system noticed the hazard too late.",
        "Separate code, with no AI involved, recomputed the conclusion from the same evidence and found instead "
        "that the collision could not have been avoided even with normal timing.",
        "Because the two disagree, this conclusion is withheld until a human reviewer decides.",
    ]


def test_incomplete_brake_log_says_what_is_missing():
    gappy = bundle(facts={**FACTS, "DATA:brake_log_complete": False, "DATA:max_brake_gap_s": 0.42})
    assert texts(incident_report(gappy))["Where the chain broke"][0] == (
        "The brake log is incomplete: it is missing 0.42 seconds of data while braking was being decided, "
        "so brake timing cannot be measured reliably."
    )


def test_unavoidable_collision_reports_the_reduced_speed():
    hit = bundle(facts={**FACTS, "PHYS:cf_nominal_contact": True, "PHYS:cf_nominal_impact_speed_mps": 2.5})
    assert texts(incident_report(hit))["Would normal timing have avoided it?"][1] == (
        "Replayed with every step performing to specification, the collision still happens, "
        "at a closing speed of 9.0 km/h."
    )


def test_handoff_replaces_the_brake_command():
    facts = {k: v for k, v in FACTS.items() if k != "AV:brake_request_t"}
    facts |= {"AV:handoff_t": 5.9, "PHYS:handoff_margin_s": 1.2, "PROFILE:human_prt_s": 1.5}
    report = texts(incident_report(bundle(facts=facts)))
    assert "At 5.90 seconds, the system handed control back to the driver." in report["What the vehicle's systems did"]
    assert report["Where the chain broke"][-3:-1] == [
        "The driver then had 1.20 seconds before the collision.",
        "A person typically needs 1.50 seconds to react.",
    ]


def test_missing_fields_are_omitted_never_invented():
    sparse = bundle(facts={"VID:impact_t": 7.1}, scene={}, counts={})
    report = texts(incident_report(sparse))
    assert report["What the vehicle's systems did"] == ["The collision happened at 7.10 seconds."]
    assert "What the camera saw" not in report
    assert "Where the chain broke" not in report
    assert "Would normal timing have avoided it?" not in report


def test_singular_counts_read_naturally():
    one = bundle(counts={"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 0})
    assert texts(incident_report(one))["How this was verified"][-1] == (
        "Of the investigator's 1 claim, 1 was confirmed by recomputation, 0 rest on a single source and 0 were blocked."
    )


def test_no_words_the_checker_would_block():
    banned = re.compile(r"\b(fault|blame|liab\w*|negligen\w*|reckless\w*|culpab\w*|guilty)\b", re.I)
    variants = [
        bundle(),
        bundle(
            facts={**FACTS, "ATTR:label": "UNAVOIDABLE", "PHYS:cf_nominal_contact": True},
            verdict={"agent_label": "PERCEPTION_LATE", "independent_label": "UNAVOIDABLE", "status": "REJECTED"},
        ),
    ]
    for b in variants:
        for section in incident_report(b):
            for line in section.sentences:
                assert not banned.search(line.text), line.text
