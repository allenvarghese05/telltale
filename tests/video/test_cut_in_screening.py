import json

import pytest

import telltale.video.witness as wit
from telltale.video.witness import parse_cut_in, screen_cut_in


def test_parse_strips_fences_and_keeps_a_clean_answer():
    raw = '```json\n{"cut_in": "yes", "time_s": 5.5, "confidence": "high"}\n```'
    assert parse_cut_in(raw) == {"cut_in": "yes", "time_s": 5.5, "confidence": "high"}


def test_out_of_range_values_fall_back_rather_than_being_trusted():
    """Model output is untrusted: an unexpected enum must not become a confident answer."""
    parsed = parse_cut_in('{"cut_in": "probably", "time_s": 4, "confidence": "very sure"}')
    assert parsed["cut_in"] == "unclear"
    assert parsed["confidence"] == "low"


def test_an_unparseable_time_becomes_none():
    assert parse_cut_in('{"cut_in": "yes", "time_s": "about five", "confidence": "low"}')["time_s"] is None


def test_a_missing_answer_is_unclear():
    assert parse_cut_in('{"time_s": null}')["cut_in"] == "unclear"


def test_text_without_json_is_rejected():
    with pytest.raises(ValueError, match="no JSON"):
        parse_cut_in("I cannot tell from this video.")


def test_a_cached_answer_is_never_asked_again(tmp_path, monkeypatch):
    """Screening 64 clips must cost once; a rerun must not spend another API call."""
    (tmp_path / "nx99.json").write_text(json.dumps({"cut_in": "no", "time_s": None, "confidence": "high"}))

    def _fail(*_args, **_kwargs):
        raise AssertionError("the model was asked again despite a cached answer")

    monkeypatch.setattr(wit, "_ask_video", _fail)
    assert screen_cut_in("nx99", cache_dir=tmp_path)["cut_in"] == "no"
