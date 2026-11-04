# Perception-error propagation — results

Read against [perception-sensitivity-preregistration.md](perception-sensitivity-preregistration.md), committed
before any result was computed. Raw results: `perception_sensitivity.json`, produced by
`scripts/perception_sensitivity.py`. **Zero API cost:** every perturbation rebuilds evidence from committed logs
with the existing `build_store`, which re-runs alignment, the counterfactual and `attribute`.

**83 cases with ground truth:** 34 demo (16 car, 18 truck) and 49 agent-benchmark (19 original, 30 hard), across 15
stories. Unperturbed, the deterministic attribution matches ground truth on **83 of 83**.

## Headline

**At the hazard-onset error SAM actually makes in the real world, the deterministic verdict is unchanged only
46% of the time.**

Every case was re-attributed at each of the 260 signed onset errors measured on the 400-clip benchmark (scoring A),
21,580 rebuilds in all:

| errors applied | feasible | verdict unchanged | infeasible (onset past impact or before the clip) |
|---|---|---|---|
| all 260 measured errors | 20,214 | **9,364 (46%)** | 1,366 |
| without the start-of-clip tail (235) | 18,517 | **8,867 (48%)** | 822 |

The start-of-clip tail split is exploratory and post hoc, as in the benchmark results. Removing it barely helps:
the instability comes from the bulk of SAM's error, not its tail.

The reason is in the margins. For each case, the smallest onset shift that changes the label:

| side | cases that flip | median margin | flip within 0.5 s | flip within 1 s |
|---|---|---|---|---|
| onset later | 61 of 83 | **0.30 s** | 40 | 57 |
| onset earlier | 60 of 83 | **0.45 s** | 33 | 51 |

SAM's median absolute onset error on unseen clips is 0.88 s. **The typical verdict tolerates less timing error
than SAM typically makes.**

## The flips are systematic, not random

Under the fixed onset shifts:

| onset shift | verdict unchanged | most common change |
|---|---|---|
| −2.0 s | 23/83 (28%) | brake-late → perception-late (×17) |
| −1.0 s | 32/83 (39%) | brake-late / handoff-late / unavoidable → perception-late |
| −0.5 s | 50/83 (60%) | brake-late → perception-late (×12) |
| −0.25 s | 57/83 (69%) | unavoidable → perception-late (×9) |
| +0.25 s | 53/83 (64%) | brake-late → unavoidable (×12) |
| +0.5 s | 43/83 (52%) | brake-late → unavoidable (×16) |
| +1.0 s | 26/83 (31%) | perception-late → unavoidable (×18) |
| +2.0 s | 10/32 (31%), 51 infeasible | perception-late → unavoidable (×7) |

A wrong onset pushes the verdict toward one of exactly two labels, and the code says why:

- **An onset placed too early blames perception.** Perception latency is computed as `AV:first_seen_t − onset`, so
  an earlier onset makes the car's driver-assist look slower to notice the hazard.
- **An onset placed too late excuses everyone.** The but-for counterfactual starts at the onset, so a later onset
  leaves the simulated nominal car less time and distance, it collides anyway, and the verdict becomes
  `UNAVOIDABLE`.

SAM's measured errors lean early (mean −0.99 s), so in the measured-error run the commonest flips are *to*
`PERCEPTION_LATE`: brake-late (1,950), unavoidable (1,756), command-late (1,588) and handoff-late (1,424). Next is
brake-late → unavoidable (1,374).

## By story

Verdict unchanged under SAM's measured errors (all 260 / without the tail):

| story | unchanged |
|---|---|
| marginal_command | 9% / 9% |
| marginal_actuation | 11% / 12% |
| tight_actuation_perception | 12% / 13% |
| brake_slow | 26% / 29% |
| tight_command_perception | 30% / 33% |
| command_late | 35% / 38% |
| unavoidable | 47% / 52% |
| tight_handoff_perception | 48% / 49% |
| unavoidable_with_fault | 48% / 53% |
| late_handoff | 49% / 52% |
| marginal_perception | 60% / 56% |
| tight_perception_command | 62% / 58% |
| tight_perception_actuation | 63% / 59% |
| **perception_late** | **78% / 76%** |
| dropout | 100% / 100% |

**Pre-registered hypothesis 1, that perception-late cases would be the most sensitive, is refuted.** They are the
most stable story apart from dropout. The mechanism above explains it: an onset error in the early direction only
makes perception look later, so the label stays `PERCEPTION_LATE`. Only a later onset can flip it, and SAM's
errors are mostly early. The most fragile are the stories where a non-perception fault is close to its threshold
(marginal command and actuation, and tight pairs led by actuation), because any early onset error hands the
blame to perception.

**Pre-registered hypothesis 2, that unavoidable cases depend on gap and speed, is partly supported.** No unavoidable
case flips when the onset moves *later* (0 of 9, and 0 of 5 for unavoidable-with-fault). Less time keeps a
collision unavoidable. They do flip when the onset moves *earlier*, which hands the counterfactual more runway and
turns the case into perception-late.

**Dropout cases never change (100%).** An incomplete brake log makes the verdict `INCONCLUSIVE` regardless of
timing, as designed.

