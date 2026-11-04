import pytest

from telltale.web.titles import crash_title, investigation_title, pick_default


def bundle(
    reason="closing", lighting="daylight", weather="partly cloudy", profile="car", label="PERCEPTION_LATE", **extra
):
    return {
        "profile": profile,
        "scene": {"danger_onset_reason": reason, "conditions": {"lighting": lighting, "weather": weather}},
        "verdict": {"independent_label": label, "status": extra.pop("status", "VERIFIED")},
        **extra,
    }


@pytest.mark.parametrize(
    ("kwargs", "title"),
    [
        ({}, "Rear-end crash on a partly cloudy day"),
        ({"weather": "overcast"}, "Rear-end crash on an overcast day"),
        ({"lighting": "night"}, "Rear-end crash at night"),
        ({"reason": "entering", "lighting": "night"}, "Lane cut-in at night"),
        ({"reason": "predicted", "weather": "unclear"}, "Lane cut-in in daylight"),
        ({"reason": "collision_course"}, "Side or crossing crash on a partly cloudy day"),
        ({"reason": None, "lighting": "unclear"}, "Crash"),
    ],
)
def test_crash_title_is_plain_and_built_from_the_scene(kwargs, title):
    assert crash_title(bundle(**kwargs)) == title


@pytest.mark.parametrize(
    ("kwargs", "title"),
    [
        ({}, "Car: noticed the hazard too late"),
        ({"label": "COMMAND_LATE"}, "Car: noticed in time, braked too late"),
        ({"label": "BRAKE_ACTUATION_LATE", "profile": "truck"}, "Loaded truck: brakes slow to engage"),
        ({"label": "LATE_HANDOFF", "profile": "truck"}, "Loaded truck: handed back to the driver too late"),
        ({"label": "UNAVOIDABLE"}, "Car: unavoidable, even with a perfect response"),
        ({"status": "REJECTED"}, "Car: the AI and the checker disagree"),
        ({"status": "REJECTED", "red_team": "altered"}, "Someone edits the AI's answer: the checker catches it"),
    ],
)
def test_investigation_title_names_the_vehicle_and_what_the_checker_found(kwargs, title):
    assert investigation_title(bundle(**kwargs)) == title


def test_default_is_the_first_crash_car_case_noticed_too_late():
    entries = [
        {"case_id": "b-truck", "clip_id": "b", "profile": "truck", "label": "PERCEPTION_LATE", "red_team": False},
        {"case_id": "a-red", "clip_id": "a", "profile": "car", "label": "PERCEPTION_LATE", "red_team": True},
        {"case_id": "a-late", "clip_id": "a", "profile": "car", "label": "COMMAND_LATE", "red_team": False},
        {"case_id": "a-noticed", "clip_id": "a", "profile": "car", "label": "PERCEPTION_LATE", "red_team": False},
    ]
    assert pick_default(entries) == "a-noticed"


def test_default_falls_back_to_the_first_case():
    assert (
        pick_default([{"case_id": "x", "clip_id": "x", "profile": "truck", "label": "UNAVOIDABLE", "red_team": False}])
        == "x"
    )
