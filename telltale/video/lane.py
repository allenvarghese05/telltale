"""Ego-lane geometry: the lane in pixels, lane overlap, target selection and lane entry."""

from __future__ import annotations

MIN_BOX_FRACTION = 0.02
TARGET_WINDOW_S = 1.0
TARGET_MIN_LANE_OVERLAP = 0.5


def lane_polygon_px(tracks: dict, clip: dict) -> list[tuple[float, float]]:
    """The clip's ego-lane polygon, from fractions of the frame to pixels."""
    return [(x * tracks["width"], y * tracks["height"]) for x, y in clip["ego_lane_polygon"]]


def resolvable(box: list[float], frame_width: int) -> bool:
    """Below ~2% of the frame a box is a handful of pixels, and its growth is jitter rather than approach.

    Measured on cand38: a 10-17 px wide vehicle produced time-to-collision values of 1.5-2.1 s while it was
    in fact shrinking into the distance.
    """
    return (box[2] - box[0]) >= MIN_BOX_FRACTION * frame_width


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


def select_target(tracks: dict, clip: dict, window: int = 5) -> str:
    """The struck vehicle: the largest one near impact that spent the last second mostly in our lane.

    Largest-box-at-impact alone picks whatever is closest to the camera. On cand56 that was a pickup
    overtaking in the next lane (0.17 mean lane overlap over the last second) instead of the car ahead (1.00).
    Requiring the vehicle to have been in our path before impact excludes passers. Boxes too small to
    measure are ignored. If no vehicle qualifies (one crossing our path, or a mis-drawn lane), the largest
    box near impact is used, as before.
    """
    fps, frame_width = tracks["fps"], tracks["width"]
    impact_frame = round(clip["time_of_event"] * fps)
    first_frame = impact_frame - round(TARGET_WINDOW_S * fps)
    poly = lane_polygon_px(tracks, clip)
    largest, in_path = None, None
    for oid, dets in tracks["objects"].items():
        near = [d for d in dets if abs(d["frame"] - impact_frame) <= window]
        if not near:
            continue
        box = min(near, key=lambda d: abs(d["frame"] - impact_frame))["box"]
        area = (box[2] - box[0]) * (box[3] - box[1])
        if largest is None or area > largest[0]:
            largest = (area, oid)
        last_second = [d["box"] for d in dets if first_frame <= d["frame"] <= impact_frame]
        overlap = sum(lane_overlap_fraction(b, poly) for b in last_second) / len(last_second) if last_second else 0.0
        qualifies = overlap >= TARGET_MIN_LANE_OVERLAP and resolvable(box, frame_width)
        if qualifies and (in_path is None or area > in_path[0]):
            in_path = (area, oid)
    if largest is None:
        raise ValueError("no tracked object visible near the impact frame")
    return (in_path or largest)[1]


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
