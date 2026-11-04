import json
import re
from pathlib import Path

import pytest

import telltale.web.export as export_module
from telltale.web.export import PERCEPTION_GRID, TAU_GRID, counterfactual_grid, export_site

BUNDLE = {
    "case_id": "nx01-car-s0101",
    "clip_id": "nx01",
    "profile": "car",
    "video_url": "media/nx01.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "lane_polygon": [[0.4, 0.62], [0.6, 0.62], [0.85, 1.0], [0.15, 1.0]],
    "target_boxes": [],
    "events": [],
    "series": {},
    "facts": [],
    "scene": {
        "clip_id": "nx01",
        "tracked_vehicles": 16,
        "hazards": [],
        "target_object_id": "7",
        "target_lane_changes": [],
        "danger_onset_t": 6.0,
        "danger_onset_reason": "entering",
        "first_hazard_t": 5.2,
        "conditions": {"weather": "overcast", "lighting": "daylight", "road_surface": "dry"},
    },
    "verdict": {
        "agent_label": "PERCEPTION_LATE",
        "independent_label": "PERCEPTION_LATE",
        "status": "VERIFIED",
        "reason": "",
        "noncausal_faults": [],
        "excess_s": {},
    },
    "claims": [],
    "counts": {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 0},
    "digest": "abc",
    "agent": {"model": "m", "tool_calls": []},
    "counterfactual_inputs": {
        "v_ego0": 25.0,
        "v_other": 15.0,
        "d0": 30.0,
        "t_end": 5.0,
        "measured": {"perception_s": 2.4, "command_s": 0.05, "tau_s": 0.15},
    },
}


@pytest.fixture
def built(tmp_path):
    bundles, clips, thumbs = tmp_path / "bundles", tmp_path / "clips", tmp_path / "thumbs"
    bundles.mkdir()
    clips.mkdir()
    (thumbs / "nx01-car-s0101").mkdir(parents=True)
    (bundles / "nx01-car-s0101.json").write_text(json.dumps(BUNDLE))
    (clips / "nx01.mp4").write_bytes(b"\x00")
    (thumbs / "nx01-car-s0101" / "hazard_onset_t.jpg").write_bytes(b"\x00")
    return export_site(bundles, tmp_path / "site", clips_dir=clips, thumbs_dir=thumbs)


def test_site_structure(built):
    assert (built / "index.html").exists()
    assert json.loads((built / "cases.json").read_text()) == [
        {"case_id": "nx01-car-s0101", "clip_id": "nx01", "profile": "car"}
    ]
    assert (built / "cases" / "nx01-car-s0101.json").exists()
    assert (built / "media" / "nx01.mp4").exists()
    assert (built / "thumbs" / "nx01-car-s0101" / "hazard_onset_t.jpg").exists()
    assert "does not assign legal fault" in (built / "reports" / "nx01-car-s0101.html").read_text()
    assert "sdk: static" in (built / "README.md").read_text()


def test_avoidance_map_grid(built):
    grid = json.loads((built / "cf" / "nx01-car-s0101.json").read_text())
    assert len(grid["impact_kmh"]) == len(PERCEPTION_GRID)
    assert len(grid["impact_kmh"][0]) == len(TAU_GRID)
    p_late = grid["perception_s"].index(2.4)
    p_nominal = grid["perception_s"].index(0.2)
    tau = grid["tau_s"].index(0.15)
    assert grid["impact_kmh"][p_late][tau] > 0
    assert grid["impact_kmh"][p_nominal][tau] == 0.0


def test_grid_reports_the_measured_and_nominal_operating_points(built):
    grid = json.loads((built / "cf" / "nx01-car-s0101.json").read_text())
    assert grid["measured"] == {"perception_s": 2.4, "command_s": 0.05, "tau_s": 0.15}
    assert grid["nominal"] == {"perception_s": 0.2, "tau_s": 0.15}


def test_grid_states_the_checkers_exact_outcomes_not_the_nearest_cell():
    facts = [
        {"id": "PHYS:actual_impact_speed_mps", "value": 5.2},
        {"id": "PHYS:cf_nominal_contact", "value": False},
    ]
    grid = counterfactual_grid({**BUNDLE, "facts": facts})
    assert grid["outcome_kmh"] == {"measured": 18.7, "nominal": 0.0}


def test_grid_outcome_reports_the_nominal_collision_speed():
    facts = [
        {"id": "PHYS:cf_nominal_contact", "value": True},
        {"id": "PHYS:cf_nominal_impact_speed_mps", "value": 2.5},
    ]
    assert counterfactual_grid({**BUNDLE, "facts": facts})["outcome_kmh"] == {"measured": None, "nominal": 9.0}


def test_exported_case_carries_the_incident_report(built):
    case = json.loads((built / "cases" / "nx01-car-s0101.json").read_text())
    assert case["narrative"][0] == {
        "title": "What the camera saw",
        "sentences": [
            {
                "text": "Automatic tracking followed 16 vehicles in the dashcam footage.",
                "sources": ["scene.tracked_vehicles"],
            }
        ],
    }
    assert case["narrative"][-1]["title"] == "What this report does not say"


def test_printable_report_includes_the_incident_report(built):
    report = (built / "reports" / "nx01-car-s0101.html").read_text()
    assert "<h2>Incident report</h2>" in report
    assert "Automatic tracking followed 16 vehicles in the dashcam footage." in report
    assert report.index("Incident report") < report.index("does not assign legal fault")


def test_unsafe_case_id_is_rejected(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "x.json").write_text(json.dumps({**BUNDLE, "case_id": "../evil"}))
    with pytest.raises(ValueError, match="unsafe case id"):
        export_site(bundles, tmp_path / "site", clips_dir=tmp_path, thumbs_dir=tmp_path)


def test_csp_lets_the_hosted_space_play_its_videos():
    """Hugging Face serves .mp4 files from its CDN (*.hf.co), so `media-src 'self'` alone blocks every video."""
    index = (Path(export_module.__file__).parent / "static" / "index.html").read_text()
    csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', index).group(1)
    media = next(d for d in csp.split(";") if d.strip().startswith("media-src")).split()
    assert media[1:] == ["'self'", "https://*.hf.co"]
