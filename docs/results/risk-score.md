# Consequence weights for extraction errors (08 Nov 2026)

Milestone 1 committed to a consequence-weighted Risk Score after Chang et al. (2026), with the weights "derived by
perturbing gold events, like a wrong runway, a wrong type, a wrong callsign, a missed event, or a spurious event, and
observing how the engine's output changes as a result". This is that measurement.

What this measures is the **engine's sensitivity** to each class of extraction error -- not a score attached to an
alert, and not a per-parser score (see the last caveat). Read it as: if an extractor makes this kind of mistake, how
often does the mistake reach the engine's output, and what does it do when it gets there.

Each perturbation edits **one** event in a recording's stored event stream and re-folds the stream through the engine.
Nothing is re-parsed and no API call is made, so this is free and reproducible: `python scripts/risk_score.py`
(`--all` for every structured arm on gold transcripts). Perturbations are deterministic.

The point of weighting is that extraction errors are not interchangeable. An error only matters if it reaches the
engine's output, and the ones that do reach it do not all cause the same harm.

> **Re-run 08 Nov 2026 after the strip fix.** The engine now treats the two ends of one strip (13 and 31) as one
> runway (`atcdb/engine.py`, `OPPOSITE_MATRIX`). `wrong_runway` and `spurious_other` both move an event to the other end
> of the same strip, so those two rows changed; the other four are unchanged on the rules arm and move by at most one
> point on Sonnet's. The tables below are the re-run.
>
> - **Still holds:** finding 1, and finding 2 for `dropped` (it costs recall, 38 to 45%, and never raises a false alarm).
> - **No longer holds:** `wrong_runway` now raises a false alarm 5 to 6% of the time and loses a true detection 25 to
>   27% (it was 0% and 49 to 54%), so it is not an omission-like error. Finding 3's 0% floor was the blind spot itself:
>   an invented landing on the other end of a working strip raises a false alarm 49 to 61% of the time, more than one on
>   the busiest end, because two landings from opposite ends are head-on. On a corpus of one strip there is no unused
>   runway for an invention to land on harmlessly.
> - **Survives, smaller:** finding 4 holds through `spurious_inuse` only, at 7 to 11%. `spurious_other` now loses no
>   detection, because the invented reservation sits on the same strip and still conflicts with the later clearance.
>
> A follow-up fix on 08 Nov 2026 made a hold-short release a clearance held from the strip's other end, so
> release matches the detection rule above; that moved `spurious_other`'s false-alarm rate on the rules
> stream from 62% to 61% and nothing else (the Sonnet stream is unchanged).
>
> The prose under "What the weights say" was rewritten against these tables on 08 Nov 2026. The three
> bullets above are kept as the record of what the strip fix changed and why.

## Weights, pre-registered primary arm (rules, window, gold)

Denominators: "changed the output" over all perturbations of that kind; "lost a true detection" over perturbations on
the 98 positives; "created a false alarm" over perturbations on the 309 real negatives.

| Error kind | Perturbations | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---|---|---|
| `wrong_runway` | 602 | 23% | 27% | 6% |
| `wrong_type` | 572 | 24% | 26% | 8% |
| `wrong_callsign` | 648 | 19% | 13% | 9% |
| `dropped` | 703 | 27% | 45% | 0% |
| `spurious_inuse` | 2094 | 54% | 7% | 37% |
| `spurious_other` | 2094 | 71% | 0% | 61% |

Same study on the Sonnet 5 arm's event stream, as a check that these are properties of the engine and not of one
parser's output:

| Error kind | Perturbations | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---|---|---|
| `wrong_runway` | 728 | 21% | 25% | 5% |
| `wrong_type` | 636 | 25% | 26% | 6% |
| `wrong_callsign` | 773 | 20% | 16% | 7% |
| `dropped` | 882 | 23% | 38% | 0% |
| `spurious_inuse` | 2069 | 48% | 11% | 30% |
| `spurious_other` | 2069 | 60% | 0% | 49% |

All five structured gold arms (`--all`: rules in none, role and window context, plus Haiku 5.5 and Sonnet 5) agree
on which error kinds sit at the top and bottom of the ordering, which is what we would expect if the weight is mostly
a property of the conflict engine rather than of the extractor that fed it. They do **not** agree on magnitude: the
context-free rules arm is the clear dissenter, putting `wrong_runway`'s lost-detection rate at 33% against 49 to 54%
elsewhere and `spurious_other`'s at 34% against 13 to 14%, and it inverts the false-alarm ordering of `wrong_type` and
`wrong_callsign`. Read the ordering as the robust part and the percentages as specific to the arm named above each
table.

