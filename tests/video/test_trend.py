import numpy as np

from telltale.video.trend import windowed_slope


def test_recovers_a_clean_slope():
    t = np.arange(60) / 30.0
    slope, fitted, ok = windowed_slope(t, 100.0 + 12.0 * t)
    assert ok[30]
    assert slope[30] == np.float64(12.0).round(6) or abs(slope[30] - 12.0) < 1e-6
    assert abs(fitted[30] - (100.0 + 12.0 * t[30])) < 1e-6


def test_pure_noise_is_not_significant():
    rng = np.random.default_rng(3)
    t = np.arange(90) / 30.0
    _, _, ok = windowed_slope(t, 20.0 + rng.normal(0, 9.0, 90))
    assert ok.mean() < 0.05


def test_a_single_outlier_does_not_hide_a_real_slope():
    t = np.arange(60) / 30.0
    values = 100.0 + 12.0 * t
    spiked = values.copy()
    spiked[30] += 500.0
    _, _, ok = windowed_slope(t, spiked)
    assert ok[30]


def test_too_short_a_series_is_never_significant():
    t = np.arange(5) / 30.0
    _, _, ok = windowed_slope(t, np.arange(5, dtype=float))
    assert not ok.any()
