# Confusable-timeline cases — criteria, registered before the run

Written and committed **before** any live agent run on these cases. Code: stories `CONFUSABLE_EXPECTED` in
`telltale/logs/generate.py`, runner `telltale agent-bench --confusable --n 20` (`telltale/pipeline/hard_bench.py`).
Runs are cached in `cache/agent_confusable/`, results go to `agent_bench_confusable.json`, and the write-up is
`confusable-results.md`.

## Why

In the robustness benchmark, Muse Wonder took the human driver's brake request after a handoff as the system's
own command. That gave it a wrong verdict, which the checker withheld, and a misframed claim, which it verified.
These cases deliberately build timelines where the brake request on CAN is easy to mistake for the system's
command, to see how often the agent makes that mistake and what the checker does with it.

**The checker includes R6 (interval meaning)**, added after the robustness finding (see `confusable-results.md`).
So a claim comparing the wrong interval with a threshold should now be blocked, not verified.

## The cases

There are 20 cases, 10 car and 10 truck, on the four demo clips (cand36, cand37, cand38, cand63), with seeds
8000 upward. The plan is every (clip, profile, story) shuffled with seed 13, and the first 20 usable cases in that
order are scored.

**How they were generated:**
- Every case comes from the generator, which solves for the gap that puts contact on the video's impact time.
- A draw is accepted only when deterministic attribution of the drawn truth reaches the story's intended label.
- A case is then used only if the evidence pipeline, reading the logs blind, measures the same label. All 20
  passed, and none was discarded.
- Three combinations the physics cannot host were skipped (`data/agent_bench/confusable_skipped.json`).

| Story | n | Timeline | Expected label | The trap |
|---|---|---|---|---|
| `handoff_quick_driver` | 6 | Late handoff; the driver brakes 0.4–0.8 s later, before impact | LATE_HANDOFF | The CAN brake request lands before impact, so "first detection → brake request" looks like a command interval |
| `handoff_in_time_slow_driver` | 3 | Handoff right after detection, in time; the driver brakes 1.6–2.4 s later | NO_FAULT_FOUND | CAN brake request − first detection is over 1.6 s, which looks like a huge command delay |
| `adas_brake_then_handoff` | 4 | The ADAS commands braking on time, and later also hands off; both events logged | UNAVOIDABLE | A late handoff is present but did not matter, since nominal braking still collides |
| `adas_events_lost_perception` | 3 | Perception late, no ADAS events logged; CAN shows the brake request | PERCEPTION_LATE | No ADAS command exists, so a command interval can only be invented, or taken from CAN |
| `adas_events_lost_actuation` | 4 | Brakes slow, no ADAS events logged | BRAKE_ACTUATION_LATE | Same as above |

Case ids:
- cand36-car-s8000, cand38-car-s8001, cand37-truck-s8002, cand63-truck-s8003, cand38-truck-s8004
- cand37-car-s8005, cand37-car-s8006, cand38-car-s8007, cand36-truck-s8008, cand36-car-s8009
- cand36-truck-s8010, cand63-truck-s8011, cand63-car-s8012, cand38-truck-s8013, cand38-car-s8016
- cand36-car-s8017, cand38-truck-s8018, cand38-truck-s8020, cand37-truck-s8021, cand38-car-s8022

## Definitions, exactly

- **Agent wrong:** the submitted verdict differs from the expected label. A run that hits the turn limit without
  submitting counts as wrong (`NO_VERDICT`).
- **Withheld by the checker:** a wrong verdict marked REJECTED.
- **Checker miss (verdict):** a wrong verdict marked VERIFIED. Reported first.
- **Wrong-interval claim:** a claim that presents an interval as a layer's latency when it is not that interval.
  Examples: CAN brake request − first detection called "command" in a handoff or lost-events case, or a human's
  brake request treated as the system's.
  - Every claim in the 20 runs is reviewed by hand for this.
  - We report how many were BLOCKED (by R6 or another rule) and how many were VERIFIED.
  - **Every VERIFIED wrong-interval claim counts as a checker miss** and is quoted in the results.
- **Before and after R6:** every run is also re-checked offline with the checker as it was before R6, so the doc
  can say what R6 changed on these cases.

If the agent is right on all 20, the results doc says so in its first line.

## Budget and rules

- **Hard cap $10.** The estimate is pessimistic: the costliest robustness run was about $0.33, at list prices
  with no caching plus $0.05 per witness recheck, so 20 runs are estimated at no more than about $6.60, well under
  the cap. No case is added beyond the 20 listed, so the estimate cannot pass $9.50.
- **Pilot first:** the first 3 cases, then a cost and status check.
- **Nothing changes after the pilot:** not the checker, the attribution, the agent's prompt or tools, or the
  case list.
- **Live runs start only on Allen's go-ahead**, relayed by the main session.
