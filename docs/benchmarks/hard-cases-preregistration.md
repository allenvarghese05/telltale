# Hard-case agent benchmark — criteria, registered before the run

Written and committed **before** any live agent run on these cases, so the reading of the result cannot be
chosen to flatter it. Whatever comes back is reported against the definitions below.

## Why this benchmark exists

On the 19-case agent benchmark Muse Wonder's verdict was right 19 of 19 times, so the checker's verdict path
was never exercised by a natural mistake. It was shown only by a hand-edited red-team case. This benchmark makes
the calls genuinely close, to test honestly whether the checker catches real agent mistakes.

## The cases

30 cases, generated blind by `telltale agent-bench --hard --n 30` (code: `telltale/pipeline/hard_bench.py`,
stories: `HARD_EXPECTED` in `telltale/logs/generate.py`). Car and truck are mixed: 12 car, 18 truck.

| Family | Stories | What makes it hard |
|---|---|---|
| Tight (16) | `tight_perception_command`, `tight_command_perception`, `tight_actuation_perception`, `tight_perception_actuation`, `tight_handoff_perception` | Two steps are both over their limits. The primary wins by 0.03 to 0.09 s of excess over its threshold. |
| Marginal (9) | `marginal_perception`, `marginal_command`, `marginal_actuation` | One step is just over its limit (0.01 to 0.10 s of excess) next to another step that missed its own limit by 0.005 to 0.04 s. |
| Unavoidable with fault (5) | `unavoidable_with_fault` | The but-for run with nominal timings still collides, but one step also overran its limit by 0.05 to 0.40 s. The correct label is UNAVOIDABLE, and the overrun is a noncausal fault. |

Every hard case also has larger clock skews than the demo cases: the CAN clock is off by up to ±8 s, and the ADAS
clock by up to ±1.3 s relative to CAN. (The ADAS aligner searches ±1.5 s, so that is the honest limit.)

**Physical consistency.** As with the existing stories, the gap at hazard onset is solved so the simulated
contact lands on the video's impact time. Combinations the physics cannot host are skipped, not forced: 10 of
the first 40 planned combinations, mostly on `cand63` (5.3 s from hazard onset to impact, too long for a
close call). A car braking at 8 m/s² avoids a ~2 s cut-in whenever braking is meaningfully late, so car
"unavoidable with fault" cases exist only on the shorter clips. The skipped list is in
`data/agent_bench/hard_skipped.json`.

**Where the expected label comes from.** It is never hand-assigned. A draw is accepted only when deterministic
attribution of the drawn hidden truth reaches the story's intended label. The case is then used only if the
evidence pipeline, reading the generated logs blind, measures the same label. The label goes to
`data/agent_bench/ground_truth/<case>.json`. The agent, the checker and the evidence builder never read that
folder. All 30 cases passed the blind-measurement check, and none were discarded.

**Fixed order.** The plan is every (clip, profile, story) shuffled with seed 11, with case seeds 7000 upward. The
benchmark scores the first 30 usable cases in that order. The order was not chosen after seeing any agent output.

## Definitions, exactly

- **Agent wrong:** the verdict Muse Wonder submits differs from the expected label. A run that hits the turn
  limit without submitting counts as **wrong** (`NO_VERDICT`). It is not retried and not dropped.
- **Checker catches it:** a wrong agent verdict that the checker marks `REJECTED`, so the report is withheld
  pending human review.
- **Wrong verdict verified:** a wrong agent verdict that the checker marks `VERIFIED`. This is the failure that
  matters most. **If any occurs it is reported in the first paragraph of the results doc, with the case id, the
  agent's label, the expected label and the cause.** It is never relegated to a table or a footnote.
  - The verdict check compares the agent with the pipeline's independent attribution. On these cases that
    attribution equals the ground truth by construction, so a verified wrong verdict should be impossible. If
    one appears, it is a bug, and it is reported as one.
  - For the same reason, this benchmark tests whether the checker catches the agent. It does not test the
    attribution itself against an outside answer key, and the results doc will say so.
- **Correct but withheld:** a correct agent verdict marked `REJECTED`. Reported separately. It would mean the
  pipeline and the ground truth disagreed.
- **API errors** (503s, timeouts) are infrastructure, not agent mistakes. A case interrupted by one is re-run
  until it completes. Only completed runs and `NO_VERDICT` runs are scored.

## What gets reported

1. **Agent accuracy alone**, as k of n, overall and split by family (tight, marginal, unavoidable) and by
   profile (car, truck).
2. **How many wrong verdicts the checker withheld**, as k of the wrong ones.
3. **Wrong verdicts that were verified:** the count, prominently, even if it is zero.
4. **Claims:** verified, single-source and blocked counts. Each blocked claim is classified by hand and listed
   with its checker reason:
   - **Falsehood:** the claim states something the evidence contradicts. The recomputed value differs from the
     claimed one, a comparison is false, or a number in the text is wrong.
   - **Form block:** the statement is true, but it cannot be proven as written. Examples: a correct interval that
     cites only one endpoint, a numeric check on a yes/no fact, or a number taken from a tool argument rather
     than a fact.
5. **If the agent is right on all 30,** the results doc says so plainly in its first line. That is a result: it
   means these cases did not produce a natural catch, and the catch path stays shown only by tests and the
   red-team case.

## Rules for the run

- **Nothing changes after the pilot.** No change is allowed to the checker, the attribution, the thresholds,
  the agent's system prompt or tools, or the case set because of anything the agent does on these cases.
  - A bug found in generation or the pipeline (not in the agent's behaviour) may be fixed. The fix is disclosed
    in the results doc, and every affected case is regenerated and re-run.
- **Pilot first.** The first 5 cases run live, and the run then pauses for review before the remaining 25.
- **Budget.** At most about $30 of Meta API credit, a hard ceiling and not a target. If the ceiling is reached
  before 30 cases complete, the results report the cases that completed, state the shortfall, and no case is
  cherry-picked to fill it.
- **Separation.** Agent runs are cached in `cache/agent_hard/` and scored into `agent_bench_hard.json`. The
  19-case benchmark (`cache/agent_bench/`, `agent_bench.json`) is untouched.
