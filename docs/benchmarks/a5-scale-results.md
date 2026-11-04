# A5 at scale — results

Telltale's automatic danger onset against Nexar's human `time_of_alert` annotation, on **400 clips** drawn with
seed 7 from the 686 eligible Nexar positives not in the demo set. Read against the thresholds fixed in
[a5-preregistration.md](a5-preregistration.md) and [a5-scale-preregistration.md](a5-scale-preregistration.md),
both committed before the clips they govern were scored. Raw rows: `video_bench.json`. Every number here is
computed from those rows, the bench manifest and the cached SAM tracks in `cache/sam_bench/`.

## Method, in one paragraph

Each clip is trimmed to the 8 s before the labelled event plus 1.5 s after it. SAM 3.1 tracks every vehicle,
deterministic code finds the struck vehicle and the moment it became a hazard, and that moment is compared with
the human alert label. Nothing was tuned per clip: the ego-lane polygon is the default, and the hazard thresholds
are the same 2 s time-to-collision and 2 s time-to-lane-crossing as in the 40-clip run.

**Where it stopped, and why.** The overnight release was capped at n = 410 by budget, set before any of those
clips was seen. It stopped at 06:21 EST, when its stall guard fired after 15 minutes without progress. All 410
clips had been downloaded and 400 SAM-tracked. The 10 untracked clips are exactly draw positions 401–410, so
**n = 400 is a complete prefix of the draw**. It was scored from cache, with no further API calls. The run stopped
on its pre-registered "stop rather than retry" rule, not because of the results. There were no download failures
and no API errors among the 400.

## The label, briefly

`time_of_alert` is "the earliest moment when a focused human can recognize that a dangerous situation is about to
occur" (arXiv:2503.03848). It is the **second-highest** of several annotators' answers, not their median, chosen to
bias the label toward shorter alert-to-accident intervals.

## Headline (scoring A, the shipped detector)

| subset | coverage | median abs | IQR abs | signed mean / median | signed stdev | within 1 s / 2 s | bucket |
|---|---|---|---|---|---|---|---|
| **new clips (out of sample)** | 234/360 (65%) | **0.88 s** | 0.40–2.02 s | −0.99 / −0.27 s | **2.09 s** | 52% / 75% | **Weak** |
| all 400 | 260/400 (65%) | 0.91 s | 0.42–2.04 s | −1.00 / −0.29 s | 2.11 s | 52% / 74% | **Weak** |
| original 40, re-scored | 26/40 (65%) | 1.03 s | 0.65–2.62 s | −1.09 / −0.45 s | 2.27 s | 46% / 69% | **Weak** |

**The pre-registered bucket is Weak.** The median absolute error is well inside the 2.0 s threshold, but the
spread of the signed error is just over 2.0 s. Per the pre-registration this is reported plainly as noisy, and
the median is not quoted without the spread beside it: Telltale's onset has a median error of 0.88 s from the
human label on clips it never saw, **with a signed spread of 2.09 s**.

The 360 new clips are the honest out-of-sample number. The original 40 informed the earlier diagnosis.

