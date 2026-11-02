"""Clip manifests: `data/clips/manifest.json` (demo clips) and the benchmark manifest."""

from __future__ import annotations

import json
from pathlib import Path

from telltale.config import BENCH_CLIPS, CLIPS

MANIFEST = CLIPS / "manifest.json"
BENCH_MANIFEST = BENCH_CLIPS / "bench_manifest.json"
DEFAULT_POLYGON = [[0.40, 0.62], [0.60, 0.62], [0.85, 1.0], [0.15, 1.0]]


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"clips": {}}


def save_manifest(manifest: dict, path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def get_clip(clip_id: str) -> dict:
    return load_manifest()["clips"][clip_id]
