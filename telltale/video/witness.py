"""Muse Spark as an independent video witness, plus the recheck tool the agent can call.

The witness is asked only what a bystander could see — lane change, turn signal, brake lights, conditions.
It is never asked whether contact occurred: measured against clips with confirmed impacts, Spark reports
proximity rather than contact, so `VID:impact_t` stays with the Nexar human label.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from telltale.config import CACHE, CLIPS, WITNESS_MODEL, client
from telltale.core.manifest import get_clip
from telltale.core.schema import Fact

logger = logging.getLogger(__name__)

PROMPT = """You are an impartial traffic-incident witness reviewing a forward dashcam clip.
Report only what is visible. Use "unclear" when you cannot see it. Times are seconds from the clip start.
Return ONLY a JSON object with exactly these keys:
{"other_vehicle_lane_change_t": number or null,
 "other_vehicle_turn_signal": "yes" | "no" | "unclear",
 "other_vehicle_brake_lights": "yes" | "no" | "unclear",
 "weather": short string, "lighting": short string,
 "road_surface": "dry" | "wet" | "snow" | "unclear"}"""

RECHECK_INSTRUCTION = {
    "enum": "Answer with ONLY one word from: {allowed}.",
    "free": "Answer with ONLY one or two words naming what you see (for example: daylight, night, clear, rain).",
}
UNCERTAIN = re.compile(r"\b(cannot|can't|unclear|unsure|unknown|not visible|hard to|difficult to|no idea)\b")
FILLER = {"the", "it", "is", "a", "an", "in", "of", "scene", "this", "appears", "looks", "clip", "and", "to", "be", "i"}
NUMERIC = {"other_vehicle_lane_change_t"}
ENUMS = {
    "other_vehicle_turn_signal": {"yes", "no", "unclear"},
    "other_vehicle_brake_lights": {"yes", "no", "unclear"},
    "road_surface": {"dry", "wet", "snow", "unclear"},
}
FREE_TEXT = {"weather", "lighting"}
WIT_KEYS = NUMERIC | set(ENUMS) | FREE_TEXT
MAX_TEXT = 40


def parse_witness_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"witness returned no JSON: {text[:200]}")
    return json.loads(match.group(0))


def witness_facts(answers: dict, model: str) -> list[Fact]:
    """Turn the witness's answers into facts, keeping only keys we asked for with values we expect."""
    facts = []
    for key in sorted(WIT_KEYS):
        value = answers.get(key)
        if value is None:
            continue
        if key in NUMERIC:
            try:
                value = float(value)
            except (TypeError, ValueError):
                logger.warning("witness gave a non-numeric %s: %r", key, value)
                continue
            unit = "s"
        else:
            value = str(value).strip().lower()[:MAX_TEXT]
            if key in ENUMS and value not in ENUMS[key]:
                logger.warning("witness gave an out-of-range %s: %r", key, value)
                value = "unclear"
            unit = ""
        facts.append(Fact(f"WIT:{key}", value, unit, "WIT", f"{model} video witness, full clip", "observation"))
    return facts


CUT_IN_PROMPT = """Watch this forward dashcam clip. Does another vehicle move from an adjacent lane into
the camera car's lane, ahead of it, before the collision or near-miss?
A vehicle that was already ahead in the same lane the whole time does not count.
Return ONLY a JSON object with exactly these keys:
{"cut_in": "yes" | "no" | "unclear",
 "time_s": number or null,
 "confidence": "high" | "medium" | "low"}"""
