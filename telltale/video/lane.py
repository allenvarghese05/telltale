"""Ego-lane geometry: point-in-polygon, target selection, and lane entry."""

from __future__ import annotations


def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


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
    flags = [point_in_polygon((d["box"][0] + d["box"][2]) / 2, d["box"][3], poly_px) for d in dets]
    if not flags or flags[0]:
        return None
    for i in range(1, len(dets) - hold + 1):
        if not flags[i - 1] and all(flags[i : i + hold]):
            return dets[i]["frame"]
    return None
