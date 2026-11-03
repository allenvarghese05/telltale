from telltale.video.sam import normalize_sam_summary


def test_normalize_groups_by_object_and_sorts_frames():
    summary = [
        {
            "concept": "car",
            "boxes": [
                {"object_id": 3, "frame": 2, "left": 10, "top": 20, "right": 30, "bottom": 40},
                {"object_id": 3, "frame": 1, "left": 11, "top": 21, "right": 31, "bottom": 41},
                {"object_id": 5, "frame": 1, "left": 100, "top": 200, "right": 300, "bottom": 400},
                {"object_id": 9, "frame": None, "left": 0, "top": 0, "right": 1, "bottom": 1},
            ],
        }
    ]
    t = normalize_sam_summary(summary, fps=30.0, width=1000, height=500)
    assert list(t["objects"]) == ["3", "5"]
    assert [d["frame"] for d in t["objects"]["3"]] == [1, 2]
    assert t["objects"]["3"][0]["box"] == [11.0, 21.0, 31.0, 41.0]


def test_fractional_coordinates_are_auto_detected_and_scaled():
    summary = [{"boxes": [{"object_id": 1, "frame": 0, "left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4}]}]
    t = normalize_sam_summary(summary, fps=30.0, width=1000, height=500)
    assert t["objects"]["1"][0]["box"] == [100.0, 100.0, 300.0, 200.0]


def test_accepts_single_object_summary():
    summary = {"boxes": [{"object_id": 1, "frame": 0, "left": 10, "top": 10, "right": 20, "bottom": 20}]}
    assert "1" in normalize_sam_summary(summary, 30.0, 100, 100)["objects"]
