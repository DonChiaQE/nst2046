# Extraction on 200 human-labelled instructions: rules vs Haiku vs Sonnet (20 Oct 2026)

Haiku 5.5 added on 20 Oct 2026 as the live demo app's week-1 check (live demo spec, Section 8); it is not one of the
evaluation's arms.

A supplementary extraction check, not the Level 1 measure. The 200 controller instructions are the readback sheet's
(`readback_sheet_A`), which a labeller filled with each instruction's runway events instead of readback verdicts. They
are not a uniform sample and most come from approach and radar recordings, not tower. One labeller, so no kappa.
Gold transcripts, `role` context (the parser sees the speaker's role, no history). Reproduce with
`python scripts/score_pair_events.py --labels ~/Downloads/readback_sheet_A.csv` (free: every parse is cached).
Each instruction's outcome per parser, kinds and runways only, is in `extraction-pair-events-cases.csv`; join it to
`data/labels/pair_events_A.csv` on `pair_id` for the text and label (rebuild it with `--cases`).

## Runway events (what the conflict engine uses)

32 labelled runway events: 14 LAND, 9 LUAW, 8 TAKEOFF, 1 HOLD_SHORT.

| Parser | Found | Missed | Invented | Instructions exactly right (all events) |
|---|---:|---:|---:|---:|
| Rules | 30 | 2 | 0 | 189 / 200 |
| Haiku 4.5 | 31 | 1 | 7 | 128 / 200 |
| Sonnet 5 | 32 | 0 | 9 | 147 / 200 |
| Haiku 5.5 | 31 | 1 | 6 | 150 / 200 |

"Invented" counts runway events (including VACATED and unplaceable ones) with no matching label.

What each parser got wrong:
- **Rules** missed "cleared for **immediate** takeoff" (the regex wants "cleared for takeoff") and "taxi to holding point
  runway zero four", which the labeller marked as a hold-short.
- **Sonnet** turned 7 approach clearances ("cleared for ILS approach runway one three", "cleared for visual approach")
  into landing clearances, and 2 "vacate ... contact ground" instructions into vacated reports.
- **Haiku 4.5** read the same holding-point instruction as a line-up (LUAW), a re-clearance ("departure of runway three
  one") as a takeoff clearance, one ILS approach as a landing, 3 "vacate" instructions as vacated reports, and "cross
  cerno" (a waypoint) as a runway crossing it could not place.
- **Haiku 5.5** missed the same holding-point instruction as the rules parser, turned 4 approach clearances (3 ILS, 1
  visual) into landing clearances, read "cross cerno" as a crossing it could not place, as Haiku 4.5 did, and read a
  bare frequency and "good bye" as an event it could not place.

Week-1 gate for the live app: Haiku 5.5 may miss at most 2 more runway events than Sonnet (it missed 1) and invent at
most twice as many (it invented 6, Sonnet 9). **Passed**: Haiku 5.5 stays the app's Claude model. The run cost about 4
cents.

## Handoffs: do not use these numbers

Claude's handoff precision looks poor (Sonnet 37 found, 44 invented), but the labeller marked only 36 of the 92 "contact
<frequency>" instructions as handoffs, so most "invented" handoffs are missing labels.

## Reading this honestly

- The rules parser is more precise and the LLMs find slightly more, which is the trade-off the project asks about.
  With 32 runway events, the recall difference is 2 events and means little on its own.
- Sonnet's 7 false landings come from approach clearances, which are mostly an approach-frequency phrase. On tower
  recordings they should be rarer, but the pattern matters: the model fills in the next step it expects ("approach"
  becomes "land"). That is the hallucination mechanism the report should discuss.
- The Level 1 sheet (`scripts/make_event_sheet.py`: 200 tower transmissions, blind, 50 rows labelled by both) is still
  the proper measure.
