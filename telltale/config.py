"""Paths and model settings. The API key is read from the environment (via .env) and never stored elsewhere."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
CLIPS = DATA / "clips"
BENCH_CLIPS = DATA / "bench_clips"
CASES = DATA / "cases"
GROUND_TRUTH = DATA / "ground_truth"
CACHE = ROOT / "cache"
DBC_DIR = Path(__file__).resolve().parent / "logs" / "dbc"

API_BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
AGENT_MODEL = os.environ.get("TELLTALE_AGENT_MODEL", "muse-wonder-1.0")
WITNESS_MODEL = os.environ.get("TELLTALE_WITNESS_MODEL", "muse-spark-1.3")


def client() -> OpenAI:
    """OpenAI-compatible client for the Meta Model API. Raises if no key is configured."""
    from openai import OpenAI

    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set. Use replay mode or add it to .env")
    return OpenAI(base_url=API_BASE, api_key=key)
