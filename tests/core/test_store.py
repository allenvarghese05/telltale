import pytest

from telltale.core.schema import Fact
from telltale.evidence.store import EvidenceStore


def _facts() -> list[Fact]:
    return [
        Fact("VID:lane_entry_t", 4.0, "s", "VID", "SAM mask entered ego lane"),
        Fact("AV:first_seen_t", 5.35, "s", "AV", "first /adas/tracks message"),
        Fact("ATTR:label", "PERCEPTION_LATE", "", "ATTR", "attribution", "derived"),
    ]


SERIES = {"can.speed_mps": {"t": [0, 1], "v": [20, 19], "unit": "m/s", "source": "CAN"}}


def test_get_has_and_series_window():
    store = EvidenceStore(_facts(), SERIES)
    assert store.has("VID:lane_entry_t")
    assert store.get("AV:first_seen_t").value == 5.35
    assert store.series("can.speed_mps", 0.5, 2)["v"] == [19.0]
    assert store.series_names() == ["can.speed_mps"]


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="duplicate fact id VID:lane_entry_t"):
        EvidenceStore([*_facts(), _facts()[0]])


def test_json_roundtrip_and_tamper_detection():
    data = EvidenceStore(_facts(), SERIES).to_json()
    assert EvidenceStore.from_json(data).verify_integrity()
    data["facts"][0]["value"] = 9.9
    with pytest.raises(ValueError, match="digest mismatch"):
        EvidenceStore.from_json(data)


def test_only_tool_generated_facts_can_be_appended():
    store = EvidenceStore(_facts())
    child = store.extended(
        [
            Fact("WIT2:turn_signal", "no", "", "WIT2", "recheck", "observation"),
            Fact("CF:run1_contact", False, "", "CF", "counterfactual", "derived"),
        ]
    )
    assert child.has("CF:run1_contact")
    assert child.parent_digest == store.digest
    assert child.digest != store.digest
    with pytest.raises(PermissionError, match="PHYS:perception_latency_s"):
        store.extended([Fact("PHYS:perception_latency_s", 0.1, "s", "PHYS", "forged")])


def test_agent_view_hides_checker_facts():
    ids = {f.id for f in EvidenceStore(_facts()).agent_facts()}
    assert ids == {"VID:lane_entry_t", "AV:first_seen_t"}
