from telltale.logs.mcap_io import read_adas_mcap, write_adas_mcap


def test_mcap_roundtrip(tmp_path):
    p = tmp_path / "a.mcap"
    write_adas_mcap(
        p,
        [
            (
                "/adas/tracks",
                1_700_000_005_350_000_000,
                {"track_id": 7, "event": "first_seen", "range_m": 12.5, "rel_speed_mps": 9.0},
            ),
            ("/ego/speed", 1_700_000_000_000_000_000, {"speed_mps": 25.0}),
        ],
    )
    d = read_adas_mcap(p)
    assert d["/adas/tracks"][0][1]["range_m"] == 12.5
    assert abs(d["/adas/tracks"][0][0] - 1_700_000_005.35) < 1e-6
    assert d["/ego/speed"][0][1]["speed_mps"] == 25.0
