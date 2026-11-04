# Hard-case agent benchmark — results

**Muse Wonder was right on all 30 hard cases, so the checker had no wrong verdict to catch.** No wrong verdict
was verified, and none was withheld, because there were none. Every one of the 261 claims verified, and none
was blocked or left single-source. So these cases did not produce a natural catch. The checker's catch path is
still shown only by tests and by the hand-edited red-team case (`cand36-redteam`).

The criteria were fixed in [`hard-cases-preregistration.md`](hard-cases-preregistration.md) (commit `b1cf647`),
which was committed with the 30 cases before any live run. Raw rows are in
[`agent_bench_hard.json`](../../agent_bench_hard.json), and the agent runs are in `cache/agent_hard/`.

## Headline numbers

| Measure | Result |
|---|---|
| Agent accuracy alone | **30 of 30** (car 12 of 12, truck 18 of 18) |
| By family | tight 16 of 16, marginal 9 of 9, unavoidable with a noncausal fault 5 of 5 |
| Wrong verdicts withheld by the checker | 0 of 0 (no wrong verdicts) |
| **Wrong verdicts that were verified** | **0** |
| Correct verdicts withheld | 0 |
| Runs that never submitted (`NO_VERDICT`) | 0 |
| Independent attribution vs ground truth | 30 of 30, as built: a case was used only if the blind pipeline agreed with the drawn truth |
| Claims | 261 total: 261 verified, 0 single-source, 0 blocked |
| Blocked claims, falsehood vs form | 0 falsehoods, 0 form blocks |

## How close the calls were

These are the margins the evidence pipeline measured from the logs, as excess over each threshold, read from the
hidden `ATTR:excess_*` facts:

- **Tight (16):** the winning step beat the runner-up by 0.037 to 0.092 s. Both steps were over their limits in
  every case. The closest was `cand37-truck-s7035`: actuation +0.230 s against perception +0.193 s. Correct.
- **Marginal (9):** the faulty step was over its limit by 0.052 to 0.100 s. The near miss beside it was under its
  own limit by 0.006 to 0.039 s. The closest was `cand38-truck-s7032`: actuation +0.070 s, with perception
  0.006 s under. Correct.
- **Unavoidable with a fault (5):** a step overran by 0.07 to 0.33 s, but the nominal-timing counterfactual still
  collided.
  - In every one the agent said UNAVOIDABLE, and its claims named the overrun as real.
  - For example (`cand38-truck-s7039`): "Because contact persists under nominal timings, the crash was
    unavoidable despite the perception interval exceeding its threshold."
  - This was the trap most likely to catch an agent that just picks the biggest fault. It didn't.

Actuation margins are coarser than the drawn ones (+0.07 or +0.09 s rather than a continuous value), because CAN
pressure frames are 20 ms apart. The margins above are the measured ones, which is what both the agent and the
checker saw.

## Why the agent got them all right (our reading)

- **It never does arithmetic itself.** Every interval comes from the `measure` tool, which subtracts two facts
  exactly. A 0.04 s margin is as easy to read correctly as a 0.4 s one. On these 30 runs it called `measure`
  4 to 11 times per case and `run_counterfactual` 32 times in all, at least once per case.
- **The decision rule is in its instructions.** It runs the but-for counterfactual first, then picks the step with
  the largest excess over its threshold. Once each number is exact, a close call is a comparison, not a judgement.
- **So these cases test procedure, not perception.** They make the arithmetic tight. They do not make the
  evidence ambiguous. Cases that could plausibly trip the agent would have contradictory or missing evidence:
  a witness that disagrees with SAM, a missing ADAS event, or an implausible clock offset. Those are outside
  this benchmark and are not claimed here.

## What this does and does not show

- **It does show** that, on 30 blind cases built to be close and run with the checker unchanged, the agent's
  verdict and all 261 of its claims survived independent recomputation. The 19-case benchmark found the same:
  19 of 19 correct.
- **It does not show** that the checker catches natural wrong verdicts, because none occurred. That path is
  covered by `test_analyze_rejects_a_wrong_agent_verdict` and `test_verdict_verified_and_rejected`, and is
  demonstrated by the red-team case.
- **It does not test the attribution against an outside answer key.** Ground truth here is the deterministic
  attribution of the generator's hidden truth, so "independent accuracy 30 of 30" is consistency by
  construction. The only outside-label benchmark in the project is the video one, against Nexar's human labels.

## Run notes

- 30 live investigations, run 2026-11-03 from 21:35 to 22:19 EST. Each took about 84 s on average (32 to
  445 s; the 445 s case sat through the 503 spell below).
  The run made 161 chat completions and 25 witness-recheck video uploads across the pilot and the main run.
- There were 5 HTTP 503 responses from the Meta API between 22:00 and 22:06. The OpenAI SDK's built-in retry
  (two retries, 60 s back-off) absorbed all of them, and no run failed or was restarted.
- No change was made to the checker, the attribution, the thresholds, the agent's prompt or tools, or the case
  set after the pilot. No generation or pipeline bug was found, so nothing was regenerated.
- 10 of the first 40 planned (clip, profile, story) combinations could not be hosted by the physics and were
  skipped before any agent run (`data/agent_bench/hard_skipped.json`).

## Truck demo cases (same evening)

The replay site gained a truck version of every demo story the clips can host, 18 cases in all:
- all five stories on `cand36`, `cand37` and `cand38`;
- perception, brake and handoff on `cand63`. Its 5.3 s hazard window cannot host a truck command-late or
  unavoidable crash.

Each truck case has its own per-clip seed, and the car seeds are unchanged. All 18 ran live from 22:20 to
22:43 EST:
- **18 of 18 verdicts matched the injected story and were VERIFIED.**
- **165 of 165 claims verified**, with 0 single-source and 0 blocked.

There were no API errors. Rendering was checked by exporting the site and opening `cand36-truck-s1275` locally.
