# Perception-error propagation — pre-registration

Committed before any result of this study was computed. Zero API cost: no model is called.

## Question

If perception (SAM 3.1 plus Telltale's video code) gets the hazard onset wrong, how often does the deterministic
attribution change? And at the error SAM actually makes in the real world, as measured on the 400-clip benchmark,
how stable is the verdict?

## Cases

Every committed case that has ground truth:

- the **16 demo cases** in `data/cases` (red-team case excluded: it has no ground truth and its run is altered);
- the **19 agent-benchmark cases** in `data/agent_bench/cases`.

All 35 use the car profile. No truck cases exist on this branch. If truck or hard cases reach `main` before the
pull request opens, they are added and the change is recorded. Ground truth is read only by this study's scoring
code, never by the checker or agent paths.

## Method

Everything reuses existing code. Each perturbation builds a modified `VideoFacts` or log copy and calls the
existing `build_store`, which re-runs alignment, the counterfactual and `attribute`. The label read is
`ATTR:label`. No physics is reimplemented.

1. **Onset shift.** `VID:hazard_onset_t` is moved by δ ∈ {−2, −1, −0.5, −0.25, +0.25, +0.5, +1, +2} s. A shift is
   **infeasible**, and reported as such, never dropped, if the shifted onset is at or before the clip start
   (t ≤ 0) or at or after impact.
2. **Flip margin.** For each case, the smallest |δ| on a 0.05 s grid over ±3 s at which the label first changes,
   on the early and late side separately.
3. **Missed onset.** What the pipeline does when SAM misses the car, and separately a what-if: `attribute` with
   perception latency unknown and every other measured value unchanged.
4. **Measured real-world error.** The signed errors of all 260 scored clips in the n = 400 benchmark (scoring A,
   onset minus human alert) are applied as onset shifts to every case. Evaluating every empirical error gives the
   exact expectation over the measured distribution, with no sampling and therefore no seed. Reported twice: with
   all 260 errors, and without the start-of-clip tail (onset in the clip's first 2 s, 25 clips). The tail split
   is exploratory and post hoc, as in the benchmark results.
5. **Log clock corruption.** The ADAS log is anchored to CAN by matching speed traces within ±1.5 s of the CAN
   anchor. Extra ADAS skew of 0, 0.5, 1.0, 1.5, 2.0, 2.5 and 3.0 s is added to a copy of each case's log, and the
   study records the recovered offset error and the label. CAN skew is anchored by the impact trigger, so it is
   tested at ±1 and ±5 s to confirm it has no effect.

## Metrics

- **Stability:** the share of feasible perturbations where the label equals the unperturbed label.
- **Correctness:** the share where the label equals the ground-truth expected label.
- **Flip direction:** what the label changes to.
- **Infeasible:** the count of perturbations with no verdict, shown beside every rate.

All are reported overall and by story. Two hypotheses are stated in advance:

- perception-late cases are the most sensitive, because their margin is measured from the onset;
- unavoidable cases depend on gap and speed, so they flip when an onset moved later shortens the time available.

## Rules

- The study changes no code in `telltale/physics`, `telltale/evidence`, `telltale/verify` or `telltale/video`.
- Any design improvement it suggests is described, not implemented.