Coverage, the share of clips where the detector produced an onset at all, is 65%. That is above the 50% line that
would have made it a headline limitation, but it means a third of clips get no onset. See [Coverage](#coverage).

## Why the published 40-clip numbers changed

The 40-clip run was published with a median absolute error of 0.905 s and 75% coverage. Re-scored with today's
code, the same 40 clips, from the same cached SAM tracks, give 1.03 s and 65%.

Exactly one code change is responsible. Commit `bee03f6` changed how the struck vehicle is chosen. The old rule
took the **largest box at impact**. The new rule takes the largest vehicle that spent the last second **mostly
inside the ego lane**, and falls back to the largest box only when none did. It fixed a real demo-clip bug: on
cand56 the old rule chose a pickup overtaking in the next lane, close to the camera, instead of the car ahead.
It was measured on the demo tracks, not on benchmark clips. On the original 40 it scores a different vehicle on
10 clips: 7 lose their onset, 2 gain one, 1 moves.

**Scoring A (current code) is the headline, and it is the less flattering of the two.** The project owner chose it
before the full results existed, on the principle that the benchmark should measure the detector that ships.

## Both scorings, side by side

Scoring B is the code of the 40-clip run, before `bee03f6`. Re-run over the original 40 from the cached tracks, it
reproduces the published figures exactly.

| subset | scoring | coverage | median abs | IQR abs | signed mean / median | signed stdev | within 1 s / 2 s | bucket |
|---|---|---|---|---|---|---|---|---|
| new clips | **A** | 234/360 (65%) | 0.88 s | 0.40–2.02 s | −0.99 / −0.27 s | 2.09 s | 52% / 75% | Weak |
| new clips | B | 250/360 (69%) | 0.78 s | 0.33–1.69 s | −0.81 / −0.16 s | 2.01 s | 56% / 78% | Weak |
| all 400 | **A** | 260/400 (65%) | 0.91 s | 0.42–2.04 s | −1.00 / −0.29 s | 2.11 s | 52% / 74% | Weak |
| all 400 | B | 280/400 (70%) | 0.83 s | 0.34–1.69 s | −0.81 / −0.18 s | 2.0001 s | 56% / 78% | Weak, on the line |
| original 40 | **A** | 26/40 (65%) | 1.03 s | 0.65–2.62 s | −1.09 / −0.45 s | 2.27 s | 46% / 69% | Weak |
| original 40 | B = published | 30/40 (75%) | 0.91 s | 0.55–1.39 s | −0.86 / −0.62 s | 1.95 s | 53% / 80% | Intermediate |

B is better on every measure. Over all 400 its spread is 2.0001 s: Weak by a ten-thousandth of a second, and
Intermediate if rounded. Buckets here use the unrounded value. The two
scorings differ only in which vehicle is called the struck one. The target-selection fix that corrects cand56
costs about five points of coverage on this benchmark. That is a real trade-off, reported rather than hidden.

## The early bias, re-examined

The 40-clip write-up offered a diagnosis: a time-to-collision under 2 s is ordinary in dense traffic, so the
`closing` test fires on everyday car-following long before anything is dangerous. **At scale, that diagnosis does
not hold.**

By the hazard test that fired, on the new clips (scoring A):

| reason | n | mean signed | median signed | stdev |
|---|---|---|---|---|
| `closing` | 106 | −0.45 s | **+0.08 s** | 1.93 s |
| `predicted` | 94 | −1.13 s | −0.45 s | 1.99 s |
| `entering` | 34 | **−2.28 s** | −1.53 s | 2.28 s |

`closing`, the test the diagnosis blamed, is the **least** biased: its median lands slightly *after* the human
alert. The early bias is carried by `entering` and `predicted`, the lane-geometry tests.

By Nexar's scene label, the "dense traffic" half does not survive either:

| scene | coverage | mean signed | median signed |
|---|---|---|---|
| Urban | 154/223 (69%) | −1.04 s | −0.23 s |
| Highway | 42/82 (51%) | −0.93 s | −0.05 s |
| Sub-urban | 26/35 (74%) | −0.91 s | −0.87 s |
| Other | 9/15 (60%) | −0.72 s | −0.23 s |

Urban and highway clips are about equally early in the mean. An interim look at n = 160 had suggested a larger
urban effect (−1.13 s against −0.49 s); it shrank with more data, which is a reason to trust the larger sample
over the smaller.

### What actually drives it: a start-of-clip tail (exploratory)

*This section is exploratory diagnosis. The 2 s cut-off was chosen after seeing the data, and nothing in it
changes the pre-registered headline.*

The mean signed error is −0.99 s but the median only −0.27 s, so the distribution is skewed: most onsets are near
the human label, with a long early tail. Splitting the 234 scored new clips by when the onset fires:

| onset fires | clips | mean signed | median signed | stdev | median abs |
|---|---|---|---|---|---|
| in the clip's first 2 s | 25 (11%) | −5.40 s | — | — | — |
| at 2 s or later | 209 (89%) | −0.46 s | **−0.03 s** | 1.48 s | 0.73 s |

No human alert in the sample comes before 3.90 s into the trimmed clip; the median is 6.63 s. So an onset in the
first 2 s cannot be agreeing with anyone. Those 25 clips split evenly across the three tests (9 `predicted`,
8 `entering`, 8 `closing`), which points at the clip boundary rather than any one rule. A vehicle already near
or in the ego lane at the first frame lets a test latch immediately.

On the other 89%, the detector's onset lands on the human label with a median offset of −0.03 s.

The obvious fix is to require that the struck vehicle first be seen *not* to be a hazard before an onset can
fire. It would have to be justified on first principles and validated on a fresh draw with its own
pre-registration. Doing it here, on these clips, would turn the project's only outside answer key into
self-assessment.

## Coverage

126 of the 360 new clips (35%) produced no onset for the struck vehicle.

| class | count |
|---|---|
| (a/b) nothing resolvable tracked: no vehicle involved, or one SAM's `--concept car` missed | 5 |
| (c) vehicles tracked and resolvable, but the struck vehicle never satisfied a hazard test | 121 |

SAM is not the coverage problem: on 121 of the 126, vehicles were plainly tracked. The hazard tests are. Coverage
is notably lower on highway clips (51%) than urban ones (69%). A plausible reason, not tested here, is that
following at highway speed rarely brings the time-to-collision under 2 s until the last moment.

## The worst clips (new, scoring A)

| clip | signed error | onset | human alert | test | scene |
|---|---|---|---|---|---|
| 00360 | −7.73 s | 0.17 s | 7.90 s | `closing` | Urban |
| 00177 | −6.87 s | 0.53 s | 7.40 s | `entering` | Urban |
| 00961 | −6.23 s | 0.70 s | 6.93 s | `predicted` | Urban |
| 00135 | −6.20 s | 1.57 s | 7.77 s | `predicted` | Urban |
| 00302 | −6.13 s | 0.30 s | 6.43 s | `entering` | Urban |

All five fire within the first 1.6 s of the clip: the start-of-clip tail above.

## What was not done

- No threshold, polygon, detector or scoring rule was changed in response to any of these results.
- No clip was dropped. Clips with no onset count against coverage.
- The run was not extended or stopped because of the results. It ended on its pre-registered stall rule, at a
  budget cap set in advance.

## Reproducing these numbers

The SAM tracks for all 400 clips are committed in `cache/sam_bench/` (about 25 MB), so the benchmark can be
re-scored without spending API credit. The trimmed videos are not committed (about 4 MB each); they are
re-downloadable from the bench manifest. `telltale video-bench --n 400` re-scores scoring A from cache. Scoring B
re-scores the same cached tracks with the target-selection and hazard code of commit `bee03f6^`; that commit's
own `video-bench` would draw a different pool, because it predates the frozen exclusions.

## Known approximation

On a near-miss there is no struck vehicle, but the code still picks one: the vehicle that was mostly in our lane
near `time_of_event`, or the largest box if none was. Nexar marks collisions and near-misses alike as positives
with no flag separating them, so the sample necessarily contains both, and on near-misses the "target" is a
stand-in for what the driver was reacting to.

## Addendum: scoring C, the collision-course test (added after the results above)

Scoring C is a third code change, made after this benchmark was run, and **it was motivated by demo-clip failures,
not by benchmark results**, as `bee03f6` was. On cand14 a taxi strikes our right side, and on cand60 an oncoming car
turns across our path; scoring A picked some small car ahead as the struck vehicle on both. Neither clip is in the
benchmark pool. The change adds a lane-agnostic test, `collision_course`: a vehicle whose time to collision from the
growth of its box *height* stays under 2 s for 9 frames while it touches the ego lane. Height, because an
edge-clipped or turning vehicle's width stops tracking its distance: on cand14 the taxi's box is clipped at the
right edge from 6.98 s and its width stops growing, while its height keeps growing until impact. An overtaking
vehicle alongside (cand56's pickup) is the opposite case: its width grows as more of it slides into view, while its
height stays flat. The classic constant-bearing rule (a vehicle whose bearing holds steady while it grows is on a
collision course) was tried and rejected. It assumes a point-sized ego vehicle; on a wide car a side impact does
not hold a constant bearing, and the taxi's bearing drifted outward all the way to impact. The test is used twice:

- **Struck vehicle:** a vehicle also qualifies if it was on a collision course at any point in the 2 s before
  impact, beside the "last second mostly in our lane" rule of `bee03f6`. cand56 still picks the car ahead (3);
  cand14 now picks the taxi (4); cand60 the turning car (2).
- **Hazard onset:** `collision_course` is a fallback reason, used only for a vehicle that no lane test
  (entering, predicted, closing) flags. Making it an equal reason, earliest wins, was tried and rejected: it moved
  the onset *earlier* on three of the four demo clips (cand36, 37, 38), which would have invalidated their
  committed live runs, and earlier onsets would also worsen the detector's existing early bias against the human
  labels (see [The early bias, re-examined](#the-early-bias-re-examined)). On the four demo
  clips the struck vehicle, onset time and reason are unchanged, and a test pins that.

**The headline stays scoring A.** C is reported as a new row; nothing above was re-scored or rewritten.

| subset | scoring | coverage | median abs | IQR abs | signed mean / median | signed stdev | within 1 s / 2 s | bucket |
|---|---|---|---|---|---|---|---|---|
| new clips | **A** | 234/360 (65%) | 0.88 s | 0.40–2.02 s | −0.99 / −0.27 s | 2.09 s | 52% / 75% | Weak |
| new clips | B | 250/360 (69%) | 0.78 s | 0.33–1.69 s | −0.81 / −0.16 s | 2.01 s | 56% / 78% | Weak |
| new clips | C | 250/360 (69%) | 0.89 s | 0.36–1.84 s | −0.93 / −0.26 s | 2.01 s | 53% / 76% | Weak |
| all 400 | **A** | 260/400 (65%) | 0.91 s | 0.42–2.04 s | −1.00 / −0.29 s | 2.11 s | 52% / 74% | Weak |
| all 400 | B | 280/400 (70%) | 0.83 s | 0.34–1.69 s | −0.81 / −0.18 s | 2.0001 s | 56% / 78% | Weak, on the line |
| all 400 | C | 280/400 (70%) | 0.91 s | 0.37–1.85 s | −0.94 / −0.30 s | 2.01 s | 52% / 76% | Weak |
| original 40 | **A** | 26/40 (65%) | 1.03 s | 0.65–2.62 s | −1.09 / −0.45 s | 2.27 s | 46% / 69% | Weak |
| original 40 | C | 30/40 (75%) | 0.97 s | 0.55–1.80 s | −1.01 / −0.61 s | 2.03 s | 50% / 77% | Weak |

C wins back B's coverage (70% of all 400) while keeping the cand56 fix, and its spread is slightly tighter than A's.
Its median error is no better than A's; the bucket is still Weak. 47 clips score differently from A, 13 of them
through a `collision_course` onset. A target-selection-only variant (no new hazard reason) reaches 66.7% coverage
over all 400, so most of the gain comes from the fallback onset.

## Addendum: suggesting the impact time for an uploaded clip

An uploaded clip has no labelled event time. `telltale.video.impact.suggest_impact_time(video_path=None,
tracks=None)` returns a deterministic suggestion in seconds, for the person uploading to confirm or correct: the
frame of the largest camera jolt (mean grey-level change between consecutive frames) when a video is given,
otherwise the frame where any tracked vehicle's box is tallest.

Every trimmed benchmark clip has its event at exactly 8.0 s, so scoring on whole clips would reward any method
that leans late. Each clip was therefore cut to a random window containing the event (start uniform in 0–6 s, end
uniform in 8.3–9.5 s, seed 7), and the suggestion scored against Nexar's `time_of_event` inside that window.

| method (400 clips) | within 0.5 s | within 1 s | median abs error |
|---|---|---|---|
| camera jolt (used for a video) | 54.5% | 67.2% | 0.43 s |
| tallest box (used for tracks only) | 49.2% | 65.5% | 0.53 s |
| fastest height growth | 33.5% | 54.0% | — |
| jolt nearest the tallest box | 49.5% | 65.5% | — |
| window midpoint (no information) | 1.2% | 16.2% | 2.17 s |

The jolt was chosen from these four on the same 400 clips, so its figures are mildly optimistic; there was no
held-out set. About a third of clips miss by more than 1 s, which is why the value is only ever a prefilled suggestion.
