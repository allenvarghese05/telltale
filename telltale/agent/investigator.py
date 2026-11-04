"""The investigator: a Muse Wonder agent that reads the evidence with tools and decides the primary cause.

The model is injected, so tests never touch the network. Every number the agent uses comes from a tool here,
never from its own arithmetic. `PHYS:*` and `ATTR:*` facts stay hidden: the agent must reach its own verdict
before the checker compares it with the independent recomputation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict

from telltale.core.schema import HIDDEN_FROM_AGENT, LABELS, Fact
from telltale.evidence.store import EvidenceStore

SYSTEM = """You are Telltale's lead forensic investigator for vehicle collisions. You determine the primary
contributing factor from evidence. You never assign legal fault.

METHOD
1. list_evidence. Build the timeline: VID:hazard_onset_t (the struck vehicle became a hazard; VID:hazard_onset_reason
   says how: entering our lane, predicted to enter, or closing within it), AV:first_seen_t (system detects),
   AV:brake_request_t or AV:handoff_t (decision), CAN:brake_request_t and CAN:pressure_reached_t (brakes engage),
   VID:impact_t.
2. Use measure for every interval. Never compute numbers yourself.
   perception = AV:first_seen_t - VID:hazard_onset_t;  command = AV:brake_request_t - AV:first_seen_t
   actuation = CAN:pressure_reached_t - CAN:brake_request_t;  handoff margin = VID:impact_t - AV:handoff_t
   A measure result is NOT a fact: no evidence id holds it. To state an interval in a claim you must use a
   "diff" assertion over the two endpoints, which is what licenses that number. See CLAIM FORMAT.
3. Compare each with its PROFILE threshold (perception/command/actuation threshold, human_prt for handoff margin).
4. But-for test: call run_counterfactual with PROFILE nominal values (nominal_perception_s, nominal_command_s,
   nominal_tau_s). If contact is still true, the verdict is UNAVOIDABLE. If it's avoided, the primary factor is the
   layer whose measured value exceeds its threshold by the most. If the counterfactual avoids the crash and nothing
   exceeds a threshold, the verdict is NO_FAULT_FOUND.
5. If DATA:brake_log_complete is false, the verdict is INCONCLUSIVE.
6. Witness facts (WIT:*) are single-source. For important visual observations, call witness_recheck on a short window
   and cite both facts with a 'same' or 'agree' assertion.
7. submit_findings with verdict (one of: PERCEPTION_LATE, COMMAND_LATE, BRAKE_ACTUATION_LATE, LATE_HANDOFF,
   UNAVOIDABLE, NO_FAULT_FOUND, INCONCLUSIVE) and 5-10 claims.

CLAIM FORMAT: each claim cites existing evidence ids and includes an assertion the checker can recompute:
  {"op":"diff","a":ID,"b":ID,"equals":n} | {"op":"value","fact":ID,"equals":n}
  {"op":"gt"|"lt","fact":ID,"than_fact":ID} | {"op":"agree","a":ID,"b":ID,"within":n}
  {"op":"same","a":ID,"b":ID} | {"op":"is","fact":ID,"equals":value}
Every number in claim text must come from the cited facts (you may convert s->ms, m/s->km/h or
mph; round to 2 decimals). A number is licensed two ways only: it is the value of a cited numeric fact, or
your assertion derives it (a "diff" licenses a-b). Cite every fact whose value you name, including thresholds
and nominal values.
Example, an interval against its threshold - cite BOTH endpoints AND the threshold:
 {"text":"The system took 1.35 s to notice the vehicle, above the 0.30 s it is allowed.","type":"timing",
  "evidence":["AV:first_seen_t","VID:hazard_onset_t","PROFILE:perception_threshold_s"],
  "assertion":{"op":"diff","a":"AV:first_seen_t","b":"VID:hazard_onset_t","equals":1.35}}