## What the weights say

**1. Field-level errors rarely reach the output; invented events usually do.** Getting one field wrong on an event
that is otherwise right -- the runway, the type, the callsign -- changes an alert only 19 to 25% of the time. Inventing
an event that was never said changes one 48 to 71% of the time. So a per-slot accuracy figure overstates how much
field-level transcription quality matters to this system, which is Chang et al.'s argument for weighting, reproduced
here on our own pipeline -- but it understates how much *not inventing things* matters. Those are the two halves of
"extraction quality" and this engine weights them very differently.

**2. Omission and invention cause opposite harms, and only omission is now clean.** `dropped` is the pure omission:
it costs recall (38 to 45% of the perturbations that land on a positive) and raises a false alarm **0% of the time, on
every arm**. Invention is the mirror image: `spurious_other` loses no true detection at all (0%) and raises a false
alarm 49 to 61% of the time. Neither is "worse" -- they are harms of different kinds, which is why a single scalar
score would hide this result rather than express it. What no longer holds is treating `wrong_runway` as omission-like:
since the engine relates the two ends of a strip, a misread designator can land on the same tarmac and conflict, so it
now both loses detections (25 to 27%) and raises false alarms (5 to 6%).

**3. An invented clearance is most dangerous on the *other* end of a working strip.** This is the sharpest number
here, and it reverses the pre-fix reading. A spurious landing clearance on the recording's busiest runway creates a
false alarm 30 to 37% of the time; the same invented event on a runway the recording "never uses" creates one 49 to
61% of the time -- more, not less. On a corpus with one active strip there is no harmlessly unused runway: the other
designator is the reciprocal end, and two landings from opposite ends are head-on, so `OPPOSITE_MATRIX` rates the pair
`alert` where the same-direction pair is legal. `spurious_other` is accordingly the single most consequential
perturbation in the study, changing the output 60 to 71% of the time.

This removes the mechanism that previously explained the central tension in the evaluation. Sonnet 5 invents 9 runway
events on the 200 labelled instructions where the rules parser invents 0 (`extraction-pair-events.md`, which counts
runway events; the rules parser also produced 3 unlabelled `HANDOFF`s, and that sheet notes only 36 of 92 "contact
&lt;frequency&gt;" instructions were labelled as handoffs). The pre-fix argument was that most of Sonnet's inventions are
approach clearances read as landing clearances on runways the tower is not working, which the engine absorbed
harmlessly. Post-fix the engine no longer absorbs them, so that explanation cannot be reused. The measured RUNWAY
false-alarm comparison is pending re-adjudication of the alerts the strip fix newly raises (`conflict-eval.md`), and
this paragraph should not be cited until it is.

**4. A hallucination can suppress a real alert, not only raise one.** `spurious_inuse` still loses a true detection
7% (rules stream) to 11% (Sonnet stream) of the time. The mechanism is in `engine.apply`
([`engine.py`](../../atcdb/engine.py), "one aircraft is in one place: its old reservation is superseded"): an invented
clearance for an aircraft releases whatever reservation that aircraft actually held, so a hallucination can silently
cancel the reservation a later clearance was supposed to conflict with. This is the failure mode least visible from
the outside -- no alert, no alarm, no trace -- and it is invisible to any metric that counts false alarms. It no
longer appears under `spurious_other`, whose invented reservation now sits on the same strip and still conflicts with
the later clearance, so suppression is specific to inventions that land on the runway already in use.

## Caveats

- The perturbed streams are an extractor's output, not human gold events, and no labelled stream could have been
  substituted. The pre-registered Level 1 event sheets were never labelled (`decisions.md`, 2026-10-22), and the 200
  labelled instructions that do exist (`data/labels/pair_events_A.csv`) are a per-transmission sample rather than
  labelled recordings: 183 of their 191 recordings carry exactly one labelled transmission, only 20 of the 407 scored
  recordings appear among them at all, none of the labelled transmissions is an injection trigger, and they have no
  second annotator (the kappa of 0.80 in `conflict-eval.md` is for alert verdicts, not for events). A consequence
  study has to fold a whole recording through the engine to see a conflict appear or vanish, which a single labelled
  line inside an otherwise unlabelled recording cannot support. What those labels do establish is that the rules
  parser invented 0 *runway* events across all 200 instructions (it produced 3 `HANDOFF`s with no
  matching label, which that sheet attributes to unlabelled handoffs rather than to invention), so its stream is the closest available stand-in. The real
  check, though, is that this measures a property of **the engine** rather than of one parser: the study repeated on
  the Sonnet stream, and on all four structured gold arms, agrees on the ordering and roughly on the magnitudes.
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
