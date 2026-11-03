# Cut-in screening — shortlist for the hero demo clip

Our three validated demo clips (cand36, cand37, cand38) all come out as `closing` — rear-ends. A true
cut-in, where a car crosses into the ego lane, is the most legible version of the story for a viewer, so
this screens the remaining candidates for one.

Muse Spark was asked one question per clip, with the distinction that tripped up earlier triage made
explicit: *"A vehicle that was already ahead in the same lane the whole time does not count."* Answers are
cached under `cache/cut_in/`, so re-running costs nothing.

**This selects demo clips only.** It never touched the A5 benchmark pool, and no screening answer is ever
evidence — the model narrows 59 clips to a handful, and a human confirms by eye.

## Result

59 clips screened (all 64 candidates less cand36/37/38, already `closing` in our own geometry, and
cand01/cand06, already settled by eye). No API or parse failures.

| answer | count |
|---|---|
| no | 38 |
| **yes** | **20** |
| unclear | 1 |

Impact is at 8.00 s in every clip by construction — they are trimmed to `[event − 8 s, event + 1.5 s]`.
"Lead" is how long before impact the cut-in begins, which is the window an ADAS latency story has to live in.

## Ranked shortlist — daylight, high confidence, usable lead

Best first. A lead of roughly 1.5–3.5 s is the sweet spot: long enough for a perception-or-braking story,
short enough that the cut-in is plainly the triggering event.

| clip | nexar | cut-in | lead | brightness | note |
|---|---|---|---|---|---|
| **cand45** | 00702 | 5.00 s | **+3.00 s** | 88 | longest usable lead in daylight |
| **cand14** | 00981 | 5.50 s | **+2.50 s** | 115 | NYC taxi cutting in from the right; flagged in earlier triage too |
| **cand15** | 00997 | 6.00 s | +2.00 s | 117 | brightest of the shortlist |
| **cand35** | 00900 | 6.00 s | +2.00 s | 118 | earlier triage: "black SUV pulls out from the right" |
| cand30 | 00661 | 6.50 s | +1.50 s | 90 | |
| cand19 | 00966 | 6.50 s | +1.50 s | 77 | earlier triage: SUV cuts left then stops under an overpass |
| cand48 | 00110 | 3.00 s | +5.00 s | 79 | lead may be too long — the cut-in may not be the trigger |
| cand52 | 01024 | 7.00 s | +1.00 s | 132 | short lead; little room for a latency story |

Previews for all eight are in `cache/previews/<clip>.png`; the clips are `data/clips/<clip>.mp4`.

## Screened out, and why

- **cand41** (00343): cut-in reported at **8.50 s**, *after* the 8.00 s impact. Rejected.
- **cand56** (00190): 7.80 s, a 0.20 s lead — effectively simultaneous with impact.
- **cand09** (00109, lead +6.50 s), **cand20** (00621, +6.50 s), **cand12** (00733, +5.50 s): the reported
  cut-in is so far ahead of impact that it is probably an earlier, unrelated manoeuvre rather than the
  triggering event. cand12 was already judged a near-miss by eye.
- **Night** (brightness < 70): cand22, cand07, cand46, cand23, cand63, cand54, cand29. Not disqualifying —
  our own measurements found SAM tracks night clips *better* than day — but a hero clip for judges wants
  visible lane markings.

## What happens next

A human watches the shortlist and confirms one or two. Then those clips get SAM, the witness, a tuned
`ego_lane_polygon`, and a check that `compute_video_facts` returns `hazard_onset_reason` of `entering` or
`predicted`.

If a confirmed clip still comes back `closing`, that is reported rather than worked around: it would mean
the manoeuvre a human sees as a cut-in does not cross our lane geometry, which is exactly what happened
with cand38 and is worth knowing.