Quoting a counterfactual's inputs: cite PROFILE:nominal_perception_s, PROFILE:nominal_command_s and
PROFILE:nominal_tau_s alongside the CF: facts, or those numbers are unlicensed.
Corroborating a witness observation: witness_recheck returns the value it saw, not yes/no, so pass the
WIT: fact's own name as `slug` and compare with {"op":"same","a":"WIT:<key>","b":"WIT2:<key>"}.
An independent deterministic checker verifies every claim and your verdict. Unsupported, legal or driver-state claims
are blocked."""


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


NUM = {"type": "number"}
TOOLS = [
    _fn("list_evidence", "List visible evidence facts (id, value, unit, source, derivation).", {}, []),
    _fn(
        "get_series",
        "Time series in video seconds, at most 200 points.",
        {"name": {"type": "string"}, "t0": NUM, "t1": NUM},
        ["name"],
    ),
    _fn(
        "measure",
        "Exact a minus b for two numeric fact ids.",
        {"a": {"type": "string"}, "b": {"type": "string"}},
        ["a", "b"],
    ),
    _fn(
        "run_counterfactual",
        "Replay the crash physics with given timings. Creates citable CF:run<k>_* facts.",
        {"perception_s": NUM, "command_s": NUM, "tau_s": NUM},
        ["perception_s", "command_s", "tau_s"],
    ),
    _fn(
        "witness_recheck",
        "Independent vision model answers a yes/no question about a short video window. Creates a WIT2 fact.",
        {"question": {"type": "string"}, "t0": NUM, "t1": NUM, "slug": {"type": "string"}},
        ["question", "t0", "t1", "slug"],
    ),
    _fn(
        "submit_findings",
        "Submit the verdict and structured claims.",
        {
            "verdict": {"type": "string", "enum": list(LABELS)},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["timing", "physics", "observation", "attribution", "other"],
                        },
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "assertion": {"type": "object"},
                    },
                    "required": ["text", "type", "evidence"],
                },
            },
        },
        ["verdict", "claims"],
    ),
]


def _downsample(series: dict, n: int = 200) -> dict:
    step = -(-len(series["t"]) // n) or 1
    return {**series, "t": series["t"][::step], "v": series["v"][::step]}


def _assistant_dict(msg) -> dict:
    """Turn an SDK assistant message back into a plain dict we can append to the transcript."""
    message = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        message["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
            }
            for c in msg.tool_calls
        ]
    return message


def investigate(
    store: EvidenceStore,
    llm,
    counterfactual_fn: Callable[[float, float, float], dict] | None = None,
    recheck_fn: Callable[..., Fact] | None = None,
    model: str = "muse-wonder-1.0",
    max_turns: int = 16,
) -> dict:
    """Run the tool loop until the agent submits a valid verdict, and return its findings plus the facts it created."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Investigate this case. Evidence store digest: {store.digest}."},
    ]
    tool_calls: list[dict] = []
    agent_facts: list[Fact] = []
    cf_runs = 0
    rechecked: dict[str, str] = {}  # recheck slug -> the WIT2 fact id it produced

    def visible_num(fact_id: str) -> float:
        if fact_id.startswith(HIDDEN_FROM_AGENT) or not store.has(fact_id):
            raise KeyError(f"{fact_id} is not available")
        value = store.get(fact_id).value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{fact_id} is not numeric")
        return float(value)

    for _ in range(max_turns):
        msg = llm.chat.completions.create(model=model, messages=messages, tools=TOOLS).choices[0].message
        messages.append(_assistant_dict(msg))
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Call submit_findings with your verdict and claims now."})
            continue
        for c in msg.tool_calls:
            name, args = c.function.name, json.loads(c.function.arguments or "{}")
            tool_calls.append(
                {
                    "name": name,
                    "args": args
                    if name != "submit_findings"
                    else {"verdict": args.get("verdict"), "n_claims": len(args.get("claims", []))},
                }
            )
            if name == "submit_findings":
                if args.get("verdict") in LABELS:
                    return {
                        "model": model,
                        "digest": store.digest,
                        "verdict": args["verdict"],
                        "claims": args.get("claims", []),
                        "tool_calls": tool_calls,
                        "agent_facts": [asdict(f) for f in agent_facts],
                    }
                out = {"error": f"verdict must be one of {list(LABELS)}"}
            elif name == "list_evidence":
                out = [asdict(f) for f in store.agent_facts()]
            elif name == "get_series":
                try:
                    out = _downsample(store.series(args["name"], args.get("t0"), args.get("t1")))
                except KeyError:
                    out = {"error": f"unknown series; available: {store.series_names()}"}
            elif name == "measure":
                try:
                    a, b = visible_num(args["a"]), visible_num(args["b"])
                    out = {"a": args["a"], "b": args["b"], "a_minus_b": round(a - b, 4)}
                except (KeyError, TypeError) as exc:
                    out = {"error": str(exc)}
            elif name == "run_counterfactual" and counterfactual_fn is not None:
                cf_runs += 1
                perception, command, tau = (
                    float(args["perception_s"]),
                    float(args["command_s"]),
                    float(args["tau_s"]),
                )
                result = counterfactual_fn(perception, command, tau)
                how = f"simulate(perception={perception}, command={command}, tau={tau})"
                new = [
                    Fact(f"CF:run{cf_runs}_contact", bool(result["contact"]), "", "CF", how, "derived"),
                    Fact(
                        f"CF:run{cf_runs}_impact_speed_mps",
                        round(float(result["impact_speed_mps"]), 4),
                        "m/s",
                        "CF",
                        how,
                        "derived",
                    ),
                    Fact(
                        f"CF:run{cf_runs}_min_gap_m",
                        round(float(result["min_gap_m"]), 4),
                        "m",
                        "CF",
                        how,
                        "derived",
                    ),
                ]
                store = store.extended(new)
                agent_facts.extend(new)
                out = [asdict(f) for f in new]
            elif name == "witness_recheck" and recheck_fn is not None:
                # Facts are immutable, so a second recheck under the same slug is refused rather than appended
                # (it once crashed a live run), and before the video upload when the slug itself repeats.
                if args["slug"] in rechecked:
                    existing = rechecked[args["slug"]]
                    out = {"error": f"slug already rechecked as {existing}; cite that fact or use a new slug"}
                else:
                    fact = recheck_fn(args["question"], float(args["t0"]), float(args["t1"]), args["slug"])
                    if store.has(fact.id):
                        out = {"error": f"{fact.id} already exists; cite that fact or use a different slug"}
                    else:
                        rechecked[args["slug"]] = fact.id
                        store = store.extended([fact])
                        agent_facts.append(fact)
                        out = asdict(fact)
            else:
                out = {"error": f"tool {name} unavailable in this run"}
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(out)})
    raise RuntimeError("investigator did not submit findings within the turn limit")
