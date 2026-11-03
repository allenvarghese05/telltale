import numpy as np
import pytest

from telltale.evidence.align import align_by_speed, can_offset_from_impact


def _speed(t):
    return np.where(t < 5.0, 25.0, np.maximum(25.0 - 12.0 * (t - 5.0), 0.0))


def test_can_offset_from_impact():
    assert can_offset_from_impact(8.0, 1_700_000_008.37) == pytest.approx(-1_700_000_000.37)


def test_align_by_speed_recovers_skew():
    ref_t = np.arange(0, 10, 0.02)
    true_offset = -0.37
    other_t = np.arange(0, 10, 0.05) - true_offset
    other_v = _speed(other_t + true_offset)
    off = align_by_speed(ref_t, _speed(ref_t), other_t, other_v, guess=0.0)
    assert off == pytest.approx(true_offset, abs=0.01)
