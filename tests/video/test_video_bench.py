from telltale.video.bench import summarize


def test_summary_metrics():
    rows = [
        {"ok": True, "onset_t": 6.0, "alert_t": 6.2},
        {"ok": True, "onset_t": 5.0, "alert_t": 6.5},
        {"ok": True, "onset_t": None, "alert_t": 6.0},
        {"ok": False, "error": "no target"},
    ]
    s = summarize(rows)
    assert s["n_attempted"] == 4
    assert s["n_target_found"] == 3
    assert s["n_onset_found"] == 2
    assert s["median_abs_err_s"] == 0.85
    assert s["within_0_5s"] == 0.5
    assert s["within_1_0s"] == 0.5


def test_signed_error_keeps_its_direction():
    """Our onset is expected to lag the human alert; a sign flip would mean something changed."""
    rows = [{"ok": True, "onset_t": 7.0, "alert_t": 6.0}, {"ok": True, "onset_t": 7.5, "alert_t": 6.5}]
    assert summarize(rows)["mean_signed_err_s"] == 1.0


def test_summary_of_nothing_is_not_a_division_by_zero():
    s = summarize([])
    assert s["n_attempted"] == 0
    assert s["median_abs_err_s"] is None
    assert s["within_0_5s"] is None


def test_clips_without_a_label_are_counted_but_not_scored():
    rows = [{"ok": True, "onset_t": 4.0, "alert_t": None}, {"ok": True, "onset_t": 6.0, "alert_t": 6.2}]
    s = summarize(rows)
    assert s["n_target_found"] == 2
    assert s["n_onset_found"] == 1
