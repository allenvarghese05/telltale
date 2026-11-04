"""Ego-lane geometry: the lane in pixels, lane overlap, target selection and lane entry."""

from __future__ import annotations

from telltale.video.ttc import ttc_series

MIN_BOX_FRACTION = 0.02
TARGET_WINDOW_S = 1.0
TARGET_MIN_LANE_OVERLAP = 0.5
COURSE_TTC_S = 2.0
COURSE_HOLD_FRAMES = 9


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


def mean_lane_overlap(dets: list[dict], poly_px: list[tuple[float, float]], first_frame: int, last_frame: int) -> float:
    """The average share of the vehicle's width inside the ego lane over a span of frames; 0 if it was not seen."""
    boxes = [d["box"] for d in dets if first_frame <= d["frame"] <= last_frame]
    return sum(lane_overlap_fraction(b, poly_px) for b in boxes) / len(boxes) if boxes else 0.0


def collision_course_frame(
    dets: list[dict], fps: float, poly_px: list[tuple[float, float]], frame_width: int, from_frame: int | None = None
) -> int | None:
    """First frame from which a vehicle is closing on the ego car fast while touching the ego lane's extent.

    Unlike the lane tests, this does not ask where the vehicle is in the lane, so it catches a car turning across
    our path or striking our side. "Closing fast" is a time to collision under 2 s from the growth of the box's
    height, held for 9 frames, the same threshold and hold the in-lane `closing` test uses. Height rather than
    width, because an edge-clipped or turning vehicle's width stops tracking its distance. Touching the lane
    (any overlap) keeps out oncoming traffic that grows as it approaches in its own lane, and a vehicle passing
    alongside is excluded by its height staying flat. With `from_frame`, only runs from that frame on count, while
    the time to collision is still estimated over the whole track.
    """
    if len(dets) < COURSE_HOLD_FRAMES:
        return None
    frames, ttc = ttc_series(dets, fps, dimension="height")
    run = 0
    for i, d in enumerate(dets):
        on = (
            (from_frame is None or d["frame"] >= from_frame)
            and ttc[i] < COURSE_TTC_S
            and resolvable(d["box"], frame_width)
            and lane_overlap_fraction(d["box"], poly_px) > 0.0
        )
        run = run + 1 if on else 0
        if run >= COURSE_HOLD_FRAMES:
            return int(frames[i - COURSE_HOLD_FRAMES + 1])
    return None


def select_target(tracks: dict, clip: dict, window: int = 5) -> str:
    """The struck vehicle: the largest one near impact that was in our path or on a collision course with us.

    Largest-box-at-impact alone picks whatever is closest to the camera: on cand56 a pickup overtaking in the next
    lane, instead of the car ahead. Requiring the last second mostly in our lane fixed that but assumed a forward
    conflict, and missed a taxi striking our side (cand14) and an oncoming car turning across our path (cand60),
    each picked as some small car ahead instead. So a vehicle also qualifies if it was on a collision course at
    any point in the 2 s before impact. If none qualifies, the largest box near impact is used.

    Ranking qualifiers by shortest time to collision was tried and rejected: distant boxes a few pixels wide give
    noisy short TTCs and would replace the true struck vehicle on two of the four demo clips.
    """
    fps, frame_width = tracks["fps"], tracks["width"]
    impact_frame = round(clip["time_of_event"] * fps)
    first_frame = impact_frame - round(TARGET_WINDOW_S * fps)
    course_from = impact_frame - round(COURSE_TTC_S * fps)
    poly = lane_polygon_px(tracks, clip)
    largest, qualified = None, None
    for oid, raw in tracks["objects"].items():
        dets = sorted(raw, key=lambda d: d["frame"])
        near = [d for d in dets if abs(d["frame"] - impact_frame) <= window]
        if not near:
            continue
        box = min(near, key=lambda d: abs(d["frame"] - impact_frame))["box"]
        area = (box[2] - box[0]) * (box[3] - box[1])
        if largest is None or area > largest[0]:
            largest = (area, oid)
        if not resolvable(box, frame_width):
            continue
        overlap = mean_lane_overlap(dets, poly, first_frame, impact_frame)
        before = [d for d in dets if d["frame"] <= impact_frame]
        on_course = collision_course_frame(before, fps, poly, frame_width, from_frame=course_from) is not None
        if (overlap >= TARGET_MIN_LANE_OVERLAP or on_course) and (qualified is None or area > qualified[0]):
            qualified = (area, oid)
    if largest is None:
        raise ValueError("no tracked object visible near the impact frame")
    return (qualified or largest)[1]


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
