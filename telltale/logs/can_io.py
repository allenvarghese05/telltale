"""candump-format CAN log reading and writing, decoded through our DBC definitions."""

from __future__ import annotations

import re
from pathlib import Path

import cantools

from telltale.config import DBC_DIR

LINE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def load_dbc(name: str):
    """Load one of our bundled DBC files by file name."""
    return cantools.database.load_file(str(DBC_DIR / name))


def message_for_signal(db, signal: str):
    """The message that carries `signal`, so callers never hard-code frame ids."""
    for m in db.messages:
        if any(s.name == signal for s in m.signals):
            return m
    raise KeyError(signal)


def write_candump(path, frames) -> None:
    """frames: iterable of (timestamp_s, frame_id, data_bytes, is_extended)."""
    lines = []
    for ts, fid, data, ext in sorted(frames, key=lambda f: f[0]):
        ident = f"{fid:08X}" if ext else f"{fid:03X}"
        lines.append(f"({ts:.6f}) can0 {ident}#{bytes(data).hex().upper()}")
    Path(path).write_text("\n".join(lines) + "\n")


def read_candump(path) -> list[tuple[float, int, bytes]]:
    """Parse a candump log into (timestamp_s, frame_id, data) tuples, skipping unparseable lines."""
    out = []
    for line in Path(path).read_text().splitlines():
        m = LINE.match(line.strip())
        if m:
            out.append((float(m.group(1)), int(m.group(2), 16), bytes.fromhex(m.group(3))))
    return out


def decode_signals(frames, db) -> dict[str, tuple[list[float], list[float]]]:
    """Decode frames into per-signal (times, values) traces. Unknown frame ids are ignored."""
    out: dict[str, tuple[list[float], list[float]]] = {}
    for ts, fid, data in frames:
        try:
            msg = db.get_message_by_frame_id(fid)
        except KeyError:
            continue
        for name, val in msg.decode(data).items():
            t, v = out.setdefault(name, ([], []))
            t.append(ts)
            v.append(float(val))
    return out
