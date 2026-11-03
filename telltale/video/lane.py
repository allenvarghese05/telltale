"""Ego-lane geometry: point-in-polygon, target selection, and lane entry."""

from __future__ import annotations


def _lane_edges(poly: list[tuple[float, float]]) -> tuple[tuple, tuple]:
    """The lane's left and right boundary lines, taken from the trapezoid's two side edges."""
    if len(poly) != 4:
        raise ValueError(f"ego lane polygon must have 4 points, got {len(poly)}")
    by_depth = sorted(poly, key=lambda p: p[1])
    far = sorted(by_depth[:2], key=lambda p: p[0])
    near = sorted(by_depth[2:], key=lambda p: p[0])
    return (far[0], near[0]), (far[1], near[1])


def _x_at(edge: tuple[tuple[float, float], tuple[float, float]], y: float) -> float:
    (x1, y1), (x2, y2) = edge
    return x1 if y2 == y1 else x1 + (y - y1) * (x2 - x1) / (y2 - y1)


def in_lane_laterally(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Is this point between the lane's edges at its own depth?

    The boundary lines are extrapolated beyond the polygon, because the trapezoid's top edge marks how far
    the lane was drawn, not where the lane ends. Testing containment in the polygon itself would make a
    vehicle "enter the lane" simply by driving closer, which is what it did on every real clip.
    """
    left, right = _lane_edges(poly)
    x_left, x_right = _x_at(left, y), _x_at(right, y)
    return x_left <= x <= x_right if x_left < x_right else False


def lane_overlap_fraction(box: list[float], poly: list[tuple[float, float]]) -> float:
    """How much of the vehicle's width sits inside the ego lane, at its own depth.

    A single bottom-centre point cannot tell a vehicle in our path from one passing alongside whose point
    grazes the lane edge — which on cand38 made an overtaking car the earliest "hazard" at t=0.
    """
    left, right = _lane_edges(poly)
    bottom = box[3]
    x_left, x_right = _x_at(left, bottom), _x_at(right, bottom)
    width = box[2] - box[0]
    if width <= 0 or x_right <= x_left:
        return 0.0
    inside = min(box[2], x_right) - max(box[0], x_left)
    return max(0.0, min(inside / width, 1.0))


def select_target(objects: dict[str, list[dict]], impact_frame: int, window: int = 5) -> str:
    """The struck vehicle is the one filling the most of the frame at impact."""
    best = None
    for oid, dets in objects.items():
        near = [d for d in dets if abs(d["frame"] - impact_frame) <= window]
        if not near:
            continue
        left, top, right, bottom = min(near, key=lambda d: abs(d["frame"] - impact_frame))["box"]
        area = (right - left) * (bottom - top)
        if best is None or area > best[0]:
            best = (area, oid)
    if best is None:
        raise ValueError("no tracked object visible near the impact frame")
    return best[1]


def lane_entry_frame(dets: list[dict], poly_px: list[tuple[float, float]], hold: int = 3) -> int | None:
    """First frame whose box bottom-centre crosses into the ego lane and stays for `hold` frames.

    A target already inside the lane on the first frame never entered it: that is a lead vehicle, not a
    cut-in, and returning frame 0 would report a lane entry that never happened. Such clips get `None`
    here and fall back to the time-to-collision branch of the danger onset.
    """
    flags = [in_lane_laterally((d["box"][0] + d["box"][2]) / 2, d["box"][3], poly_px) for d in dets]
    if not flags or flags[0]:
        return None
    for i in range(1, len(dets) - hold + 1):
        if not flags[i - 1] and all(flags[i : i + hold]):
            return dets[i]["frame"]
    return None
