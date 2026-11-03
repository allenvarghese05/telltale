# A5 video benchmark — success criteria, registered before the run

Written and committed **before** the 40-clip benchmark produced any numbers, so that the reading of the
result cannot be chosen to flatter it. Whatever comes back is reported against these thresholds.

## What is measured

Telltale's automatic danger onset against Nexar's own human `time_of_alert` annotation, on 40 clips drawn
with a fixed seed from the 686 eligible positives that are **not** in our demo manifest. Scored with the
**default** ego-lane polygon and no per-clip tuning.

## The label, exactly

From the Nexar Dashcam Collision Prediction Dataset paper, arXiv:2503.03848:

- `time_of_alert` is **"the earliest moment when a focused human can recognize that a dangerous situation
  is about to occur"**. Figure 1 and the Table 2 footnote phrase it as **"the earliest moment that the
  driver could intervene to prevent the accident"**.
- Each clip was annotated by several people. The **event time is the median** of their answers; the
  **alert time is the second-highest value**, chosen over the median explicitly because alert annotation is
  highly subjective, which biases the label toward shorter alert-to-accident intervals.

So the label is a *human perceptual* onset, deliberately skewed late. Telltale's onset is geometric: a
vehicle crossing into the ego lane, predicted to reach its edge within 2 s, or already in lane with
time-to-collision under 2 s. **A systematic positive offset is the predicted outcome, not a defect.**

## Why the headline metric is the spread, not a hit rate

On the three demo clips the signed errors were +1.10 s, +1.37 s and +2.06 s — consistent, and all above
1 s. A detector tracking the same moment as the annotator with a constant lag would therefore score near
zero on `within_0_5s` and `within_1_0s` and read as a failure. The spread of the signed error is the
honest measure of whether we are tracking the same moment; the offset is a separate, reportable fact.

## Buckets, fixed in advance

| Outcome | Condition | How it gets reported |
|---|---|---|
| **Strong** | median abs error ≤ 2.0 s **and** stdev of signed error ≤ 1.0 s | "Telltale identifies the same moment as the human annotator, with a consistent +X s lag — the direction and sign the label's definition predicts." |
| **Weak** | median abs error ≤ 2.0 s but stdev of signed error > 2.0 s | Reported plainly as noisy. The median is not quoted without the spread beside it. No spin. |
| **Intermediate** | median ≤ 2.0 s, stdev between 1.0 s and 2.0 s | Reported as partially consistent, with quartiles shown. |
| **Negative** | median abs error > 2.0 s | Reported as a negative result, with the worst clips and their causes. |

**Coverage below ~50%** (`onset_coverage = n_onset_found / n_attempted`) is a **headline limitation**, stated
alongside the error figures, never relegated to a footnote. Accuracy computed over clips we happened to
score says nothing about the ones we silently dropped.

## Rules for handling the result

- **No threshold, polygon or parameter in `telltale/video/` may be changed because of these 40 clips.**
  This is the only measurement in the project where an outside party set the answer key; tuning on it
  converts it into another piece of self-assessment.
- Failures are diagnosed and classified, not discarded: (a) no vehicle involved at all — pedestrian,
  animal, debris, ego-only braking; (b) a vehicle was involved but SAM's `--concept car` missed it — truck,
  bus, motorcycle; (c) other SAM or geometry error. If (b) is a large share, that is **reported** — running
  a second concept is a decision for the human, not a quiet fix.
- The pool stays unbiased. No "real crashes only" filter: Nexar marks collisions and near-misses alike as
  positives with no flag distinguishing them, and onset timing is equally well defined for both. Filtering
  with our own detector would bias the test set.

## Known approximation, stated up front

On a near-miss there is **no struck vehicle**, but `select_target` picks the largest box near
`time_of_event` regardless — so on those clips the "target" is the most prominent vehicle at the moment of
the near-miss rather than one that was actually hit. That is a reasonable stand-in for the vehicle the
human was reacting to, and it is an approximation rather than ground truth. It is named here so it cannot
be presented later as if it had always been exact.