CUT_IN_ANSWERS = {"yes", "no", "unclear"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


def parse_cut_in(text: str) -> dict:
    """Read the screening answer, keeping nothing the model was not asked for."""
    raw = parse_witness_json(text)
    answer = str(raw.get("cut_in", "")).strip().lower()
    confidence = str(raw.get("confidence", "")).strip().lower()
    try:
        when = None if raw.get("time_s") is None else float(raw["time_s"])
    except (TypeError, ValueError):
        logger.warning("cut-in screening gave a non-numeric time_s: %r", raw.get("time_s"))
        when = None
    return {
        "cut_in": answer if answer in CUT_IN_ANSWERS else "unclear",
        "time_s": when,
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "low",
    }


def screen_cut_in(clip_id: str, cache_dir: Path | None = None) -> dict:
    """Ask the witness whether a clip shows a cut-in, caching so a rerun costs nothing.

    This picks candidate *demo* clips for a human to confirm by eye. It never touches the A5 benchmark
    pool, and its answers are never evidence.
    """
    out = (cache_dir or CACHE / "cut_in") / f"{clip_id}.json"
    if out.exists():
        return json.loads(out.read_text())
    clip = get_clip(clip_id)
    answer = parse_cut_in(_ask_video(CLIPS / clip["file"], CUT_IN_PROMPT))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(answer, indent=2))
    return answer


def _ask_video(path: Path, prompt: str) -> str:
    api = client()
    with open(path, "rb") as fh:
        uploaded = api.files.create(file=fh, purpose="user_data")
    response = api.responses.create(
        model=WITNESS_MODEL,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, {"type": "input_file", "file_id": uploaded.id}],
            }
        ],
    )
    return response.output_text


def run_witness_for_clip(clip_id: str) -> dict:
    clip = get_clip(clip_id)
    answers = parse_witness_json(_ask_video(CLIPS / clip["file"], PROMPT))
    out = CACHE / "witness" / f"{clip_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": WITNESS_MODEL, "answers": answers}, indent=2))
    return answers


def recheck_instruction(key: str) -> str:
    """How the second look should answer, so its value is comparable with the matching `WIT:` fact."""
    allowed = ENUMS.get(key)
    if allowed:
        return RECHECK_INSTRUCTION["enum"].format(allowed=", ".join(sorted(allowed)))
    return RECHECK_INSTRUCTION["free"]


def parse_recheck_answer(text: str, key: str) -> str:
    """The observed value, not just yes/no.

    The agent corroborates a witness observation by comparing this against the matching `WIT:` fact, so
    "daylight" has to come back as "daylight". Collapsing every answer to yes/no made that comparison
    impossible and blocked every corroboration attempt.
    """
    lowered = text.lower()
    allowed = ENUMS.get(key)
    if allowed:
        match = re.search(rf"\b({'|'.join(sorted(allowed))})\b", lowered)
        return match.group(1) if match else "unclear"
    if UNCERTAIN.search(lowered):
        return "unclear"
    meaningful = [w for w in re.findall(r"[a-z]+", lowered) if w not in FILLER]
    return " ".join(meaningful[:2])[:MAX_TEXT] if meaningful else "unclear"


def recheck(clip_id: str, question: str, t0: float, t1: float, slug: str) -> Fact:
    """Independent second look at a short window: a fresh upload, no prior context, no earlier answer shown."""
    clip = get_clip(clip_id)
    key = slug if slug in WIT_KEYS else ""
    with tempfile.TemporaryDirectory() as td:
        sub = Path(td) / "sub.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-ss",
                f"{t0:.2f}",
                "-i",
                str(CLIPS / clip["file"]),
                "-t",
                f"{max(0.5, t1 - t0):.2f}",
                "-c:v",
                "libx264",
                "-an",
                str(sub),
            ],
            check=True,
            capture_output=True,
        )
        text = _ask_video(sub, f"{question}\n{recheck_instruction(key)}")
    safe = re.sub(r"[^a-z0-9_]", "_", slug.lower())[:40]
    return Fact(
        f"WIT2:{safe}",
        parse_recheck_answer(text, key),
        "",
        "WIT2",
        f"{WITNESS_MODEL} second look at {t0:.2f}-{t1:.2f}s, asked without the first answer: {question}",
        "observation",
    )
