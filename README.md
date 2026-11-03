# Telltale

**Meta AI investigates vehicle crashes. A deterministic checker makes the investigation auditable.**

Live replay, no key needed: https://huggingface.co/spaces/Allen05254/telltale

## What it is

Telltale takes a real dashcam crash clip and the vehicle's own logs, and works out which part of the vehicle's
response failed: noticing the hazard, deciding to brake, or the brakes themselves. Meta AI does the
investigating. Plain Python checks every statement it makes before a person reads any of them.

One case runs like this:

1. **SAM 3.1** tracks every vehicle in the footage and timestamps the moment the struck vehicle became a hazard:
   it moved into the camera car's lane, was about to, or was already in the lane and closing.
2. **Muse Spark 1.3** watches the same clip as an independent witness: turn signals, brake lights, lighting,
   weather, road surface.
3. **A Muse Wonder agent** investigates the vehicle's CAN and ADAS logs. It uses a tool for every number, runs
   but-for crash simulations, can ask the witness for a second look, and decides the primary cause.
4. **Deterministic Python** recomputes every claim the agent made, and separately recomputes the verdict from
   the same evidence. A claim it cannot reproduce is blocked. A claim resting on one visual source is labelled
   single-source. If its verdict disagrees with the agent's, the verdict is withheld for human review.

The agent never sees the checker's own facts. The evidence store is immutable and hashed with SHA-256.

## Why it exists

Language models state things that are not true. Meta's evaluation report for Muse Spark 1.1 scored its input
hallucination at 1.67 in a Petri 3.0 alignment run, against 1.22 for GPT-5.5 and 1.34 for Claude 4.8 Opus, where
lower is better ([quoted here](https://www.eesel.ai/blog/meta-muse-spark-11-review)). In October 2026 a Muse
agent sent a user an unprompted message saying it could not check his Gmail for "that Anthropic message". He had
never asked, and Gmail was never connected. Meta attributed it to a bug that made the model hallucinate
([report](https://futurism.com/artificial-intelligence/man-quits-meta-muse-creepy)).

A crash investigation cannot carry statements like that. Telltale's answer is architectural, not a promise
about the model: the agent genuinely decides, and code proves or blocks every statement before a person sees it.

## Results

| Benchmark | Result |
|---|---|
| Danger onset against Nexar's human labels, 40 unseen clips, no per-clip tuning | Median absolute error 0.905 s, with the middle half of clips between 0.545 s and 1.387 s. Spread of the signed error 1.947 s. 80% within 2 s, 53% within 1 s. Onset found on 30 of 40 clips (75%). |
| Synthetic blind attribution, six failure stories, car and truck profiles | **Pending.** The run is in progress; this row will be filled from its committed results file. |
| Agent alone against agent plus checker | **Pending.** The run is in progress; this row will be filled from its committed results file. |

The danger-onset median is not quotable on its own. Against thresholds fixed in
[`docs/benchmarks/a5-preregistration.md`](docs/benchmarks/a5-preregistration.md) before the numbers existed,
the 1.947 s spread puts the result in the **partially consistent** bucket, not the strong one. On average
Telltale fires 0.861 s earlier than the human annotator, and the tail is long. The full analysis, including the
five worst clips and why, is in [`docs/benchmarks/a5-results.md`](docs/benchmarks/a5-results.md). The raw rows
are in [`video_bench.json`](video_bench.json). No threshold was tuned in response to them.

## Run it

**Replay, with no API key.** This rebuilds the same static site the hosted Space serves, from the cached
investigations in the repository.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
telltale export-site
telltale serve          # http://127.0.0.1:8000
```

**With your own key.** Copy `env.example` to `.env` and set `MODEL_API_KEY`. Then rerun the investigations
against the live Meta API; each run is cached, and the checker verifies it the same way.

```bash
cp env.example .env     # set MODEL_API_KEY; .env is never committed
telltale make-demo
telltale analyze-all --live
telltale export-site && telltale serve
```

**On any dashcam clip.** SAM 3.1 runs through Meta's cookbook script, which is not vendored into this
repository, so fetch it once first.

```bash
git clone --depth 1 https://github.com/meta-models/meta-model-cookbook vendor/meta-model-cookbook
pip install -r vendor/meta-model-cookbook/07_sam/01_api_basics/requirements.txt

telltale add-clip my_dashcam.mp4 --clip-id mine --event-time 7.4
telltale sam mine
telltale witness mine
telltale video-report mine
```

`video-report` describes what the footage alone establishes: the vehicles tracked, when the struck one became a
hazard and how, its lane changes, and the witness's conditions. It makes no claim about cause. That needs the
vehicle's own logs.

For development, install with `pip install -e ".[dev]"` and see [`AGENTS.md`](AGENTS.md).

## Data honesty

**The video is real.** Every clip comes from the Nexar Collision Prediction Dataset, under the Nexar Open Data
License (`data/clips/NEXAR_LICENSE`). Attribution: Moura & Zvitia, "Nexar Collision Dataset", Hugging Face, 2025.
No resale, and no re-identification of people, vehicles or plates.

**The vehicle logs are generated.** Real fleet CAN and ADAS logs are proprietary, and we have no access to any.
The logs are generated by [`telltale/logs/generate.py`](telltale/logs/generate.py) to match each clip's hazard
and impact times, with faults injected blind and at random, and clock skew applied. Swap in a real fleet's logs
and the pipeline is unchanged.

**Ground truth stays hidden.** The fault each log was generated with is stored under `data/ground_truth/`, and
only benchmark scoring code reads it. The agent, the checker and the evidence builder never do.

**Only public data reaches the Meta API.** Free-tier credits allow Meta to use submitted content, so nothing
private is ever sent.

## Scope and limits

**Full causal attribution covers forward conflicts: rear-end and cut-in crashes.** The crash physics is
one-dimensional and longitudinal. Cross-path crashes, such as the intersection U-turn in clip `cand60`, get the
video-only report, which makes no claim about cause.

**Telltale never decides legal responsibility.** It identifies which step in the vehicle's response fell outside
its specification, and hands a person a verified timeline to sign off.

Next steps, each with a reason measured during the build:

- **Two-dimensional physics** for cross-path geometry, so crashes like `cand60` can be attributed too.
- **Motion-based tracklet re-association**, in the style of ByteTrack or OC-SORT with camera-motion
  compensation, for long or heavily occluded footage. On the four committed SAM tracks whose struck vehicle
  could be identified (`cand36`, `cand37`, `cand38`, `cand63`), SAM 3.1 already held one identity for that
  vehicle in every frame with no gaps, so this is for harder footage than the demo uses.
- **A speed-aware hazard threshold.** The fixed rule, a time to collision under 2 s, fires on ordinary car
  following in dense traffic, which is why Telltale fires early on urban clips. On 8 of the 40 benchmark clips,
  none of the hazard tests fired on the struck vehicle at all.

## How it was built

Telltale was built during the Meta Global AI Developer Hackathon, October 26 to November 4, 2026. The work ran
as four parallel tracks in separate git worktrees (video, vehicle logs and physics, the agent and checker, and
the replay site), each building against data formats locked on the first night. The plans are in
[`docs/plans/`](docs/plans/), and the rules every contributor and coding agent follows are in
[`AGENTS.md`](AGENTS.md).