By profile, car and truck are similar (50% and 45% unchanged across the shift grid). By set, the hard cases are the
most fragile (35%), as they were built to be, then demo (52%) and agent-bench (61%).

## Missed onset

**What the pipeline does.** When SAM misses the struck vehicle, `compute_video_facts` raises and no case is built.
There is no verdict at all, rather than a guessed one.

**What-if: attribution with perception latency unknown** and every other measured value unchanged. 63 of 83
verdicts are unchanged. **All 20 that change were perception-late**, and 13 of them become `NO_FAULT_FOUND`. With
the onset gone, the one fault that existed is invisible, and the car is cleared.

So the pipeline's refusal is the right behaviour, and it is load-bearing. A version that ran on without an onset
would clear the car in exactly the cases where perception was at fault.

## Log clock corruption

**ADAS skew.** The ADAS log is aligned to CAN by matching speed traces within ±1.5 s of the CAN anchor. Extra skew
on a copy of each case's ADAS log:

| extra ADAS skew | ADAS offset recovered (±0.05 s) | verdict unchanged | worst offset error |
|---|---|---|---|
| 0 s | 83/83 | 83/83 | 0.00 s |
| 0.5 s | 78/83 | 81/83 | 0.26 s |
| 1.0 s | 64/83 | 78/83 | 0.76 s |
| 1.5 s | 43/83 | 69/83 | 1.26 s |
| 2.0 s | 20/83 | 53/83 | 1.76 s |
| 2.5 s | 9/83 | 45/83 | 2.26 s |
| 3.0 s | 0/83 | 37/83 | 2.76 s |

Alignment degrades before the nominal 1.5 s edge, because each case already carries its own ADAS skew relative to
CAN: up to ±0.8 s in the standard generator and up to ±1.3 s in the hard cases. That uses part of the window.

**CAN skew.** The pre-registration expected CAN skew to have no effect, since CAN is anchored to the video by the
impact trigger. **That expectation is refuted.** CAN's own offset is indeed recovered exactly, but the ADAS search
window is centred on the CAN anchor, so shifting CAN moves the window away from the true ADAS offset:

| CAN skew | ADAS offset recovered | verdict unchanged |
|---|---|---|
| −5 s | 0/83 | 35/83 |
| −1 s | 64/83 | 78/83 |
| +1 s | 66/83 | 71/83 |
| +5 s | 0/83 | 17/83 |

What matters is the **relative** CAN–ADAS skew. Beyond the window the grid search still returns its best offset
inside the window, so the failure is silent: the store carries a wrong `AV:clock_offset_s` and nothing flags it.

## Findings in plain English

1. **The verdict is sensitive to perception timing.** At SAM's real-world error it holds about half the time. The
   attribution engine is right on 83 of 83 cases when it is fed the true onset, but the onset is the weakest input
   it has.
2. **Perception errors bias the verdict in a known direction.** An early onset blames perception, and a late one
   excuses everyone. Since SAM errs early, the practical risk is **over-blaming perception**.
3. **Perception-late findings are the most trustworthy; near-threshold non-perception findings the least.**
4. **Refusing to run without an onset is essential.** Running on would have cleared the car in every
   perception-late case that changed.
5. **Clock alignment fails silently** once the relative CAN–ADAS skew leaves the search window.

## Proposed design improvement (described, not implemented)

**A timing-robustness gate on every verdict.**

After attribution, re-run it with the hazard onset moved across the perception error band measured on the
400-clip benchmark: at minimum a band of ±0.9 s (SAM's median absolute error on unseen clips), and ideally the
full set of measured errors. Then report the verdict as one of:

- **Robust:** the label holds across the band. Publish as now.
- **Timing-sensitive:** the label changes within the band. Publish the verdict together with the alternative and
  the onset shift that produces it, e.g. *"perception-late if the hazard began at 6.1 s; unavoidable if it began
  0.3 s later"*, and route the case to human review the way a rejected verdict already is.

Why this rather than something else:

- **The data supports it directly.** The median flip margin (0.30 s late, 0.45 s early) is smaller than SAM's
  median error, so most verdicts would be flagged. That is the honest state of the evidence, not a defect of the
  gate.
- **It reuses the existing deterministic path.** One rebuild takes roughly 30–60 ms (this study averaged about
  50 ms over car and truck cases), so a band of a few dozen shifts costs a second or two per case, and adds nothing
  an agent could game.
- **It names the direction of doubt.** A flagged perception-late verdict and a flagged brake-late verdict mean
  different things, and the gate says which way the evidence leans.

Two smaller observations from the same data:

- The clock-alignment search should report when its best offset sits at the edge of its window, rather than
  returning it silently.
- The gate and the start-of-clip fix from the benchmark work together: excluding onsets in the first frames of
  footage removes the worst early errors before the gate sees them.

## What was not done

- No code in `telltale/physics`, `telltale/evidence`, `telltale/verify` or `telltale/video` was changed. The study
  only calls it.
- Ground truth was read only by the study's scoring, never by the checker or agent paths.
- No infeasible perturbation was dropped. All are counted above.
- No model was called.
