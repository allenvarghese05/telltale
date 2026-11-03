from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.lane import _lane_edges, _x_at, lane_overlap_fraction

POLY_PX = [(x * 1280, y * 720) for x, y in DEFAULT_POLYGON]
BOTTOM = 650.0


def _box_spanning(u_left, u_right):
    left, right = _lane_edges(POLY_PX)
    x_left, x_right = _x_at(left, BOTTOM), _x_at(right, BOTTOM)
    width = x_right - x_left
    return [x_left + u_left * width, BOTTOM - 80, x_left + u_right * width, BOTTOM]


def test_a_centred_vehicle_is_fully_in_lane():
    assert lane_overlap_fraction(_box_spanning(0.3, 0.7), POLY_PX) == 1.0


def test_a_vehicle_in_the_next_lane_has_no_overlap():
    assert lane_overlap_fraction(_box_spanning(1.2, 1.6), POLY_PX) == 0.0


def test_a_vehicle_straddling_the_edge_is_partial():
    fraction = lane_overlap_fraction(_box_spanning(0.8, 1.2), POLY_PX)
    assert 0.4 < fraction < 0.6


def test_a_grazing_vehicle_barely_counts():
    """The failure this exists for: a car passing on the left whose bottom-centre grazed u=0."""
    assert lane_overlap_fraction(_box_spanning(-0.45, 0.05), POLY_PX) < 0.2
