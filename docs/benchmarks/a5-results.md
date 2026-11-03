# A5 video benchmark — results

40 clips drawn with seed 7 from the 686 eligible Nexar positives not in our demo manifest, scored with the
**default** ego-lane polygon and no per-clip tuning. Read against the thresholds fixed in
[a5-preregistration.md](a5-preregistration.md) before these numbers existed. Raw rows: `video_bench.json`.

## Summary

```json
{
  "n_attempted": 40,
  "n_target_found": 40,
  "n_onset_found": 30,
  "onset_coverage": 0.75,
  "median_abs_err_s": 0.905,
  "p25_abs_err_s": 0.545,
  "p75_abs_err_s": 1.387,
  "mean_signed_err_s": -0.861,
  "median_signed_err_s": -0.617,
  "stdev_signed_err_s": 1.947,
  "within_0_5s": 0.233,
  "within_1_0s": 0.533,
  "within_2_0s": 0.8
}
```

## Pre-registered bucket: **intermediate**

Median absolute error 0.905 s is comfortably inside the 2.0 s threshold, and the middle half of clips lands
between 0.545 s and 1.387 s. But the spread of the signed error is **1.947 s**, which falls in the 1.0–2.0 s
band, not the ≤ 1.0 s the "strong" bucket required.

Per the pre-registration, this is reported as **partially consistent, with quartiles shown**. Telltale's
onset is usually close to the human annotator's, but not reliably so: the half of the distribution we get
right is tight, and the tail is long.

**The median is not quotable on its own.** 0.905 s beside a 1.947 s spread is a different claim from 0.905 s
alone.

## The sign flipped, and that matters

On the three demo clips the signed errors were **+1.10, +1.37, +2.06 s** — we fired consistently *later*
than the human, exactly as the label's late-skewed definition predicts. Across 40 unseen clips the mean
signed error is **−0.861 s**: on average we now fire *earlier*.

The three demo clips were not representative. They are highway and open-road scenes; this sample is 24 of
40 Urban. Had we reported the demo numbers as the result, we would have described the opposite behaviour
from the truth. This is the single clearest argument for having run the benchmark at all.

## Coverage: 30 of 40 (75%)

Above the 50% threshold that would have made it a headline limitation, but the ten misses are informative,
and **none was an exception** — every clip ran to completion.

| cause | count | clips |
|---|---|---|
| (a/b) SAM `--concept car` tracked **nothing at all** | 2 | 00271, 00944 |
| (c) vehicles tracked, but the struck vehicle never satisfied any hazard test | 8 | 00845, 00362, 00791, 00319, 00887, 00940, 00765, 00943 |

The eight in (c) are not detection failures: SAM tracked between 1 and 16 vehicles on each, all above the
resolvability floor, with maximum box widths of 173–511 px. The vehicles were plainly there; our three
hazard tests simply never fired on the one that mattered. On four of those eight, *other* vehicles did
register as hazards while the struck vehicle did not.

The two in (a/b) cannot be separated without watching them: either no vehicle was involved (pedestrian,
animal, debris, ego-only braking) or the vehicle was not a car (truck, bus, motorcycle) and the concept
missed it. **Running a second concept is a decision for the human, not a silent fix.** At 2 of 40 it is
unlikely to be the main story.

## By hazard reason

| reason | n | mean signed err | stdev |
|---|---|---|---|
| `predicted` | 17 | −0.56 s | 1.85 s |
| `closing` | 12 | −1.10 s | 2.08 s |
| `entering` | 1 | −3.13 s | — |

Two things stand out. **`entering` fired on 1 clip in 30** — real lateral cut-ins are rare in this dataset,
consistent with what the demo-clip curation found. And **`closing` carries both the largest early bias and
the widest spread**, which points straight at the diagnosis below.

## The five worst clips

| clip | error | onset | alert | reason | what it looks like |
|---|---|---|---|---|---|
| 00744 | **−6.53 s** | 0.95 s | 7.48 s | predicted | fires in the first second of the clip |
| 00287 | **−5.68 s** | 0.65 s | 6.33 s | closing | fires almost immediately; first hazard at 0.03 s |
| 00452 | −4.17 s | 2.40 s | 6.57 s | closing | fires 4 s before the human sees danger |
| 00007 | −3.13 s | 3.17 s | 6.30 s | entering | the only `entering` clip, and it is early |
| 00751 | −2.37 s | 4.40 s | 6.77 s | closing | first hazard at 0.00 s |

Every one is negative, and in each the onset sits at or near the clip's *first* hazard, very early.

## Diagnosis — reported, not acted on

**A time-to-collision under 2 s is ordinary in dense traffic.** Following distances in city driving are
routinely under two seconds, so the `closing` test fires on normal car-following long before anything
dangerous happens. The human annotator marks the moment danger became *recognisable*; we mark the moment
the geometry crossed a threshold that urban traffic crosses constantly. With 24 of 40 clips Urban, that
drags the mean signed error negative and fattens the tail.

This also explains why the demo clips disagreed: on a highway, a sustained TTC under 2 s really is unusual.

Consistent with that, the 8 coverage misses in bucket (c) are the mirror image — clips where the threshold
never fired on the struck vehicle at all.

**No threshold, polygon or parameter was changed in response to these numbers**, per the pre-registration.
Any fix must be justified on the demo clips or on first principles and then re-validated on a *fresh* draw;
re-tuning against this sample would convert the project's one independent measurement into self-assessment.

## Known approximation

On a near-miss there is no struck vehicle, but `select_target` takes the largest box near `time_of_event`
regardless. On those clips the "target" is the most prominent vehicle at the moment of the near-miss rather
than one that was hit — a reasonable stand-in for what the driver was reacting to, and an approximation
rather than ground truth. Nexar marks collisions and near-misses alike as positives with no flag separating
them, so the sample necessarily contains both.
