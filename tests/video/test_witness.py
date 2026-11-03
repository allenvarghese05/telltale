import pytest

from telltale.video.witness import parse_witness_json, witness_facts


def test_parse_strips_code_fences():
    raw = '```json\n{"other_vehicle_turn_signal": "no", "other_vehicle_lane_change_t": 6.1}\n```'
    assert parse_witness_json(raw)["other_vehicle_turn_signal"] == "no"


def test_parse_rejects_text_without_json():
    with pytest.raises(ValueError, match="no JSON"):
        parse_witness_json("I cannot see the video clearly.")


def test_witness_facts_skip_nulls_and_tag_source():
    facts = witness_facts(
        {"other_vehicle_lane_change_t": None, "other_vehicle_turn_signal": "no", "weather": "clear"},
        model="muse-spark-1.3",
    )
    assert {f.id for f in facts} == {"WIT:other_vehicle_turn_signal", "WIT:weather"}
    assert all(f.source == "WIT" and f.kind == "observation" for f in facts)


def test_witness_facts_keep_numeric_times_as_seconds():
    (fact,) = witness_facts({"other_vehicle_lane_change_t": "6.1"}, model="muse-spark-1.3")
    assert fact.value == 6.1
    assert fact.unit == "s"


def test_witness_ignores_keys_it_was_not_asked_for():
    """Model output is untrusted: a key we never asked about must not become evidence."""
    facts = witness_facts({"weather": "clear", "collision": "yes", "verdict": "PERCEPTION_LATE"}, model="m")
    assert {f.id for f in facts} == {"WIT:weather"}
