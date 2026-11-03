from telltale.video.bench import summarize

ROWS = [
    {"ok": True, "onset_t": 6.0, "alert_t": 6.2},
    {"ok": True, "onset_t": 5.0, "alert_t": 6.5},
    {"ok": True, "onset_t": None, "alert_t": 6.0},
    {"ok": False, "error": "no target"},
]


def test_summary_metrics():
    s = summarize(ROWS)
    assert s["n_attempted"] == 4
    assert s["n_target_found"] == 3
    assert s["n_onset_found"] == 2
    assert s["median_abs_err_s"] == 0.85
    assert s["within_0_5s"] == 0.5
    assert s["within_1_0s"] == 0.5


def test_spread_and_quartiles_describe_the_error_distribution():
    """A tight spread means we track the same moment as the human, whatever the constant offset."""
    s = summarize(ROWS)
    assert s["median_signed_err_s"] == -0.85
    assert s["stdev_signed_err_s"] == 0.919
    assert s["p25_abs_err_s"] == 0.525
    assert s["p75_abs_err_s"] == 1.175
    assert s["within_2_0s"] == 1.0


def test_coverage_is_scored_against_every_clip_attempted():
    assert summarize(ROWS)["onset_coverage"] == 0.5


def test_signed_error_keeps_its_direction():
    """Our onset is expected to lag the human alert; a sign flip would mean something changed."""
    rows = [{"ok": True, "onset_t": 7.0, "alert_t": 6.0}, {"ok": True, "onset_t": 7.5, "alert_t": 6.5}]
    s = summarize(rows)
    assert s["mean_signed_err_s"] == 1.0
    assert s["stdev_signed_err_s"] == 0.0


def test_a_single_scored_clip_has_no_spread():
    s = summarize([{"ok": True, "onset_t": 7.0, "alert_t": 6.0}])
    assert s["median_abs_err_s"] == 1.0
    assert s["stdev_signed_err_s"] is None


def test_summary_of_nothing_is_not_a_division_by_zero():
    s = summarize([])
    assert s["n_attempted"] == 0
    assert s["median_abs_err_s"] is None
    assert s["within_0_5s"] is None
    assert s["onset_coverage"] is None


def test_clips_without_a_label_are_counted_but_not_scored():
    rows = [{"ok": True, "onset_t": 4.0, "alert_t": None}, {"ok": True, "onset_t": 6.0, "alert_t": 6.2}]
    s = summarize(rows)
    assert s["n_target_found"] == 2
    assert s["n_onset_found"] == 1
    assert s["onset_coverage"] == 0.5
