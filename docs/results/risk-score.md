# Consequence weights for extraction errors (08 Nov 2026)

Milestone 1 committed to a consequence-weighted Risk Score after Chang et al. (2026), with the weights "derived by
perturbing gold events, like a wrong runway, a wrong type, a wrong callsign, a missed event, or a spurious event, and
observing how the engine's output changes as a result". This is that measurement.

Each perturbation edits **one** event in a recording's stored event stream and re-folds the stream through the engine.
Nothing is re-parsed and no API call is made, so this is free and reproducible: `python scripts/risk_score.py`
(`--all` for every structured arm on gold transcripts). Perturbations are deterministic.

The point of weighting is that extraction errors are not interchangeable. An error only matters if it reaches the
engine's output, and the ones that do reach it do not all cause the same harm.

## Weights, pre-registered primary arm (rules, window, gold)

Denominators: "changed the output" over all perturbations of that kind; "lost a true detection" over perturbations on
the 98 positives; "created a false alarm" over perturbations on the 309 real negatives.

| Error kind | Perturbations | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---|---|---|
| `wrong_runway` | 602 | 34% | 54% | 0% |
| `wrong_type` | 572 | 24% | 26% | 8% |
| `wrong_callsign` | 648 | 19% | 13% | 9% |
| `dropped` | 703 | 27% | 45% | 0% |
| `spurious_inuse` | 2094 | 54% | 7% | 37% |
| `spurious_other` | 2094 | 8% | 14% | 0% |

Same study on the Sonnet 5 arm's event stream, as a check that these are properties of the engine and not of one
parser's output:

| Error kind | Perturbations | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---|---|---|
| `wrong_runway` | 728 | 29% | 49% | 0% |
| `wrong_type` | 636 | 25% | 26% | 6% |
| `wrong_callsign` | 773 | 19% | 16% | 7% |
| `dropped` | 882 | 23% | 38% | 0% |
| `spurious_inuse` | 2069 | 48% | 11% | 30% |
| `spurious_other` | 2069 | 11% | 20% | 0% |

All four structured gold arms agree on the ordering and roughly on the magnitudes (`--all`), which is what we would
expect if the weight is a property of the conflict engine rather than of the extractor that fed it.

## What the weights say

**1. Most extraction errors never reach the output.** Between 19% and 34% of single-field errors change any alert at
all. A per-slot accuracy figure therefore overstates how much extraction quality matters to this system — which is the
reason Chang et al. argue for weighting in the first place, reproduced here on our own pipeline.

**2. The two extractors' characteristic errors cause opposite harms.** The rules parser's failure mode is omission
(`dropped`, and `wrong_runway` from a designator it cannot normalise): those cost recall — 45% and 54% of the ones
that land on a positive — and create a false alarm **0% of the time, on every arm**. The LLM's failure mode is
invention (`spurious`): that costs false alarms and barely touches recall. Neither error kind is "worse"; they are
harms of different kinds, which is exactly why a single scalar score would hide the result rather than express it.

**3. An invented clearance is almost harmless unless it lands on a runway already in use.** This is the sharpest
number here: a spurious landing clearance on the recording's busiest runway creates a false alarm 37% of the time,
and the same invented event on a runway the recording never uses creates one **0%** of the time. The real rate for a
given extractor sits between these bounds, set by *where* its inventions land. This explains the central tension in
the evaluation — Sonnet 5 invents 9 events on the 200 labelled instructions where the rules parser invents 0
(`extraction-pair-events.md`), yet its RUNWAY false-alarm rate is 4.9/h against the rules parser's 4.1/h, well within
the confidence interval (`conflict-eval.md`). Most of Sonnet's inventions are approach clearances read as landing
clearances, and the runways in them are mostly not the runway the tower is working. The deterministic engine absorbs
them.

**4. A hallucination can suppress a real alert, not only raise a false one.** `spurious_other` creates no false
alarms, but still loses a true detection 14% (rules stream) to 20% (Sonnet stream) of the time. The mechanism is in
`engine.apply` ([`engine.py`](../../atcdb/engine.py), "one aircraft is in one place: its old reservation is
superseded"): an invented clearance for an aircraft releases whatever reservation that aircraft actually held, so a
hallucination on an empty runway can silently cancel the reservation that a later clearance was supposed to conflict
with. This is the failure mode least visible from the outside — it produces no alert, no alarm and no trace — and it
is invisible to any metric that counts false alarms.

## Caveats

- The perturbed streams are an extractor's output, not human gold events: the pre-registered event sheets were never
  labelled (`decisions.md`, 2026-10-22). The rules parser invented 0 events on the 200 labelled instructions, so its
  stream is the closest available stand-in; running the study on the Sonnet stream as well is the check that the
  result does not depend on this choice.
- One edit at a time. Real extractors make correlated errors (an ASR digit failure corrupts the runway for every
  transmission that mentions it), and those are not modelled.
- `spurious` is modelled as an invented LAND for a callsign the engine has already heard, inserted on a transmission
  that carried no runway event. Other inventions (a spurious release, a spurious hold-short) are not modelled and
  would have different weights — a spurious release in particular should suppress alerts rather than raise them.
- Recall effects are measured on synthetic positives, so they inherit that set's phrasing bias
  (`conflict-eval.md`, caveats).
- These are rates over perturbation opportunities, not over errors an extractor actually makes. Turning them into a
  per-parser score needs the error counts from a labelled extraction set, which for now is the supplementary readback
  sheet rather than the pre-registered Level 1 sample.
