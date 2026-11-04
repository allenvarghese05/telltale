# A5 at scale — pre-registration

Committed **before** any clip beyond the original 40 was scored. It extends
[a5-preregistration.md](a5-preregistration.md) and changes none of its rules.

## Why scale

The 40-clip run is the project's only measurement with an outside answer key, and 40 clips is too few to trust
a spread estimate: one clip moves the signed-error stdev noticeably. This run draws as many more clips from the
same pool as the budget allows.

## What stays frozen

- **Thresholds and ego-lane polygon** are those of the 40-clip run (`DANGER_TTC_S = 2.0`, `DANGER_TLC_S = 2.0`,
  the default polygon, no per-clip tuning, the same hazard tests). The scoring code is *not* identical; see the
  correction below.
- **Seed 7 and the same shuffle.** The run takes the first *n* clips of one seeded ordering, so the original 40
  are its prefix.
- **The same buckets, coverage rule and failure classes** as a5-preregistration.md:

| Outcome | Condition |
|---|---|
| **Strong** | median abs error ≤ 2.0 s **and** stdev of signed error ≤ 1.0 s |
| **Intermediate** | median ≤ 2.0 s, stdev between 1.0 s and 2.0 s |
| **Weak** | median ≤ 2.0 s but stdev > 2.0 s |
| **Negative** | median abs error > 2.0 s |

  Coverage below ~50% is a headline limitation. Failures are classed (a) no vehicle involved, (b) a vehicle SAM's
  `--concept car` missed, (c) other SAM or geometry error.
- **Nothing in `telltale/video/` may change because of the result.** Any later fix is justified on first
  principles and validated on a fresh, separately pre-registered draw.

## One change made before scaling, and why it is not tuning

Reproducing the original draw required a fix to how the pool is selected, committed before any new clip was
scored.

When the 40-clip run happened, the demo manifest held 64 candidate clips, and the pool excluded all of them.
The manifest now holds only the 4 chosen demo clips. Excluding just those 4 changes the list the seed shuffles,
and the resulting first 40 shared **zero** clips with the original 40. Running `--n 60` unchanged would have
discarded the original sample and scored 60 different clips under the same seed.

The fix freezes the original exclusions in `data/bench_clips/pool_exclusions.json`. The 64 ids were
reconstructed from the deterministic candidate ranking (alert-to-event gap, descending) and verified three ways:

- all 11 candidate-to-clip mappings recorded during curation land at the right positions;
- the pool comes out at exactly **686** clips, the size the original run logged;
- the code's own seed-7 draw reproduces the committed 40 **exactly**.

A second, related fix: scoring took the first *n* entries of the bench manifest, which is stored in clip-id
order, not draw order. That was correct only because all 40 downloads had succeeded. Scoring now follows the
draw, and failed downloads are recorded in the results instead of only logged.

Both changes affect which clips are drawn, never how a clip is scored. No threshold, polygon or detector moved.

## How the results will be reported

Three ways, each against the buckets above:

1. **The original 40.** A re-score from cached SAM tracks, which should match the published 40-clip numbers; any
   difference is reported.
2. **The new clips only**: the honest out-of-sample number, since the original 40 informed the diagnosis.
3. **The whole set.**

For each: median and quartiles of absolute error, mean, median and stdev of signed error, within 0.5 s, 1 s and
2 s, coverage, and failure classes. The 40-clip diagnosis predicted that a sub-2 s time-to-collision fires early
on ordinary car-following in dense traffic, giving a negative mean signed error driven by `closing` onsets. The
scaled results report whether that holds, broken down by hazard reason.

Download failures and API errors (503s are expected tonight: two other tracks share the Meta API) are infra
failures, not detector failures. Cached clips are re-run until no API error remains; any that persist are
listed and excluded from coverage, with the count stated.

## Budget

Meta credit must not drop below $30. This benchmark may spend at most about **$60**, a ceiling, not a target. A
20-clip pilot measures time and cost per clip first; the run pauses for approval after the pilot and again before
estimated spend passes $40.

## Amendment, after the 20-clip pilot and before any further clip was scored

### Correction: the scoring code changed after the 40-clip run

The section above originally said the scoring code was the same as the 40-clip run's. That was wrong, and the
pilot exposed it: re-scoring the original 40 from their cached, unchanged SAM tracks gave 26 onsets instead of
30 and a median absolute error of 1.033 s instead of 0.905 s.

Identical tracks giving different results meant the code had moved. Exactly one scoring commit landed after the
40-clip run: `bee03f6`, which makes target selection prefer the largest vehicle that spent the last second
mostly in the ego lane, instead of the largest box at impact. It fixed a demo-clip bug (cand56, where an
overtaking pickup in the next lane was chosen as the struck vehicle) and was measured on the demo tracks, not
on benchmark clips. It changes the result on 10 of the original 40 clips: 7 lose their onset, 2 gain one, 1
moves.

Both scorings are kept computable, because the SAM tracks are cached and the pre-`bee03f6` code can re-score
them at any time without an API call:

- **A**: current code, including `bee03f6`, the detector that ships;
- **B**: the code of the 40-clip run, comparable with the published numbers.

Which one is the headline is decided on principle by the project owner, recorded here, and both are reported
side by side regardless.

### Stopping rule

The target is **all 686 eligible clips**. The run stops early for only two reasons:

1. **Budget.** This benchmark's ceiling is about $60 of Meta credit, and total credit must stay above $30. Spend
   is released in steps, each confirmed against the billing dashboard.
2. **Time.** The morning cutoff at about 07:00 EST.

It **never** stops because of the results. Whatever n is reached when one of those two limits binds is the n
reported, along with which limit it was. This rules out stopping once the numbers look good.

### Decision: scoring A is the headline

Recorded during the n = 160 step, before the full results exist. The project owner chose **scoring A**, the
current code including `bee03f6`, because the benchmark should measure the detector that ships, with every fix
made since. In his words: "it should be A right because that is better and new with all the updates."

For the record, the owner had seen the 20-clip pilot under scoring A when he chose. The choice rests on which
detector the benchmark describes, not on which number is better, and both scorings stay reported side by side.

The results document shows the published 40-clip figures next to the re-scored ones and explains the
difference. `bee03f6` picks the struck vehicle from those that spent the last second mostly in the ego lane, so
on 10 of the original 40 clips a different vehicle is scored: 7 lose their onset, 2 gain one, 1 moves.
