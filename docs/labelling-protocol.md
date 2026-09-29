# Human labelling protocol

Where human judgement enters the evaluation, what each person does, and how agreement is measured.
Two labellers: Don and Jennifer. Every sheet has an A (full) and a B (overlap) copy; B is labelled
blind to A. Agreement is Cohen's kappa via `scripts/score_agreement.py`. Disagreements are resolved
by discussion and the resolution is written into the decision log with the reason.

Course requirement this serves: "verifies AI-assisted work, documents consequential decisions,
preserves useful evidence" (rubric, 10%) and "analyses failures, uncertainty and limitations"
(evaluation, 10%). No number in the report comes from a parser or model alone.

## Touchpoints

| # | Task | Sheet | Labels | Size | Feeds |
|---|---|---|---|---|---|
| H1 | Compatibility-matrix sign-off | decision log entry, not a sheet | severity per cell, with reason | 16 cells + releases | Engine (level 1) |
| H2 | ASRS incident triage | `asrs_triage_{A,B}.csv` | space, comm_trace, convertible | ~100, overlap 25 | Scope argument; seed list for H3 |
| H3 | ASRS sequence reconstruction | `asrs_sequences/<acn>.csv` + `_B` fidelity check | per-sequence: faithful yes/no | 10-20 sequences | Conflict detection (level 3), real-pattern column |
| H4 | Event labelling of tower transmissions | `event_sheet_{A,B}.csv` | true events per transmission | ~200, overlap 50 | Parser accuracy (level 2); regression fixture |
| H5 | Alert adjudication | `alert_sheet_{A,B}.csv` | true / false / ambiguous per raised conflict | all alerts on the tower replay set | False-alarm rate (level 3) |
| H6 | Readback sheets (existing) | `readback_sheet_{A,B}.csv` | consistent / inconsistent / cant_tell | 200 + 50 | Readback conflict type; lower priority than H4 |

Order of priority if time runs short: H1, H4, H5, H2, H3, H6. H1 is an hour; H4 is the one that
sets the ceiling on everything downstream.

## Definitions

### H2 — ASRS triage (`scripts/make_asrs_triage_sheet.py`)

- `space`: where the conflict or deviation manifested. `runway` (any aircraft or vehicle on or
  crossing a runway without the right to be there, or two conflicting runway clearances);
  `taxiway` (conflict confined to taxiways / apron); `airborne` (loss of separation in the air);
  `other` (e.g. wrong airport, phraseology confusion with no movement consequence).
- `comm_trace`: would the problem have been audible on frequency *before* the movement? `wrong_readback`
  (the readback did not match the clearance); `query` (someone asked "confirm"/"say again");
  `correction` (a party corrected themselves or the other); `none` (readback correct, nothing said);
  `cant_tell` (narrative does not say).
- `convertible`: `yes` if the narrative quotes or closely paraphrases the actual clearances, in order,
  so a transmission sequence could be written down; otherwise `no`.

Output numbers for the report: share of `space == runway` among communication-attributed reports;
share of pilot-deviation reports with `comm_trace != none`.

### H3 — Sequence reconstruction

For each `convertible == yes` ACN, one labeller writes `data/labels/asrs_sequences/<acn>.csv` with
columns `seq, speaker_role, text` in ATC phraseology as the narrative describes it, plus the expected
conflict (`expected_type, expected_runway, expected_at_seq`). The other labeller reads the narrative
and the sequence and marks `faithful: yes | no` with a note. Only `faithful == yes` sequences enter
the evaluation. These are labelled *synthetic, ASRS-derived* in every table (course ethics rule:
label synthetic media).

### H4 — Event labelling (`scripts/make_event_sheet.py`, to be written; mirrors `make_label_sheet.py`)

Sample ~200 Tower transmissions by transmission, not by parser output, stratified by speaker role.
The rules parser's output is **not shown**. The labeller writes the true events in a compact form,
one per line, e.g. `LAND SWR124 14`, `CROSS DLH5ME 28`, `HANDOFF SWR124 ground`, `READBACK`, `NONE`.
Unclear callsign: `?`. This sheet becomes `tests/fixtures/event_gold.csv` and a test asserts the
rules parser's score on it never drops (regression), so the human labels are wired into CI.

### H5 — Alert adjudication (`scripts/make_alert_sheet.py`, to be written)

Every conflict raised by the engine on the unperturbed tower replay set, with the transmissions up to
that point and the explanation string. Label `true` (a real contradiction on frequency), `false`
(legal / anticipated separation / stale reservation / parser error), `ambiguous`, and a `cause` for
false alarms: `anticipated_separation | missed_release | parser_error | asr_error | other`. This is
the false-alarm rate and the failure taxonomy in one pass.

## Agreement

- Cohen's kappa per label column, on the overlap rows, computed by `atcdb.agreement.cohen_kappa`.
- Blank rows are excluded before kappa (`paired_labels`). `cant_tell` / `ambiguous` are real labels,
  not blanks: two people agreeing that something is undecidable is agreement.
- Report kappa with n. Conventional reading: < 0.4 poor, 0.4-0.6 moderate, 0.6-0.8 substantial,
  > 0.8 near-perfect. Below 0.6 on any sheet triggers a definitions review before the full sheet is
  labelled.

## Logging

Each labelling session gets a decision-log line: date, sheet, rows done, kappa if overlap complete,
any definition change. Definition changes invalidate earlier rows on that column; re-label them.
