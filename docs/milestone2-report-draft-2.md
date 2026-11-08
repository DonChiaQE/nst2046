# Does an LLM extractor change what a runway-conflict alerting system catches, misses, and can account for?

**NST2046 Milestone 2 — draft 2, 2026-11-08.** All eight sections, with appendices A–H. File references point to
this repo so each claim can be checked against its source; Appendix H gives the command that regenerates every
table.

---

## 1. Question and claim

On 22 March 2026 at LaGuardia Airport, air traffic control cleared Air Canada Express 8646, a CRJ900, to land on
runway 4. Two minutes later, with the aircraft about a quarter-mile out, the same controller cleared "Truck 1 and
company" to cross that runway. The aircraft struck the truck on landing, killing both pilots (NTSB, 2026, DCA26MA161).
The two clearances were individually unremarkable and jointly incompatible — the kind of error this project's system
is built to catch. Contradictory ATC clearances are a known precursor to runway incursions: controller actions accounted for
17.9% of the 1,758 US runway incursions recorded in fiscal year 2024, and for 10 of the 17 most severe
(Category A) incursions since the start of fiscal year 2022 — a majority of them (DOT OIG, 2025, fig. 3 p. 5
and exhibit D pp. 36–37). LaGuardia's surface radar,
ASDE-X, did not alert that night, because the fire truck carried no transponder for it to track, and the two
controllers on duty were covering four positions.

**Question.** We ask whether a conflict-detection system built on ATC radio audio can catch a contradictory pair of
clearances like this one, and specifically whether the choice of extractor — a rules-based parser or a large
language model — changes what it catches, what it misses, and what kind of errors it makes. We compare the two
extractors on recall and false-alarm rate for tower-frequency traffic, and identify the mechanism behind cases where
they disagree.

**Hypothesis.** We expected the LLM to outperform the rules-based extractor at identifying genuine conflicts, at the
cost of a somewhat higher false-alarm rate from hallucinated events.

**Claim.** On human transcripts, the two extractors are statistically indistinguishable on both recall and false
alarms: a 3-point recall gap and a 0.8-per-hour false-alarm gap, with 95% confidence intervals that include zero
(§4.2). Under transcription noise, recall stays indistinguishable but the LLM raises significantly more false alarms
— the only interval in the study that excludes zero. This supports the direction of our hypothesis but not its
size: at the level of individual transmissions, the LLM extracts more correctly and hallucinates far more often than
the aggregate numbers suggest (§4.1), and most of that divergence is absorbed by the engine before it reaches an
alert (§4.3, §5). The claim is therefore about where in the pipeline the difference between the two extractors shows
up, not only whether one outperforms the other.

---

## 2. Technical explanation

The system is a three-stage pipeline. A transcriber turns audio into text. An extractor turns each line of text into
zero or more typed events. A deterministic conflict engine folds those events into per-runway reservation state and
raises an alert when two reservations are incompatible. Only the extractor stage is varied between a rules-based
parser and a large language model; the transcriber and the engine are identical in every condition, so any
difference in system output is attributable to extraction.

```
audio clip → transcriber → transcript text → extractor (rules | LLM) → typed event → engine (reservation state) → alert
```

**[FIGURE 1 — placeholder]** Pipeline diagram: transcriber, extractor (forked into rules/LLM), engine, alert, with
one worked example (recording 528: "cleared to cross 13" → `ClearToCross` → reservation on 13 → "cleared to land 13"
→ `ClearToLand` → `RUNWAY` alert).

### 2.1 Transcriber

The transcriber is `faster-whisper`'s `whisper-medium.en-atc`, a Whisper model fine-tuned on air-traffic-control
audio (`atcdb/asr.py`). It takes one audio clip per transmission and returns text, normalized to the same convention
as the human gold transcripts: lower case, digits spelled out one at a time, no punctuation. Scored against the
gold transcripts on 2,927 transmissions, it reaches 13.0% word error rate overall — 7.2% on controller speech and
18.4% on pilot speech ([`wer-baseline.md`](results/wer-baseline.md)). The fine-tuning set overlaps with 80% of the
recordings used in this study, so this WER understates error on genuinely unseen audio (§7).

### 2.2 Extractor

Both extractors take one transmission's text, an optional context window, and the speaker's role, and return a list
of events against the shared `Event` schema (`atcdb/engine.py`). Each event has four fields: `kind`, one of ten
event types — `LAND`, `TAKEOFF`, `LUAW`, `CROSS`, `HOLD_SHORT`, `HANDOFF`, `READBACK`, `VACATED`, `GO_AROUND`,
`NOOP`; `callsign`; `runway`; and `to`, the handoff target. This is a deliberately narrow interface: the extractor
reads one line and fills four slots per event; it cannot see the conflict matrix, hold state across calls, or raise
an alert itself. Context comes in three modes: `none` is the line alone, `role` adds the speaker's role, and
`window` adds the last four transmissions plus the callsigns and runways the engine is currently tracking.

#### 2.2.1 Rules-based parser

The rules parser (`atcdb/parse_rules.py`) matches normalized text against a fixed set of regular expressions — one
phrase pattern per event kind, a handoff-target pattern, and a go-around pattern (full set, Appendix B0) — frozen
before any evaluation was run. A runway designator comes directly from the matched phrase for `CROSS`/`HOLD_SHORT`;
for `LAND`/`TAKEOFF`/`LUAW`, whose own pattern names no runway, it is the nearest `runway ...` mention in the
transmission, falling back under `window` context to the single runway currently active (Appendix B4). A callsign
is read by a positional heuristic around the matched phrase (Appendix B0) rather than by modelling which aircraft
the transmission is about, and can come back blank — the mechanism behind most of §4.3's divergent cases.

#### 2.2.2 LLM

The LLM extractor calls Claude (Sonnet 5 or Haiku 5.5) once per transmission with a forced tool call,
`report_events`, against the shared event schema (`atcdb/parse_llm.py`; prompt and schema verbatim, Appendix C).
Both models run with extended thinking disabled and reasoning effort set to low; neither accepts a `temperature`
parameter, so determinism is not available at the API level — reproducibility instead comes from caching every
parse against this exact prompt and schema, keyed by model, context mode, and transcript kind.

The rules parser and the LLM differ in what kind of operation they perform, not only in accuracy. The rules parser
matches a closed, enumerated vocabulary: a fixed set of clearance verbs, callsign shapes, and the literal word
"runway" before a designator. Anything outside that enumeration produces nothing. The LLM instead scores the most
probable completion of the output schema given the text and whatever context it was shown, over an open vocabulary.
That is why it generalises to phrasing nobody enumerated, and it is the same reason it will supply a plausible value
where the text supports none: the operation is "what most likely goes in this slot," not "does this line license
this slot." This distinction is the mechanism behind every divergence reported in §4.

### 2.3 Deterministic conflict engine

The engine (`atcdb/engine.py`) is a pure state fold: each event is applied to a frozen `State` object representing,
per runway, the reservations currently open and their timestamps, and per aircraft, whether it is holding short.
Four event kinds open a reservation — `LAND`, `TAKEOFF`, `LUAW`, `CROSS` — each valid for 300 seconds before it is
discarded as stale. `HANDOFF`, `VACATED`, and certain `HOLD_SHORT` transitions release reservations; `READBACK` and
`NOOP` carry no engine state.

When a new reservation-opening event arrives on a runway that already has an open reservation, the engine looks up
the pair of kinds in a fixed compatibility matrix (e.g. `LAND`×`TAKEOFF` = `alert`, `TAKEOFF`×`TAKEOFF` = `warning`,
with a second matrix, `OPPOSITE_MATRIX`, applied when the reservation is held from the other end of the same strip,
where two landings or two departures are head-on and so `alert` rather than legal,
`CROSS`×`CROSS` = `ok`) and raises a `RUNWAY` conflict at the resulting severity. If either event's callsign is
unknown, the severity is capped at `warning` regardless of what the matrix says, on the deliberate ground that an
unidentified aircraft might be the aircraft already holding the reservation. A second alert type, `READBACK`, fires
when a pilot's readback does not match the instruction it responds to; this study reports but does not adjudicate
`READBACK` alerts (§3.3.2).

The engine is identical across every arm in this study. The only input that varies is the event stream it is folded
over, which is why a difference in system output can be attributed to the extractor stage rather than to anything
downstream of it.

**Framing boundary.** The engine detects incompatible *clearances* as a proxy for loss of separation on the runway
surface — not loss of separation itself, and not compliance with ICAO Doc 4444. A system alert means two aircraft
hold clearances the matrix marks incompatible; it does not mean two aircraft were physically close. §4.5 shows two
real 2026 incidents that fall outside this proxy entirely.

---

## 3. Method and reproducibility

### 3.1 Data

The corpus has three parts. **309 real tower recordings** (the negatives) come from two public research corpora,
ATCO2 and UWB-ATCC; every recording is tower-frequency only, so ground, apron, and vehicle-frequency traffic — such
as the truck crossing in the opening incident — is invisible to the engine by construction. **98 synthetic
positives** are real transmission sequences edited or spliced so that a later clearance conflicts with an earlier
one (§3.3.1); genuine conflicts are near-absent in routine recorded traffic, so recall has to be measured against
constructed ones. **200 human-labelled controller instructions**, drawn from an existing readback-labelling sheet and
labelled blind to every extractor's output, support the extraction-level measure in §4.1; this substitutes for a
purpose-built, tower-only labelling sheet that was prepared but not completed in time (§7). Five real incidents —
Austin 2023 (NTSB DCA23FA149), JFK 2023 (NTSB DCA23LA125), Prague (recording 528), and two 2026 reconstructions
from published reporting (Goa and Houston) — are used as case studies in §4.5, reported without a rate because n is
too small to support one.

### 3.2 Variations tested

Every run is specified by an **arm**: a choice of parser, model, context mode, and transcript kind
(`atcdb/evaluate.py`, `Arm`). Only the parser stage differs between arms; the transcriber and engine are held fixed.

| Dimension | Values | Note |
|---|---|---|
| Parser | `rule`, `llm`, `judge` | `judge` removes the parser *and* the engine — an ablation, §4.4 |
| Model | rules v3, Claude Sonnet 5, Claude Haiku 5.5 | one forced tool call per transmission, extended thinking disabled, effort low |
| Context | `none`, `role`, `window` (`sequence` for the judge) | nothing beyond the line / plus speaker role / plus the last 4 transmissions and tracked state |
| Transcript | `gold`, `asr` | human transcript, or the fine-tuned Whisper output (§2.1) |

The primary, pre-registered comparison is rules vs. Sonnet 5 at `window` context on gold transcripts, with the same
pair on ASR transcripts as a registered secondary comparison. Haiku 5.5, the context sweep, and the judge ablation
are secondary analyses. Fixing the primary comparison before any paid evaluation was run is what prevents the
reported result from being selected after the fact out of 18 possible arms.

### 3.3 Evaluation

Four separate evaluations are run on this data, each scoring a different unit against a different reference:

| | What is scored | Against what | Measure |
|---|---|---|---|
| Level 1 — extraction | one transmission | 200 labelled instructions | events found / missed / invented |
| Level 2 — end to end | a whole recording | 98 positives, 309 negatives | lenient & strict recall; adjudicated false alarms/hour |
| Ablation — LLM judge | a whole recording | the same Level 2 sets | the same two measures |
| Consequence weighting | one perturbed event | an arm's own stored event stream | P(output changes), P(detection lost), P(false alarm created) |

Level 1 measures whether the extractor read a line correctly; Level 2 measures whether the whole system raised the
right alert. The two are not interchangeable, and the gap between them is itself part of the result (§4.3, §5). The
consequence-weighting evaluation exists to explain that gap by measuring, directly, how often a single extraction
error survives the engine at all.

#### 3.3.1 Generation of test cases

Genuine conflicts are too rare in recorded routine traffic to measure recall against, so positives were constructed.
A keyword scan over the 309 recordings' gold text — deliberately broader than the rules parser's own patterns —
locates candidate clearance *sites*: an **anchor**, a clearance that opens a reservation, and later, on the same
runway, a **trigger**, a second clearance that would conflict with it. A seeded generator (`atcdb/inject.py`) then
builds one of five edit kinds at each site pair: `runway_swap` (the trigger's runway is replaced with the anchor's),
`holdshort_to_cross` (a hold-short becomes a crossing clearance), `verb_upgrade` (a line-up or landing clearance
becomes a takeoff clearance), `release_delete` (a release between anchor and trigger is deleted), and `splice` (no
text is edited at all — one recording that ends with an open reservation is joined to a second real recording from
the same airport whose own clearance conflicts with it). These edit kinds mirror the structure of real
contradictory-clearance incidents such as the one in §1: two individually valid instructions that, taken together,
assign the same runway to two aircraft. 92 of the 98 accepted cases are splices, so the audio and its transcript
remain unedited in the large majority of positives; only the sequencing of two real recordings is constructed.

The generator and the validator for these cases are different people. One team member's generator produced 100
candidate sequences; a second team member checked every one blind — without seeing any extractor's output — against
three written criteria: different aircraft, a genuinely incompatible use of the same runway, and plausible
phraseology. 98 were accepted and 2 rejected as implausible; only accepted cases were scored
([`data/labels/README.md`](../data/labels/README.md) §2). Separately, a 200-row sheet of real controller
instructions was labelled for runway events, blind to extractor output, supporting the Level 1 measure (§4.1); and
two real 2026 incidents (Goa 2026-04-03, Houston 2026-04-24) were reconstructed from published incident reporting
into seven short transmissions each, used as case studies in §4.5 rather than scored for a rate
(`data/labels/real_2026_cases_A.csv`).

#### 3.3.2 Scoring

Recall is reported two ways: **lenient**, counting a recording as caught if any alert of the correct severity or
higher is raised anywhere in it, and **strict**, requiring the alert at the exact transmission the conflict was
injected at. **False alarms per hour** on the 309 negatives are counted from adjudicated alerts only: a raw `RUNWAY`
alert on a real recording is a candidate false alarm until a person judges it against the recording, using a written
four-step checklist, into one of five verdicts — `genuine`, `parse_error`, `missing_release`, `other_frequency`,
`engine_rule` (`atcdb/evaluate.py`, `VERDICTS`). Of these, only `parse_error` is a verdict the choice of extractor
can move; the other four describe what the tower-only audio channel does or does not carry, or how the engine's
compatibility matrix is defined, independent of extraction quality. Inter-rater agreement on 31 alerts labelled by
both adjudicators was Cohen's κ = 0.80 with the checklist, against κ = 0.12 on an earlier round without one.
`READBACK` alerts are counted but not adjudicated, so their reported rate is an upper bound.

Confidence intervals throughout are 95% percentile bootstrap intervals over recordings (2,000 resamples, seed 0);
the primary rules-vs-Sonnet comparison uses a paired bootstrap, since both arms are scored on the same recordings.
The consequence-weighting evaluation (§5) perturbs one stored event at a time in a recording's already-extracted
event stream and re-folds it through the engine, so it requires no re-parsing and no further API calls.

---

## 4. Results

### 4.1 Extraction

200 controller instructions, labelled blind to extractor output; 32 of them contain a runway event
([`extraction-pair-events.md`](results/extraction-pair-events.md), `role` context, gold transcripts):

| Parser | Found (of 32) | Missed | Invented | Instructions exactly right |
|---|---:|---:|---:|---:|
| Rules | 30 | 2 | 0 | 189 / 200 |
| Sonnet 5 | 32 | 0 | 9 | 147 / 200 |
| Haiku 5.5 | 31 | 1 | 6 | 150 / 200 |
| Haiku 4.5 | 31 | 1 | 7 | 128 / 200 |

The two extractors fail in opposite directions: the rules parser misses a small number of events and invents none;
the LLMs miss almost none and invent several. The rules parser's two misses are "cleared for *immediate* takeoff"
(the pattern expects "cleared for takeoff") and a holding-point instruction outside its vocabulary. Sonnet's nine
inventions are discussed as a mechanism in §2.2.2; seven of the nine are approach clearances ("cleared for ILS
approach runway one three") read as landing clearances.

This sheet substitutes for the pre-registered, tower-only event sheet, which was prepared but not labelled in time
(§7); it is labelled by one person, with no second rater, and is mostly approach/radar rather than tower traffic. With
32 runway events total, a two-event recall difference is not a large sample to generalise from.

### 4.2 End-to-end

98 positives, 309 negatives, 95% bootstrap confidence intervals, gold and ASR transcripts side by side:

| | Rules (window) | Sonnet 5 (window) | Paired difference, rules − Sonnet (95% CI) |
|---|---|---|---|
| **Gold transcripts** | | | |
| Lenient recall | 87% (80–93%) | 90% (84–95%) | −3.1 pts (−9.2 to +2.0) |
| RUNWAY false alarms / h | 4.1 (1.9–6.6) | 4.9 (2.3–7.8) | −0.8 (−2.3 to +0.7) |
| **ASR transcripts** | | | |
| Lenient recall | 87% (80–93%) | 91% (85–96%) | −4.1 pts (−10.2 to +1.0) |
| RUNWAY false alarms / h | 4.5 (2.0–7.3) | 6.0 (3.0–9.3) | **−1.5 (−3.0 to −0.4)** |

On gold transcripts the two extractors are statistically indistinguishable on both measures. On ASR transcripts,
recall stays indistinguishable, but Sonnet raises significantly more false alarms — 1.5 per hour more, the only
interval in this study that excludes zero. Of the recordings where exactly one arm raises a false alarm under ASR,
Sonnet accounts for 4 and the rules parser for 0.

**Two alerts in this comparison have no adjudication verdict, and they cannot change it.** §2's strip fix raises one
previously unseen alert on recording 261 and one on 352, at alert keys no adjudication sheet covers, so
`evaluate.false_alarm_units` raises `Pending` rather than guess a verdict, and `conflict-eval.md` prints `pending`
for every RUNWAY false-alarm figure. Refusing to guess is the right default — the possible treatments bias in known
directions — but it says nothing about how much the two verdicts could matter, so we bound it
(`scripts/pending_sensitivity.py`, free and deterministic). The three treatments below bracket every verdict those
two alerts could receive:

| Treatment of the 2 pending alerts | rules − Sonnet, ASR | rules − Sonnet, gold |
|---|---|---|
| not counted (what `genuine` would do) | −1.51 (−3.02 to −0.36) | −0.75 (−2.30 to +0.74) |
| recording dropped from the comparison | −1.52 (−3.14 to −0.37) | −0.76 (−2.31 to +0.75) |
| counted as false alarms (any non-`genuine` verdict) | −1.88 (−3.61 to −0.38) | −1.13 (−2.92 to +0.38) |

The ASR interval excludes zero under all three and the gold interval includes zero under all three, so neither
conclusion depends on the pending verdicts. §4.2 reports the first row, which is the treatment least favourable to
the claim that a gap exists; an adjudication finding either alert not-genuine widens the gap rather than closing it.
We note that dropping the recording — the intuitive fix — is selection on the outcome, since it removes a negative
*because* an arm alerted on it, and so flatters the arm that alerted; it is shown for comparison, not used.

**Figure 2.** ![Primary comparison: recall and false alarms with 95% CI error bars](figures/fig-primary-comparison.png)

The Whisper model was fine-tuned on this corpus's train split, and 80% of this study's transmissions are train
split, so true degradation under unseen audio is understated for both arms (§7; test-split-only figures are in
[`conflict-eval.md`](results/conflict-eval.md)).

### 4.3 Where each extractor does well or poorly

The aggregate numbers in §4.2 combine a large shared mass of behaviour the extractor choice does not affect with a
small number of recordings that carry the whole difference:

| | Positives (n=98) | Negatives, false alarm (n=309) |
|---|---|---|
| Both arms agree | 83 (both catch) / 8 (both miss) | 295 clean + 10 both false-alarm |
| Rules only | 2 | 1 |
| Sonnet only | 5 | 2 |

**Figure 3.** ![Case-by-case agreement between rules and Sonnet, positives and negatives](figures/fig-case-contingency.png)

Classifying every false alarm by cause shows what the two arms are mostly doing, which is the same thing: no arm
ever raises an adjudicated `genuine` false alarm (i.e. an alert that turns out to be a real conflict) on any of the 309
recordings; `missing_release` — extraction was correct, but the release of a runway was simply never transmitted —
accounts for 8 of the 11 to 17 false alarms per arm; a further 3–4 per arm are `engine_rule` cases (a framing
limitation, not an extraction error); and `parse_error`, the one category the extractor can move, is 0 for rules
and 1 for Sonnet. The choice of extractor can therefore move at most one of roughly a dozen false alarms per arm —
this system's false-alarm rate is set mainly by what the tower frequency does and does not carry.

This pattern replicates on a second model (Haiku 5.5) and a second transcript kind (ASR)
([`cross-arm-replication.md`](results/cross-arm-replication.md)):

| Invented conflicts (`parse_error`) | Gold | ASR |
|---|---:|---:|
| Rules | 0 | 0 |
| Sonnet 5 | 1 | 2 |
| Haiku 5.5 | 2 | 4 |

The count rises with transcription noise within each model and is zero for the rules parser in every condition,
while `missing_release` stays flat (8–11) across all six arms. This holds across an independent model and an
independent transcript kind, which is what makes "the LLM's failure mode is invention" a property of the approach
rather than of one comparison — though the volume involved is still small relative to each arm's 11 to 17 false
alarms.

**Figure 4.** ![Failure taxonomy of RUNWAY false alarms, window context, gold transcripts, by arm](figures/fig-failure-taxonomy.png)

**The divergent cases, inspected individually.** All eleven gold-transcript divergences between rules and Sonnet
(seven positives, four negatives) were
read case by case (Appendix A); a classifier (`scripts/cross_arm_replication.py`) was then run over all 25 divergent
positives across all four rules-vs-LLM arm pairs (both models, both transcript kinds) to check whether the same
mechanisms generalise:

| Comparison | Caught by rules only | Caught by LLM only | identity (holder) | identity (trigger) | supersession |
|---|---:|---:|---:|---:|---:|
| rules vs Sonnet 5 / gold | 2 | 5 | 5 | 0 | 2 |
| rules vs Haiku 5.5 / gold | 2 | 3 | 3 | 1 | 1 |
| rules vs Sonnet 5 / ASR | 2 | 6 | 5 | 1 | 2 |
| rules vs Haiku 5.5 / ASR | 1 | 4 | 4 | 0 | 1 |

Two mechanisms account for all 25 divergent positives, with none left unclassified. **`identity (holder)`** (17 of
25): the two arms extract the conflicting clearance identically, but the rules parser extracts the *earlier*
reservation on that runway with an empty callsign, which caps the conflict at `warning` because the engine cannot
rule out that an unidentified aircraft is the one already holding the runway; an LLM that resolves that earlier
callsign from surrounding context turns the same situation into a full alert. **`identity (trigger)`** (2 of 25) is
the same mechanism applied to the conflicting clearance itself rather than the prior holder, and needs no memory of
earlier transmissions. **`supersession`** (6 of 25) runs the other way: an LLM invents an event for the aircraft
already holding the runway, the new reservation overwrites the earlier one, and the compatibility matrix then rates
the rewritten pair lower than the real one (e.g. a line-up becomes a takeoff, downgrading an alert to a warning).

Two corrections follow from running the classifier across all four arm pairs rather than one. First, callsign
resolution is not a property of being an LLM: in recording 3291, the *rules* parser resolves a bare-numeric callsign
that Haiku 5.5 leaves blank, so the rules arm is the one that catches that conflict. Second, Sonnet's accuracy can
itself produce a false alarm: in recording 74, the rules parser leaves both callsigns blank and raises two
warnings, while Sonnet names both aircraft correctly and the engine escalates to one alert — adjudicated as
`missing_release`, since the underlying issue is the same as every other case in that category.

**And one rules-parser failure from a transcript artefact.** Recording 533's rules-only false alarm is caused by a
spelling inconsistency in the transcript — the same aircraft appears as "austrian seven one two zulu" and "ausrtian
seven one two zulu" — which the regex-based callsign matcher treats as two different aircraft, flagging the aircraft
against itself; Sonnet reads both spellings as one aircraft and raises nothing.

### 4.4 The LLM-judge ablation

A separate ablation removes both the extractor interface and the engine: the whole transcript is given to the model
in one call, and it returns a list of conflicts directly, with no typed events and no runway-reservation state in
between.

| Arm (gold transcripts) | Lenient recall | RUNWAY false alarms / h | `parse_error` verdicts |
|---|---|---|---|
| Rules, window | 87% (80–93%) | 4.1 (1.9–6.6) | 0 |
| Sonnet 5 extractor, window | 90% (84–95%) | 4.9 (2.3–7.8) | 1 |
| Sonnet 5 judge, sequence | 72% (63–82%) | 14.3 (10.3–18.1) | 7 |
| Haiku 5.5 judge, sequence | 78% (69–86%) | 14.7 (10.5–19.0) | 9 |

Dropping the engine costs roughly 18 points of recall and roughly triples the false-alarm rate, with both judge
models landing in a similar range. The same Sonnet 5 model reaches 90% recall at 4.9 false alarms/hour as a
constrained extractor and 72% at 14.3 when asked to track state and apply conflict logic itself; the difference is
architectural, not a difference in model capability. Two factors temper but do not close this gap: the judge reports
no severity level, so every conflict it names counts as a full alert where the structured arms could return a
sub-threshold warning, and alert verdicts are pooled by alert key across arms. Neither accounts for an 18-point
recall difference, which is a direct miss count.

### 4.5 Real incidents

Three historical incidents and two 2026 reconstructions were replayed through the pipeline
([`pilot-cases.md`](results/pilot-cases.md); `scripts/real_2026_cases.py`). With n=5 these are reported as case
studies, not as a rate.

**Austin (KAUS), 4 Feb 2023 (NTSB DCA23FA149).** Sonnet extracts "one eight left cleared to land" and the engine
alerts at the conflicting takeoff clearance; the rules parser drops that line because the word "runway" is absent
from it, and only raises a warning 36 seconds later, without a callsign. Sonnet separately invented a `TAKEOFF`
event from the pilot's "fedex is on the go" — slang for a go-around, the opposite of a departure.

**Prague (LKPR), recording 528.** Both extractors raise the same alert, correctly: an aircraft had crossed the
runway, but the release was never spoken on the tower frequency. This is `missing_release`, and no choice of
extractor removes it.

**JFK (KJFK), 13 Jan 2023 (NTSB DCA23LA125) — a counterexample.** ATC cleared American 106 to cross runway 31L at
taxiway K; the crew instead crossed runway 4L at taxiway J, about 20 seconds after Delta 1943 began its takeoff roll
on that runway. Both clearances, as transmitted, were individually correct and named different runways — the
controller said nothing wrong, and both readbacks were correct. A system that detects incompatible *clearances*
should raise nothing here, and that is the right answer: the error was in execution, not in what was said, and is
outside what any communications-only check can represent. This is the category boundary the opening incident in §1
sits on the other side of — a contradiction between two clearances, rather than a correct clearance not followed.

Replaying the reconstructed exchange through the rules parser, as scored throughout this report, confirmed the
right answer, but not for the reason the case is usually told. In the historically ordered sequence — Delta's
takeoff clearance first, American's crossing clearance second — the parser extracted **no event at all** for
"runway four left," the same single-digit designator gap documented in Appendix B, so Delta's reservation was never
opened and the subsequent crossing clearance had nothing to conflict with. Reversing the order, so a reservation on
31L was already open when the single-digit designator was parsed, flipped the outcome: the fallback to "the one
runway currently active" (§2.2.1) then wrongly assigned Delta's takeoff to 31L, and the engine raised a false
`alert` between two aircraft that were in fact cleared for different runways (Appendix B4). The parser's correct
silence on this case was therefore not evidence that it reasons correctly about non-conflicting runways; it
depended on which clearance a controller happened to say first, driven by the same designator gap behind §7's
LaGuardia finding — once the designator is read at all, correctly extracting the two different runways rather than
failing to extract one of them, the engine's own logic is what was missing, not a judgement about non-conflict the
parser never had to make.

**Goa (VAGO, 2026-04-03) and Houston (KIAH, 2026-04-24).** These two reconstructions, built from seven transmissions
in total (five Goa, two Houston) (`data/labels/real_2026_cases_A.csv`), are the clearest demonstration of the engine's framing boundary (§2.3).
Replayed through the rules parser, the seven Goa lines (a taxi instruction to a holding point, a frequency handoff,
"expect backtrack," and a pilot's "entering runway") and the two Houston lines (a controller correcting a crew that
had followed another aircraft's clearance) produce only `HANDOFF` and `READBACK` events — **no `LAND`, `TAKEOFF`,
`LUAW`, or `CROSS` reservation is opened in either case**, so no alert can be raised by either extractor. Goa is a
backtrack incursion; Houston is a callsign-confusion event. Neither is an incompatible pair of runway clearances,
which is the only failure mode this engine models.

Sonnet 5 was run on the same seven Goa lines and invented nothing: no `TAKEOFF` and no `LAND` event, despite lines
("expect backtrack," "entering runway") structurally similar to the ones that produced a hallucination in the
synthetic data (recording 242, §4.3). Where the two extractors differ on this real text, the differences are the
same mechanisms seen elsewhere, not new ones:

| | Rules parser | Sonnet 5 |
|---|---|---|
| "taxi via N2 hold at holding point runway 08" | nothing (`NOOP`) — its pattern needs "hold short" | `HOLD_SHORT 08` |
| "hold at holding point and contact navy approach 119.7" (no runway named) | `HANDOFF` only | `HOLD_SHORT 08` + `HANDOFF` |
| the handoff's callsign | `one one niner` — the radio frequency, read as a callsign | blank, correctly |

The second row is `window` context carrying runway 08 forward from the previous line, the same mechanism as the
identity-resolution cases in §4.3. The third is a rules-parser extraction error of the same family as recording
533's misspelling: the regex-based callsign matcher takes "one one niner" from "contact navy approach one one niner
decimal seven" as if it were a callsign. None of these three differences changes the outcome, because none produces
a reservation on either arm. The Sonnet events in this table are recorded in `data/eval/real_2026/` and reproducible
without an API key; the recording currently carries provenance `transcribed` rather than `api` pending one further
run against the live API to confirm it byte-for-byte (`scripts/real_2026_cases.py --verify`).

What neither extractor represents is the incursion itself: the pilot's "entering runway" at Goa is the
safety-critical moment in that incident, and the engine has no event kind for an aircraft entering a runway other
than via a clearance it was given. That is a boundary of the engine's vocabulary, not of either extractor.

---

## 5. Conceptual analysis

§4.1 shows Sonnet inventing 9 of 32 events where the rules parser invents 0; §4.2 shows the two extractors' overall
false-alarm rates within noise of each other. A direct perturbation study resolves this tension by measuring, rather
than arguing, how often a single extraction error changes the system's output at all: one event in a recording's
already-extracted stream is edited, the stream is re-folded through the engine, and the resulting alerts are
compared to the original ([`risk-score.md`](results/risk-score.md); free and deterministic, no re-parsing or API
calls).

| Error kind | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---:|---:|
| Wrong runway | 23% | 27% | 6% |
| Dropped event | 27% | 45% | 0% |
| Wrong event type | 24% | 26% | 8% |
| Wrong callsign | 19% | 13% | 9% |
| Invented event, runway in use | 54% | 7% | 37% |
| Invented event, runway not in use | 71% | 0% | 61% |

*Rules arm, window context, gold transcripts; the Sonnet arm and the other gold arms agree within a few points.*

Four points follow from this table. **First**, most single-field extraction errors never reach the system's output
at all — 19–34% change any alert. A per-field accuracy score on its own would overstate how much extraction quality
matters to this system. **Second**, the two extractors' characteristic errors cause different, largely non-
overlapping harms: omission (the rules parser's typical failure) costs recall and essentially never creates a false
alarm; invention (the LLM's typical failure) creates false alarms and barely touches recall. Collapsing these into
one combined score would hide this asymmetry rather than express it, which is why this study reports two rates
instead of one. **Third**, an invented clearance is *most* dangerous on the other end of a working strip, not least:
an invention on the runway already in use raises a false alarm 37% of the time, and one on a runway "not in use"
61% of the time, because on a corpus with one active strip the other designator is the reciprocal end and two
landings from opposite ends are head-on. The pre-fix reading of this was the opposite, and rested on the engine
being unable to relate the two ends — most of Sonnet's inventions in this data are approach clearances
naming runways the tower is not currently working, so the deterministic engine screens them out; this explains why
so the earlier explanation of why §4.1's visible gap failed to reach §4.2's aggregate numbers is withdrawn
(`risk-score.md`, re-run callout). **Fourth**, a hallucination can also suppress a
real alert as well as raising one: an invented event on the runway already in use costs a true detection 7–11% of
the time, because the new reservation overwrites whatever that aircraft already held. This
failure mode produces no alert, no alarm, and no record that anything happened.

**Alternative explanation: the test set favours the rules parser by construction.** The synthetic positives are
located by a keyword scan for textbook clearance phrasing ("cleared to land," "line up," "cross runway") — close to
the exact phrasing the rules parser's regular expressions are written to match. This was documented as a known bias
before the paid evaluation was run, not discovered afterward
([`decisions.md`](logs/decisions.md), 2026-10-19 entry). The blind two-person validation protocol (§3.3.1) controls
who judges whether an injected case is plausible, not how candidate sites are located, so it does not remove this
bias. The "no significant difference" result in §4.2 is accordingly a lower bound on how different the two
extractors might be on phrasing further from this distribution — injections built from phrasing the keyword scan
cannot find, or scoring directly against real incident transcripts, would tighten this.

**A second methodological check, already addressed in the design.** An earlier version of the labelling procedure
risked circularity — gold labels produced using the same rule the comparison was meant to test — and was redesigned
to label blind, by individual transmission, with overlap scored for agreement before any comparison was run
(`decisions.md`, 2026-09-14 entry).

**Framing assumption.** Every result above is read through the engine's proxy: "same runway, overlapping
reservation" stands in for loss of separation, not for loss of separation itself, and the system makes no claim
about ICAO Doc 4444 compliance. §4.5's two 2026 reconstructions show this proxy's boundary directly — a backtrack
incursion and a callsign-confusion event, both reported runway-safety incidents, that this system's conflict
definition cannot represent regardless of extraction quality. Any claim about safety that follows from these
results has to be phrased in terms of this proxy, not substituted for it.

## 6. Societal and philosophical analysis

Milestone 1 framed the normative question as whether an LLM's outputs can be explained well enough for
responsibility to land somewhere. The results above suggest that this framing locates the problem in the wrong
place. The extractor in this system fills four checkable fields for one transmission at a time; a controller can
verify every one of them against the sentence they just heard, whether a regular expression or a language model
produced them. What varies between the two extractors is not whether an alert can be accounted for, but *which
conflicts the system is able to represent at all* — and that turns out to be a question about vocabulary, corpus
composition, and design choices made months before any alert fires.

We use the account of meaningful human control given by Santoni de Sio and van den Hoven (2018), which sets two
jointly necessary conditions: a system must **track** the human reasons that should govern it, and responsibility
for its behaviour must be **traceable** to a human who understood what they were doing. The two conditions separate
this project's findings cleanly, and — unusually for a normative framework applied to an engineering result — the
first one is directly measurable here.

### 6.1 Who bears the risk, and how the extractor choice distributes it

Four groups are affected, and they do not bear the same failure modes.

**Controllers** absorb the alerts. At 4–6 `RUNWAY` false alarms per hour (§4.2), with 8 of roughly 12 per arm caused
by a release that was never transmitted rather than by any extraction error (§4.3), the dominant experience of this
system for a controller would be interruption that is explicable but not actionable. The conditions under which
that becomes dangerous are specific: Parasuraman and Manzey (2010) find that automation complacency arises under
**multiple-task load**, when manual tasks compete with the automated one for attention, that it appears in experts
as readily as in novices, and that it "cannot be overcome with simple practice" — nor can automation bias be
prevented by training or instructions. Those are precisely the conditions at LaGuardia on 22 March 2026: two
controllers on position, each working two combined positions, near midnight. An alerting system introduced into
that environment cannot be made safe by telling controllers to stay vigilant, because the literature says that
instruction does not work.

**Flight crews and passengers** bear a failure mode they cannot see. §5 shows that an invented clearance on a runway
already in use costs a true detection 7–11% of the time, because the new
reservation overwrites whatever that aircraft already held. This failure produces no alert, no alarm, and no record
that anything was missed. Every other error in this study is visible to someone: a false alarm interrupts a
controller, a missed detection on a labelled positive shows up in a recall figure. This one is visible to nobody,
and the people exposed to it are the ones furthest from the system.

**Ground vehicle crews** are the group this project's evidence treats worst, and the opening case is the reason.
Replaying the reconstructed LaGuardia sequence through the rules parser under the ICAO default, as scored
throughout this report, produced no events at all — not the landing clearance, not the crossing clearance (Appendix B). The cause was not the
vehicle callsign, which the parser's prefix scan does resolve as `truck one`; it was that LaGuardia's runway 4 is
spoken as "runway four", and the parser's phrase patterns matched a two-token designator only. `runway four`
yielded nothing while `runway zero four` yielded a clearance, and this held for every single-digit runway from 1 to
9, even though the parser's own `normalize_runway` helper converts "four" to `04` correctly. The gap was in the
phrase pattern, not the helper, and it was absent from the module's own documented list of known gaps (§2.2.1): it
shipped, was scored, and sat in the report for a full pass before anyone asked the question that found it.

This matters normatively rather than just as a bug, for two reasons. First, the evaluation could not have found it
on its own: all 98 scored positives are on runways 13 and 31 — which, since §2's strip fix, are **one runway** to
the engine, making the scored corpus effectively a single-runway airport — and 97% of extracted events in the
corpus are on those
two designators. The 87% recall reported in §4.2 is unaffected by the gap and does not transfer to an
airport with a single-digit runway. Second, the exposure is not evenly distributed. Single-digit runways, non-airline
callsigns,
and vehicle operations are not randomly scattered across aviation; an extractor whose vocabulary is a closed
enumeration encodes a judgement about whose transmissions are worth representing, and that judgement was made
implicitly, by whoever wrote the regular expressions, against whatever corpus was available. The open-vocabulary
extractor has the opposite property — §4.1 shows it reads phrasing nobody enumerated, and at Austin it extracted a
landing clearance the regex dropped for a missing word — at the cost of inventing events nobody said. The choice
between them is therefore not only a trade between recall and false alarms. It is a choice about which populations
of traffic the system is capable of protecting, taken before any alert is ever raised.

**The two of us**, finally, are stakeholders in a way the Milestone 1 framing did not anticipate: we constitute the
ground truth. Inter-rater agreement on the false-alarm label was Cohen's κ = 0.12 before a written checklist
existed and 0.80 after (§3.3.2) — and κ is 1.00 on the 11 alerts the checklist's near-mechanical first step decides
and 0.62 on the other 20. Every rate in this report is measured against a construct that two non-controllers could
not reliably apply until they wrote a procedure for it.

### 6.2 Tracking: a condition this study measures rather than assumes

Santoni de Sio and van den Hoven build the tracking condition on Nozick's truth-tracking, and it is explicitly
twofold: a mechanism tracks a fact when (i) if the fact were not so, the mechanism would not report it, and (ii) if
the fact were so, the mechanism would report it. Their own illustration is a classifier that must call a wolf a wolf
and must not call a husky a wolf "in a great variety of possible worlds."

Those two limbs are this study's two measures. Limb (ii) is recall, and limb (i) is the adjudicated false-alarm
rate — which is why the failure taxonomy matters more than the headline number: of the five verdicts, only
`parse_error` is a limb-(i) failure in the relevant sense, an alert raised when nothing was said. The others record
that the tower channel did not carry a release, or that the compatibility matrix is stricter than practice. So the
report does not have to argue about whether the system tracks; it can state what was measured. On human transcripts
both limbs are indistinguishable between the two extractors. Under transcription noise limb (ii) stays
indistinguishable while limb (i) degrades significantly for the LLM, by 1.5 false alarms per hour (§4.2) — and the
invented-conflict count rises monotonically from 0 for the rules parser to 2 for Sonnet and 4 for Haiku on ASR
(§4.3). The judge ablation fails both limbs at once, losing 18 points of recall while tripling the false-alarm rate
(§4.4), which is evidence that removing the structured interface does not buy tracking performance in exchange for
its opacity.

The sharper point is what "a great variety of possible worlds" costs us. Tracking is a counterfactual robustness
claim, and our evaluation sampled one narrow region of the possible: two runway designators, one tower's
phraseology, synthetic positives located by a keyword scan tuned to textbook phrasing (§5). The single-digit runway
blind spot is a tracking failure in an immediately adjacent possible world — one airport over — that no number in
§4 could have revealed. A measured tracking result is therefore a claim about the worlds you sampled, and reporting
it as a property of the system would overstate it. This is the most useful thing the framework does for us: it
names why the corpus's composition is a normative problem and not merely a methodological caveat.

### 6.3 Tracing: the responsibility that runs backwards

The tracing condition is about ownership. Santoni de Sio and van den Hoven take it from the moral-responsibility
literature, where an agent can be responsible for an outcome they could not control at the time, provided they were
responsible earlier for putting themselves in that position — the drunk driver who is culpable not for their
in-situ incapacity but for the decision to drink. They also adopt Kamm's notion of the **choice architect**: when
one party constructs the situation in which another must choose, responsibility traces to the architect, not only
to the person facing the choice.

For an alert from the extractor pipeline, the in-situ story is good. The model fills four fields for one
transmission; the matrix that turns those fields into a severity can be read off the page; a controller can check
both. On the taxonomy of Santoni de Sio and Mecacci (2021), the **moral accountability gap** — the reduced capacity
of agents to make sense of and explain the logic of a system's behaviour — is narrow here, and it is narrow because
of the interface rather than because of the model. It is wide in the judge arm, where a reported conflict has no
intermediate representation to inspect, only a conclusion; and the judge is also the worse system, so its opacity
buys nothing.

But tracing runs backwards, and that is where this project's exposure lies. We are the choice architects of the
controller's situation, and three of our own findings show how little we understood what we were building:

- The engine's `MATRIX` defines 16 compatibility cells, and its companion `MATRIX_BASIS` records a verified ICAO
  Doc 4444 citation for exactly **three** of them (Appendix D). The remaining 13 — including every `warning` cell,
  which is what caps a conflict when an aircraft is unidentified — encode our judgement, not doctrine. The code is
  candid about this, which is to its credit, but it means the definition of "conflict" that generates every number
  in this report is largely ours.
- The engine has no representation for a backtrack incursion or for callsign confusion, so two of the most-reported
  runway-safety events of 2026 are invisible to it regardless of extraction quality (§4.5). We discovered this by
  replaying them, not by designing for it.
- The suppression failure in §5 was found by perturbation, after the fact. A pipeline that is fully traceable for
  the alerts it raises offers a controller nothing whatsoever for the detections it silently loses, because there is
  no event to inspect.

The gap these describe is not the culpability gap — nobody is unblameable here, and we are an identifiable team who
made identifiable decisions, logged with dates and reasons. It is what Santoni de Sio and Mecacci call the **active
responsibility gap**: the risk that those designing a system "may not be sufficiently aware, capable, and motivated
to see and act according to their moral obligations towards the behaviour of the systems they design." That is a
precise description of a team that wrote 16 matrix cells with 3 citations, measured recall on two runway
designators, and found its parser's single-digit blind spot only when a reader asked why a US-specific gap should be
left alone — months after it shipped and was scored. That it was then addressed in the same session (§7) is a real
mitigation of one instance, and a partial one: the condition covers clearance extraction but not read-back checking,
and it is correct by construction rather than by evidence, since no transcript in this corpus exercises it. It is not
evidence the underlying gap is closed: the same oversight pattern — a
closed enumeration standing in for a judgement nobody made on purpose — can recur at the next designator, phraseology,
or jurisdiction nobody happened to test. The decision log, the pre-registered comparison, and the blind two-person
validation protocol are further real mitigations, and the retraction of our own Milestone 1 determinism claim
(§2.2.2) is another. None of them is a solution to it.

### 6.4 What this analysis does not settle

A traceable alert is only useful if someone still attends to it, and we cannot show that they would. The temptation
is to argue that 4–6 false alarms per hour will erode vigilance, but the strongest empirical study in this domain
says the opposite: Wickens et al. (2009) analysed 495 en route conflict alerts, found 45% of them false, and
concluded that "the high false-alarm rate does not appear to induce cry wolf behavior in the context of en route ATC
conflict alerts" — controllers instead anticipated, issuing trajectory changes before the alert. Ruskin et al.
(2021) document something different in their 370 ASRS reports: controllers ignoring or muting alarms they had judged
non-hazardous, which is a response to nuisance rather than to unreliability. Neither study licenses a claim about a
tower-frequency clearance checker at 4–6 alarms per hour, and we did not run a human-in-the-loop trial. The honest
position is that the vigilance question is open and that our rates sit in a regime nobody has studied.

The opening case constrains the claim further, and in a direction that does not favour us. At LaGuardia the landing
clearance was issued at about 23:35 and the crossing clearance about two minutes later, roughly 25 seconds before
impact, with the aircraft a little over 100 feet above the ground; the controller's own "stop, stop, stop" followed
within seconds. The engine would alert at the crossing clearance — which is to say at almost exactly the moment the
controller realised it themselves. ASDE-X was installed and operating and did not alert, because the ARFF vehicles
carried no transponders for it to track: a surveillance failure about what the system could *sense*, where a
text-level check depends instead on what was *said*. That asymmetry is the real argument for this kind of system,
and it is an argument about coverage of a different failure surface, not about lead time. On the evidence here, a
clearance checker would have been **right** at LaGuardia, roughly 25 seconds before impact, and would have told the
controller something they were seconds from working out unaided — provided it could read "runway four," which the
scored rules arm could not (Appendix B4). The 25-second figure is unaffected either way, because it is set by when
the conflicting clearance was spoken, not by whether the parser could read it.

---

## 7. Limitations and next tests

**The scored rules parser is blind to single-digit runways, and this evaluation could not have detected it on its
own.** `runway four` produces no event where `runway zero four` produces a clearance, for every designator from 1
to 9, although `normalize_runway` converts both correctly (Appendix B). All 98 scored positives are on runways 13
and 31, and 97% of extracted events in the corpus carry those two designators, so the reported recall is unaffected
and does not transfer to an airport with a single-digit runway. The phrasing appears in 110 of 22,956
transcripts (73 gold, 37 ASR), and **not one is a genuine single-digit designator** — every one is a truncated
recording (Appendix B3).
This is not an isolated glitch confined to one incident: replaying the JFK case study through the same code showed
the identical gap either dropping a real clearance silently or inventing a false alert on a different runway,
depending only on which of two correctly-issued clearances came first (Appendix B4).

**The fix was made, and the first version of it was wrong in an instructive way.** Relaxing the designator pattern
to accept a single digit-word is a one-line change, and that is how it was first applied: to every recording. The
spot-check that followed showed it is not a strict improvement but a trade, and measuring it properly showed the
trade is entirely one-sided on this data. The relaxed pattern captures a designator the strict one does not in 110
of 22,956 transcripts (73 gold, 37 ASR), and **not one of those is a genuine single-digit clearance.** Every one is
a two-word designator clipped by transcription: `"...line up runway three o"` became `LUAW 03` where the strict
pattern correctly matched nothing and let the window context supply the active runway 13, and
`"...runway zero niner cleared to land"` became a `NoOp` — the clearance dropped outright, because `"zero"` alone
normalises to no valid runway. A blanket relaxation therefore buys nothing here and costs 110 misreadings.

**So the fix is not a looser pattern but an extra condition: which convention does this airport speak?** The default
requires two digit-words, as the scored baseline did — verified identical to it on all 22,956 transcripts, 0
differences, so no number in §4 moves — and the single-digit reading is enabled per recording
(`parse_rules.make_parser(single_digit_runways=True)`), for the Austin case studies (KAUS) and the Houston
reconstruction (KIAH). Under that condition the LaGuardia sequence of §6 extracts `LAND 04` and `CROSS 04` and the
engine raises the alert it should have raised; under the default it extracts nothing.

**What that says about where the limitation actually sits.** The interesting part is not that one pattern was too
narrow. It is that the thing standing between this system and a correct reading of LaGuardia was neither extractor's
ability to understand language — it was whether a phraseology convention had been encoded for that airport. That
condition sits *in front of* the parser, as a hardcoded fact about the airport, so it does not discriminate between
extractors at all: once the convention is right, the rules parser and the LLM both read `04L`, and once it is wrong,
neither can — the LLM is not rescued by being a language model, because the designator it is asked to normalise is
ambiguous in exactly the same way. The axis this report spends §4 measuring — rules versus LLM — is therefore not
the axis on which this class of failure lives.

**And our data cannot settle the rest of that axis.** Every airport the corpus names is European or Australian
(LKPR, LSZH, LSGS, LSZB, LZIB, LKTB, YSSY), none of which uses single-digit designators; 99 of the 110 truncated
mentions carry no `airport_icao` at all. There is no US airport in the corpus, and even the Houston reconstruction
never speaks a single-digit designator, so the condition we added is correct by construction and **untestable on the
evidence available.** The same holds for the other convention we encoded: `"oh"` substituted for `"zero"`, a
documented confusion source with non-native-English controllers, is now accepted inside a designator — and occurs 0
times in all 22,956 transcripts, so it too is a robustness claim about ATC phraseology rather than a result about
this data. Encoding conventions one jurisdiction at a time is not a generalisation strategy; it is a list, and the
length of that list is a property of the corpus one happens to hold. That is the honest limit of §4's external
validity, and it is a sharper statement of it than "the corpus has two designators."

**The condition is also not yet applied consistently.** It governs clearance extraction but not read-back checking:
`readback.extract_items` still requires two digit-words, deliberately, because widening it would make the read-back
check see a runway item in those same 110 truncated mentions and move every published read-back number. So under the
single-digit convention the clearance side books `"runway four left"` while the read-back side cannot, and a runway
read-back miss on a single-digit designator goes undetected. The asymmetry is pinned by a test rather than left to
be discovered.

**A candidate structural fix — a per-airport runway-validity check, rejecting a designator the recording's airport
does not actually have — is not buildable with the data this project has.** `recordings.airport_icao` is populated
for only 560 of 3,300 recordings overall, and for only 4 of the 407 scored recordings — the other 403, including
305 of the 309 scored negatives (all UWB-ATCC), carry no airport identifier at all, so there is nothing to validate
a designator against for 99% of what this report scores. It is listed as a next test below, naming the missing
metadata, rather than built on a guess.

**Level 1 is not the measure we pre-registered.** The purpose-built event sheets (200 tower transmissions, 50
double-labelled for κ) were generated but never labelled; §4.1 substitutes a readback sheet labelled by one person,
with no second rater, drawn mostly from approach and radar rather than tower traffic. This is also what prevents
§5's consequence weights from becoming a per-extractor score: the weights are rates per perturbation opportunity,
and converting them requires error counts from a properly sampled labelled set.

**The positives are synthetic and biased toward the rules parser at the site-selection step** (§5), so §4.2's "no
significant difference" is a lower bound on how far apart the two extractors could be on phrasing further from
textbook form. **The ASR arms carry train/test leakage**: the Whisper model was fine-tuned on this corpus's train
split and 80% of our transmissions are train split, so the reported degradation understates true degradation for
both arms.

**The perturbation study edits one event at a time** and operates on an extractor's own event stream rather than on
human gold events, since the event sheets are unlabelled. Correlated errors — an ASR digit failure corrupting one
runway across a whole recording — are not modelled.

**No LLM context sweep was run.** §2.2.2's mechanism argument rests on the hallucination evidence, not on measured
context variation; the rules arm's sweep (91/87/87% at `none`/`role`/`window`) shows only that context barely moves
a regular expression. A dry run on 2026-11-08 priced Sonnet at `none` and `role` at $6.88 and $6.90; this is the
single most informative remaining run and the first thing we would buy.

**`READBACK` alerts were counted but not adjudicated**, so that rate is an upper bound. **Neither adjudicator is a
controller**; verdicts follow a written procedure rather than domain expertise. **The mechanism classifier in §4.3
is automatic but was validated against a hand reading of one arm pair only** (rules vs Sonnet 5 on gold); it leaves
none of the 25 divergent positives unexplained, which is reassuring but not independent confirmation.

**Two provenance gaps in the case-study material.** The LaGuardia facts in §1 and §6.4 are taken from press
reporting of the NTSB preliminary report, not from the report itself, which is not held locally; every timestamp
and quotation should be checked against the PDF before submission, and the ~100 ft figure differs from the ~130 ft
in our own case-study note. Separately, the Sonnet events for the 2026 reconstructions in §4.5 are recorded with
provenance `transcribed` rather than `api`, meaning they were read back from a run rather than written by the
script against the API; `scripts/real_2026_cases.py --verify` closes this for about two cents.

**The engine's largest failure category has no retrofittable fix within this data.** `missing_release` dominates on
every arm and means extraction was correct and the release was never spoken. In real operation a controller clears
a runway by visual scan, or at a few major hubs by surface radar — neither produces a transmission, and there is no
verbal release phraseology for a completed takeoff in standard practice. Surface radar exists at a small set of
large airports, not the regional European towers this corpus is drawn from, and its feed is operational
infrastructure with no public access; Runway Status Lights are a display layer on that same feed and a US-specific
programme; and these recordings are archived radio audio with no synchronised video. The honest claim is not that
position data was out of scope but that **no fix for `missing_release` exists within this dataset's recorded
channel**.

**Most informative next tests, in order.** (1) The LLM context sweep, which is the mechanism variable the §4.3
evidence cannot isolate. (2) Labelling `event_sheet_B.csv` — 50 rows, both of us — which would give Level 1 a κ on
tower audio and let §5's weights become a per-extractor score. (3) A phraseology audit of the frozen baseline
against ICAO designator forms, since the single-digit blind spot above was found by one ad-hoc test and there is no
reason to think it is the only one. (4) Injections built from phrasing the keyword scan cannot locate, or scoring
directly against real incident transcripts. (5) A hybrid extractor, simulated from the stored rows: the rules
parser's events with blank callsigns backfilled from the LLM's event of the same kind and runway on the same
transmission. A preliminary run scored 94% lenient recall at 4.5 false alarms per hour against rules at 87%/4.1 and
Sonnet at 90%/4.9, but it is post-hoc — designed after reading the divergences and scored on the same 98 positives
that motivated it — and the script that produced it is not in the repository, so the figure is currently not
reproducible and is reported here only as a direction. (6) A per-airport runway-validity check, rejecting a
designator the recording's airport does not actually have — this would directly catch the clipped-recording
failure mode above (e.g. "runway three o" read as `03` rather than the real `31`), but needs airport identity this
dataset mostly does not carry: `airport_icao` covers only 4 of the 407 scored recordings, so the first step is
sourcing or inferring per-recording airport metadata for UWB-ATCC, not writing the check itself.

---

## 8. Process transparency

The appendices below are the audit trail. Both logs are kept as the work happens rather than written afterwards, and
both record rejections as well as decisions: the AI-use log includes cases where the model's output was measured and
then discarded, among them an ASR-leakage claim that turned out to be false, a cost estimate wrong by a factor of
six, a parser-side callsign fix that would have overwritten another aircraft's reservation, and a mechanism
classifier whose first version re-implemented engine state and agreed with the real engine only by coincidence.

- **AI-use log:** [`docs/logs/ai-use.md`](logs/ai-use.md) — 28 entries.
- **Decision log:** [`docs/logs/decisions.md`](logs/decisions.md) — 64 entries, each with its reason, its evidence,
  and an owner. Owner labels distinguish decisions the team took, decisions one of us identified and Claude Code
  implemented, and changes Claude Code recommended that are implemented but not yet signed off.
- **Evidence artefact:** [`notebooks/milestone2_pipeline_walkthrough.ipynb`](../notebooks/milestone2_pipeline_walkthrough.ipynb),
  executed, which reproduces the pipeline end to end from the committed rows.
- **Contribution statement:** *to be written by the team.* The logs record that one of us generated the 100
  injection candidates and the other validated all 100 blind; that adjudication sheet A (94 alerts) and sheet B (31
  alerts, both rounds) were labelled by different people; and that the paid evaluation was run once, from a single
  machine, against a cached database. The trailing note in `decisions.md` flags that several rows attributed to one
  team member record decisions approved in Claude Code sessions and need checking before this statement is written.

---

# Appendices

Appendices do not count toward the page limit. Everything below is derived from material committed to the
repository, and Appendix H gives the command that regenerates each one. No appendix reproduces UWB-ATCC transcript
text, which the corpus licence does not permit us to redistribute (`decisions.md`, 2026-09-26); where a case needs
its wording, the text is NTSB public record, published incident reporting, or invented.

## Contents

| | Appendix | What it contains | Supports |
|---|---|---|---|
| **A** | Every divergent case, rules vs Sonnet 5 | All eleven gold-transcript disagreements (seven positives, four negatives) with the events each arm extracted, then all 25 divergent positives across four arm pairs with mechanism labels | §4.3 |
| **B** | The LaGuardia replay and the single-digit runway blind spot | The scored pattern catalogue and callsign heuristic verbatim, the opening incident run through the rules parser step by step, the designator test that explains the result, and a second real case (JFK) under both clearance orderings | §1, §2.2.1, §4.3, §4.5, §6.1, §7 |
| **C** | The LLM extractor's prompt and tool schema | The system prompt and JSON schema verbatim — the only place the model's instructions are fully visible | §2.2.2 |
| **D** | The compatibility matrix and its doctrinal basis | All 16 same-end cells plus the 16 opposite-end cells, with their ICAO citation or the absence of one | §2.3, §6.3 |
| **E** | Adjudication: verdicts, checklist, and agreement | The five verdicts, the written four-step procedure, and the κ breakdown by step | §3.3.2, §6.1 |
| **F** | The 2026 reconstructions in full | All seven transmissions of the Goa and Houston cases with both arms' events | §4.5 |
| **G** | Consequence weighting in full | Every perturbation kind, the method, and its caveats | §5 |
| **H** | Reproducing every number in this report | One command per table | §3 |

---

## Appendix A — Every divergent case, rules vs Sonnet 5

### A1. The ten gold-transcript disagreements, with extracted events

All ten recordings on which the primary pair disagrees. **Events and callsigns only, no transcript text.** "Trigger"
is the injected conflicting clearance; "prior holder" is the reservation already open on that runway when it
arrives. Reproducible from the stored rows with no database and no API call.

**Positives — 7 of 98 (Sonnet catches 5 the rules parser misses, the rules parser catches 2 Sonnet misses)**

*Mechanism 1 — the prior holder is anonymous to the rules parser (all 5 Sonnet-only catches).* The trigger event is
identical in both arms. The rules parser extracts the reservation already open on that runway with an empty
callsign, so `engine.apply` caps the conflict at `warning`; Sonnet names the aircraft and the same situation
becomes an `alert`.

| Rec | Rwy | Trigger event, **identical in both arms** | Prior holder, rules | Prior holder, Sonnet |
|---|---|---|---|---|
| 3223 | 13 | `LUAW`+`TAKEOFF` jobair zero five two | `LUAW` callsign **blank** | `LUAW` csa nine seven eight |
| 3230 | 31 | `LAND` swedestar zero five one | `TAKEOFF` callsign **blank** | `TAKEOFF` shamrock six four four |
| 3246 | 13 | `TAKEOFF` csa five alfa juliett | `LUAW` callsign **blank** | `LUAW` turkish one seven seven zero |
| 3250 | 13 | `TAKEOFF` channex eight eight papa romeo | `LUAW` callsign **blank** | `LUAW` csa two nine six |
| 3260 | 13 | `LAND` csa zero two five | `LUAW`+`TAKEOFF` callsign **blank** | `LUAW`+`TAKEOFF` el al five two two |

*Mechanism 2 — Sonnet invents an event that supersedes the prior holder's reservation (both rules-only catches).*
A new reservation replaces that aircraft's existing one, so an invented clearance rewrites the *kind* of
reservation already open, and the compatibility matrix then rates the pair lower:

| Rec | Rwy | Prior holder | Sonnet's invented event | Matrix effect at the trigger | Outcome |
|---|---|---|---|---|---|
| 3242 | 31 | `LUAW` csa one zulu alfa | `TAKEOFF` for that same aircraft | `TAKEOFF` vs `LUAW` = alert becomes `TAKEOFF` vs `TAKEOFF` = **warning** | rules strict → Sonnet partial |
| 3271 | 31 | `TAKEOFF` juliett november five one one | `LAND` for that same aircraft | `LAND` vs `TAKEOFF` = alert becomes `LAND` vs `LAND` = **ok** | rules strict → Sonnet **miss** |

The 5–2 split is therefore not noise, and it is not two instances of "the LLM is better or worse." It is two
different mechanisms pulling in opposite directions: callsign resolution across transmissions, which only the
windowed LLM does, and reservation supersession by invented events, which only the LLM suffers. Recording 3271 is
the §5 suppression finding occurring unprompted — an invented clearance converting a real conflict into a
compatible pair, with no alert raised to notice.

**Negatives — 4 of 309 (all UWB-ATCC; verdicts from adjudication sheet A)**

The fourth is recording 261, which §2's strip fix newly surfaces and which no one has adjudicated yet: Sonnet
extracts a `TAKEOFF` on 13 and a `LAND` on 31 — a departure and an arrival from opposite ends of one strip, which
`OPPOSITE_MATRIX` rates `alert`. It is the clearest worked example of the fix in the corpus. Recording 352 carries
the second unadjudicated alert. `evaluate.false_alarm_units` refuses to return a rate while any alert lacks a
verdict, which is why `conflict-eval.md` prints `pending`; §4.2 reports the interval anyway, bounded by the
sensitivity analysis below.

| Rec | Rwy | What the rules parser did | What Sonnet did | Verdict | Reading |
|---|---|---|---|---|---|
| 74 | 31 | two `warning`s, both callsigns **blank** | one `alert`, both aircraft named | `missing_release` | Sonnet is *more* accurate; accuracy crosses the alert threshold |
| 242 | 31 | nothing | `alert`, csa nine six one vs swiss one two five victor | `parse_error` | the only true hallucination in the Sonnet arm |
| 533 | 13 | `alert` — *austrian seven one two zulu* vs *ausrtian seven one two zulu* | nothing | `missing_release` | a transcript typo read as two aircraft; the regex flags one aircraft against itself |

Two of the three false-alarm divergences are not extraction errors in the sense the comparison is usually read:
74 is Sonnet being right about identity, and 533 is the rules parser being defeated by a misspelling. Only 242 is
an invented conflict.

---

### A2. All 25 divergent positives across four arm pairs

Produced by `scripts/cross_arm_replication.py`, which classifies each divergence from the two parties to the
conflict: the arriving clearance, and whatever the engine already holds open on that runway. `identity_holder`
means the arms differ on whether the aircraft already holding the runway is named — which requires carrying
identity across transmissions. `identity_trigger` means they differ on the callsign of the arriving clearance
itself, which requires no memory. `supersession` means the arm that missed gave one aircraft two kinds of hold, so
the later invented one rewrote the earlier. Runway state is taken from folding the stored events through
`engine.apply`, not from scanning the event list, so a released or stale reservation is never counted as a holder.

### Every divergent positive, by recording

| Comparison | Rec | Rwy | Caught by | Mechanism |
|---|---:|---:|---|---|
| rules vs Sonnet 5 / gold | 3223 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / gold | 3230 | 31 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / gold | 3242 | 31 | rules | `supersession` |
| rules vs Sonnet 5 / gold | 3246 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / gold | 3250 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / gold | 3260 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / gold | 3271 | 31 | rules | `supersession` |
| rules vs Haiku 5.5 / gold | 3223 | 13 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / gold | 3242 | 31 | rules | `supersession` |
| rules vs Haiku 5.5 / gold | 3246 | 13 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / gold | 3260 | 13 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / gold | 3291 | 13 | rules | `identity_trigger` |
| rules vs Sonnet 5 / ASR | 3223 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / ASR | 3230 | 31 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / ASR | 3242 | 31 | rules | `supersession` |
| rules vs Sonnet 5 / ASR | 3246 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / ASR | 3250 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / ASR | 3260 | 13 | Sonnet 5 | `identity_holder` |
| rules vs Sonnet 5 / ASR | 3271 | 31 | rules | `supersession` |
| rules vs Sonnet 5 / ASR | 3286 | 31 | Sonnet 5 | `identity_trigger` |
| rules vs Haiku 5.5 / ASR | 3223 | 13 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / ASR | 3230 | 31 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / ASR | 3242 | 31 | rules | `supersession` |
| rules vs Haiku 5.5 / ASR | 3246 | 13 | Haiku 5.5 | `identity_holder` |
| rules vs Haiku 5.5 / ASR | 3260 | 13 | Haiku 5.5 | `identity_holder` |

### Divergent negatives, by recording

| Comparison | Rec | False alarm on | Verdict |
|---|---:|---|---|
| rules vs Sonnet 5 / gold | 74 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / gold | 242 | Sonnet 5 only | `parse_error` |
| rules vs Sonnet 5 / gold | 533 | rules only | `missing_release` |
| rules vs Haiku 5.5 / gold | 74 | Haiku 5.5 only | `missing_release` |
| rules vs Haiku 5.5 / gold | 242 | Haiku 5.5 only | `parse_error` |
| rules vs Haiku 5.5 / gold | 261 | Haiku 5.5 only | `parse_error` |
| rules vs Haiku 5.5 / gold | 533 | rules only | `missing_release` |
| rules vs Sonnet 5 / ASR | 242 | Sonnet 5 only | `parse_error` |
| rules vs Sonnet 5 / ASR | 1969 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / ASR | 2306 | Sonnet 5 only | `parse_error` |
| rules vs Haiku 5.5 / ASR | 242 | Haiku 5.5 only | `parse_error`, `parse_error` |
| rules vs Haiku 5.5 / ASR | 261 | Haiku 5.5 only | `parse_error` |
| rules vs Haiku 5.5 / ASR | 1065 | Haiku 5.5 only | `parse_error` |

---

## Appendix B — The LaGuardia replay and the single-digit runway blind spot

The transmissions below are paraphrased from published reporting of NTSB preliminary report DCA26MA161 and
normalised to the corpus convention (lower case, digits as words). They are a reconstruction, not a transcript: the
NTSB docket transcript should replace them when the ATC Group Chair's factual report is released. The conclusion
does not depend on the exact wording, only on the runway designator.

### B0. The full pattern catalogue, verbatim

§2.2.1 summarises this. This is the complete set the scored baseline matches against. **Every number reported in §4
was scored against the `v1` catalogue below**, which is reproduced first because that is what the numbers mean:

```python
_SIDE = r"(?: left| right| centre| center)?"
RUNWAY_RE = re.compile(rf"\brunway ({D} {D}{_SIDE})\b")
INSTRUCTION_RES = [   # kind, phrase regex. CROSS / HOLD_SHORT capture their runway directly.
    ("LAND", re.compile(r"\bclear(?:ed)? to land\b")),
    ("TAKEOFF", re.compile(r"\bclear(?:ed)? (?:for|to) take ?off\b")),
    ("LUAW", re.compile(r"\bline up\b")),
    ("CROSS", re.compile(rf"\b(?:cross|crossing) runway ({D} {D}{_SIDE})\b")),
    ("HOLD_SHORT", re.compile(rf"\bhold(?:ing)? short(?: of)?(?: runway)? ({D} {D}{_SIDE})\b")),
]
HANDOFF_RE = re.compile(r"\bcontact (?:[a-z]+ ){0,2}?(ground|apron|departure|tower|approach|radar)\b")
GO_AROUND_RE = re.compile(r"\bgo around\b")
```

**The source as it now stands differs textually and not behaviourally** (`VERSION = "v3"`). The designator is built
from a reusable fragment so the US convention can be selected per airport (§7), and `"oh"` is accepted for the zero
digit-word:

```python
_D_RWY = rf"(?:{D}|oh)"
_DESIG = rf"{_D_RWY} {_D_RWY}{_SIDE}"            # the default: two digit-words, as v1 required
_DESIG_SINGLE = rf"{_D_RWY}(?: {_D_RWY})?{_SIDE}"   # opt-in, for an airport that speaks one ("runway four left")
RUNWAY_RE = re.compile(rf"\brunway ({_DESIG})\b")
RUNWAY_RE_SINGLE = re.compile(rf"\brunway ({_DESIG_SINGLE})\b")
INSTRUCTION_RES = _instruction_res(_DESIG)           # same five kinds as above, built for each convention
INSTRUCTION_RES_SINGLE = _instruction_res(_DESIG_SINGLE)
```

The equivalence is measured, not asserted: parsing every transcript in the corpus under the `v1` catalogue and under
the current default gives **0 differences across all 22,956 transcripts** (17,039 gold, 5,917 ASR), in all three
context modes, for both `parse` and `count_unresolved`. `"oh"` never occurs in the corpus, and `_DESIG` requires two
digit-words exactly as `v1` did, so the §4 numbers are unaffected by the change. `_DESIG_SINGLE` is reached only
through `parse_rules.make_parser(single_digit_runways=True)`, which no scored arm uses — the scored path constructs
no such parser, so no number in §4 can depend on it.

Five pattern families, one event kind each except `RUNWAY_RE`, which every runway-bearing phrase (`CROSS`,
`HOLD_SHORT`, and the `LAND`/`TAKEOFF`/`LUAW` phrases via the fallback described in §2.2.1) shares. `D` is the
shared digit-word vocabulary (`atcdb/readback.py`) — the reason B1–B3 below exists is that `D {D}` requires two
digit-words, so a single-digit designator never matches any of these five patterns at all. No pattern here does
conditional clauses, two-aircraft calls, or non-edge callsigns either; those gaps are documented in the module
itself (§2.2.1) but not demonstrated case-by-case the way the designator gap is in B1–B4.

**The callsign heuristic, verbatim.** §2.2.1 and §4.3 both rely on this coming back blank rather than wrong; this
is the actual mechanism, not the simplified "scan before/after" gloss an earlier draft of §2.2.1 used:

```python
def is_id(word: str) -> bool:
    """Digit or NATO-letter word: the identifying part of a callsign."""
    return word in DIGITS or word in NATO

def take_prefix(words: list[str]) -> list[str]:
    """Callsign at the start of `words`: leading filler dropped, then up to 2 name words + id tokens, stopping at
    the first other word. [] unless at least one id token is present."""
    i = 0
    while i < len(words) and words[i] in FILLER:
        i += 1
    out: list[str] = []
    names = 0
    for w in words[i:]:
        if is_id(w):
            out.append(w)
        elif not any(is_id(x) for x in out) and names < 2 and w not in FILLER:
            out.append(w)
            names += 1
        else:
            break
    return out if any(is_id(w) for w in out) else []
```

`controller_callsign` tries `take_prefix` on the words before the matched phrase first, then the words after; `blank_values` first replaces every readback value (runway, frequency, level, heading, squawk) in the transcript with spaces, so a value already consumed by `RUNWAY_RE` or the others cannot also be misread as part of a callsign. `take_prefix` returns `[]` — an empty callsign — whenever no NATO-alphabet or digit word is found at all, which is the `identity (holder)` mechanism §4.3 reports in 17 of 25 divergent cases.

### B1. The LaGuardia sequence under the rules parser

| # | Speaker | Transmission (normalised) | Rules-parser events |
|---|---|---|---|
| 1 | controller | air canada eight six four six runway four cleared to land | **none** |
| 2 | pilot | cleared to land runway four air canada eight six four six | `READBACK` callsign=`air canada eight six four six` |
| 3 | controller | truck one and company cross runway four at delta | **none** |
| 4 | controller | stop stop stop truck one stop stop stop | **none** |

No reservation is opened, so no conflict is raised at any step.

### B2. Single-digit runway designators: the same clearance, two phrasings

| Spoken designator | Rules-parser event | `normalize_runway` |
|---|---|---|
| "runway one" | **none** | `01` |
| "runway two" | **none** | `02` |
| "runway three" | **none** | `03` |
| "runway four" | **none** | `04` |
| "runway five" | **none** | `05` |
| "runway six" | **none** | `06` |
| "runway seven" | **none** | `07` |
| "runway eight" | **none** | `08` |
| "runway nine" | **none** | `09` |

| Control: two-token designator | Rules-parser event |
|---|---|
| "runway zero four" | `LAND` rwy=04 |
| "runway one three" | `LAND` rwy=13 |
| "runway three one" | `LAND` rwy=31 |
| "runway one eight left" | `LAND` rwy=18L |

### B3. Why this happens, and what it means for the reported numbers

The parser's phrase patterns require a two-token runway designator, while its own `normalize_runway` helper accepts
one-token forms correctly. The two disagree, and only the helper matches phraseology: ICAO designators 01–09 are
spoken as a single word in normal use. The blind spot therefore affects any clearance for runways 1 through 9, for
every event kind, on both transcript kinds.

Three consequences, stated precisely:

1. **The reported recall is not wrong, but it is narrower than it appears.** All 98 scored positives are on runways
   13 and 31, and 97% of all extracted events in the corpus carry those two designators, so no number in §4 changes.
2. **The phrasing does occur in this corpus**, in 110 of 22,956 transcripts (73 gold, 37 ASR). Of the 17 that also carry
   a clearance phrase, most are truncated recordings — "line up runway three o", "hold short of runway one t" —
   where a two-token designator was clipped mid-word rather than a genuine single-digit clearance. We therefore do
   not claim a count of real missed clearances in this corpus.
3. **It is a known limitation of the scored baseline, not a hidden one.** The parser's module docstring already
   flags several blind spots (§2.2.1); this one was not among them until the case studies below found it. A
   one-line relaxation of the designator pattern, and a scan for related phraseology conventions ("oh" for "zero";
   ICAO's alternate numeral words, which do not occur anywhere in this corpus), are named as the next test in §7
   rather than adopted here — a free diff against the full corpus shows the relaxation also misreads some clipped
   two-digit recordings as a genuine single-digit designator, so it is not a strict improvement without further
   checking.

### B4. A second real case, two ways: JFK 2023 under both clearance orderings

§4.5 reports JFK (NTSB DCA23LA125) as a counterexample — a crossing clearance on 31L and a takeoff clearance on 4L,
both correctly spoken, the aircraft simply crossed the wrong runway. "Runway four left" repeats the single-digit
designator gap from B1–B3, and because this case involves two *different* runways rather than one, the bug's effect
on the outcome depends on the order the two clearances are spoken in. Both orderings are consistent with the public
timeline's level of precision, so both are reported.

**Under the rules parser, as scored throughout §4.**

*Ordering 1 — Delta's takeoff clearance first (the historically likely order: Delta had already begun its takeoff
roll when American crossed):*

| # | Speaker | Transmission (normalised) | Rules-parser event |
|---|---|---|---|
| 1 | controller | delta one niner four three runway four left cleared for takeoff | **none** (designator gap; no active runway to fall back to) |
| 2 | pilot | cleared for takeoff four left delta one niner four three | `READBACK` |
| 3 | controller | american one zero six cross runway three one left at kilo | `CROSS` rwy=31L |
| 4 | pilot | cross three one left at kilo american one zero six | `READBACK` |

No reservation is ever opened for Delta, so the crossing clearance has nothing to conflict with. **No alert, correct
outcome, wrong reason**: the parser did not determine the two runways are different; it never represented Delta's
clearance at all.

*Ordering 2 — American's crossing clearance first:*

| # | Speaker | Transmission (normalised) | Rules-parser event |
|---|---|---|---|
| 1 | controller | american one zero six cross runway three one left at kilo | `CROSS` rwy=31L |
| 2 | pilot | cross three one left at kilo american one zero six | `READBACK` |
| 3 | controller | delta one niner four three runway four left cleared for takeoff | `TAKEOFF` rwy=**31L** (fallback to the one active runway, §2.2.1) |
| 4 | pilot | cleared for takeoff four left delta one niner four three | `READBACK` |

Step 3 raises a `RUNWAY` **alert** between Delta and American on runway 31L — a false alarm invented by the
designator gap, between two aircraft that were in fact cleared for different runways.

**Reading the pair.** The same gap, applied to the same two real clearances, produced either a correct silence or a
false alert depending on which controller instruction came first — a property of parsing order, not of whether the
runways actually conflicted. The scored parser cannot be read as a clean demonstration that it reasons correctly
about non-conflicting runways: on the order §4.5 presents, it happened to be silent for the right real-world answer
and the wrong mechanism; on the other order, it was wrong outright. This is the designator gap costing something on
a case the evaluated baseline was never scored against.

**The LLM extractor was also run on both orderings** (`claude-sonnet-5`, `window` context, billed on the spot
rather than cached, 2026-11-08): it reads "four left" as `04L` and "three one left" as `31L` correctly regardless
of order, raising no conflict either way. It never had this failure mode to begin with, which is exactly the
mechanism argued in §2.2.2 — an open-vocabulary extractor has no fixed-width pattern to fail on. This is one case,
reported as a confirmation of that mechanism, not as a scored result.

---

## Appendix C — The LLM extractor's prompt and tool schema

Reproduced verbatim from `atcdb/parse_llm.py`. Every LLM arm in this study used exactly this prompt and schema.
`parse_llm.VERSION` is bumped by hand whenever either changes and the events cache is keyed by it, so no cached
parse can silently belong to a different prompt. The model sees one transmission at a time and must answer with a
`report_events` tool call; `tool_choice` forces the call, so a prose reply is a parse failure rather than a result.

### C1. System prompt

```text
You read one radio transmission from an airport tower frequency and report its runway events with the report_events tool, in the order they are spoken. Report an empty list when there are none.

Event kinds:
- LAND, TAKEOFF, LUAW (line up and wait), CROSS (cross a runway), HOLD_SHORT: a controller's instruction to an aircraft about a runway. Give the runway.
- HANDOFF: the controller tells an aircraft to contact another frequency. Give `to`: ground, departure, tower or approach.
- READBACK: a pilot repeating an instruction back to the controller. Report one READBACK for the pilot's transmission, never the instructions it repeats: pilots do not issue instructions.
- VACATED: a pilot reporting that it has left the runway.
- GO_AROUND: an instruction to go around, or a pilot reporting one.
- NOOP: nothing relevant. You may leave it out.

Fields:
- callsign: the aircraft's callsign in the transcript's own words, lower case, for example "csa one two three". Use the same words for the same aircraft every time; the tracked aircraft, when shown, are the forms already in use. Use an empty string when no callsign is said.
- runway: the designator in digits with an optional L, R or C, for example "31" or "04L", or null. When an instruction names no runway and exactly one runway has an active clearance, use that runway.
- to: only for HANDOFF; otherwise null.

Report only what the transmission says.
```

### C2. Tool schema

```python
TOOL: dict[str, Any] = {
    "name": "report_events",
    "description": "Report every runway event in the transmission, in spoken order. An empty list means none.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"events": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(EVENT_KINDS)},
                "callsign": {"type": "string", "description": "lower-case words as spoken; empty if none"},
                "runway": {"anyOf": [{"type": "string"}, {"type": "null"}],
                           "description": "digits plus optional L/R/C, e.g. 31 or 04L; null if none"},
                "to": {"anyOf": [{"type": "string", "enum": list(HANDOFF_TARGETS)}, {"type": "null"}],
                       "description": "the frequency handed to; HANDOFF only"},
            },
            "required": ["kind", "callsign", "runway", "to"],
            "additionalProperties": False,
        }}},
        "required": ["events"],
        "additionalProperties": False,
    },
}
```

### C3. What `window` context adds

In `window` mode the user message carries, in addition to the transmission: the previous four transmissions with
their speaker roles, the callsigns the engine is currently tracking, and the runways with an active clearance. The
prompt's instruction that "when an instruction names no runway and exactly one runway has an active clearance, use
that runway" is the mechanism behind the `identity_holder` divergences in §4.3, and behind the Goa row in §4.5
where Sonnet carries runway 08 forward into a transmission that names no runway. Extended thinking is disabled and
reasoning effort is set to low; neither model accepts a `temperature` parameter, so sampling is not pinned and
reproducibility comes from the cache rather than from determinism (§2.2.2).

---

## Appendix D — The compatibility matrix and its doctrinal basis

### D1. The compatibility matrix, verbatim, with its doctrinal basis

Rows are the arriving event, columns the reservation already open for a *different* aircraft on that runway.

| new \ active | `LAND` | `TAKEOFF` | `LUAW` | `CROSS` |
|---|---|---|---|---|
| `LAND` | **ok** <br>(icao-4444-7.10.2-proviso) | **alert** <br>(icao-4444-7.10.1) | **alert** | **alert** |
| `TAKEOFF` | **alert** <br>(icao-4444-7.9.2) | **warning** | **alert** | **alert** |
| `LUAW` | **alert** | **warning** | **warning** | **warning** |
| `CROSS` | **alert** | **alert** | **warning** | **ok** |

3 of the 16 same-end cells carry a verified ICAO Doc 4444 citation in `MATRIX_BASIS`; the other 13 encode the
team's judgement. The 16 opposite-end cells (`OPPOSITE_MATRIX`) carry no citation at all by design — the ICAO
paragraphs cited describe same-direction traffic — so a majority of the alerts the engine now raises rest on the
team's reading rather than on doctrine.
A conflict in which either party's callsign is unknown is capped at `warning` by `apply`, whatever this matrix says.

### D2. Why the uncited cells matter

`MATRIX_BASIS` exists because the team decided early that a cell asserting what is or is not safe should name the
rule it encodes. Three cells do. The other 13 are design judgement, and two of them carry most of this report's
weight: `LUAW`×`TAKEOFF` = `warning` is why a line-up behind a departing aircraft is adjudicated `engine_rule`
rather than counted as a false alarm, and the callsign cap — any conflict with an unidentified party reduced to
`warning` — is what produces the `identity_holder` mechanism that accounts for 17 of the 25 divergences in
Appendix A2. Neither is wrong, but neither is doctrine, and both were chosen by two students without controller
training. §6.3 treats this as the clearest instance of the active responsibility gap in this project.

---

## Appendix E — Adjudication: verdicts, checklist, and agreement

An alert on a real recording is a *candidate* false alarm until a person judges it. Of the five verdicts, only
`parse_error` is one the choice of extractor can move; the rest describe the audio channel or the engine's framing.

### E1. The five verdicts

| Verdict | Means |
|---|---|
| `genuine` | it really is two clashing clearances |
| `parse_error` | the extractor misread a line |
| `missing_release` | the reading was right, but the line that would have freed the runway was never said |
| `other_frequency` | the reading was right, but the freeing line or the other aircraft was on a frequency not captured in this corpus (ground, apron) |
| `engine_rule` | the reading was right, but the conflict rules are too strict (for example a conditional clearance) |

### E2. The written four-step checklist

Reproduced verbatim from `data/labels/README.md` §3. It was agreed on 2026-11-02, after a first round scored
without it, and is deliberately mechanical because neither adjudicator is a controller.

**How to decide (agreed 2026-11-02; neither of us is a controller, so follow these steps rather than judging).**
`context` shows the whole recording up to the alarm. Read the lines above the `>>` line and stop at the first answer:

1. Above it, is a *different* plane cleared onto the *same* runway (`cleared to land`, `cleared for takeoff`, `line up`,
   `cross`)? **No:** `parse_error` (the system made up the second plane). If the `>>` line names no plane, it is for
   the plane the controller spoke to just before.
2. After that clearance, is that plane told or does it say `vacated`, `contact ground`, `contact departure`,
   `go around` or `hold short`? **Yes:** `parse_error` (the system missed the release).
3. Is the `>>` line a line-up (`line up`, `line up and wait`, `behind ... line up`)? **Yes:** `engine_rule` (the
   controller is queueing it on purpose; the rules count that as a conflict).
4. Otherwise `missing_release`, or `other_frequency` if the release was probably said on ground's frequency.

If no step fits, the adjudicator takes the closest verdict and begins `notes` with `none fits:`.

### E3. Agreement, and what produced it

| Round | Procedure | Alerts labelled by both | Agreement | Cohen's κ |
|---|---|---:|---:|---:|
| 1 | no checklist | 30 | 14 of 30 | **0.12** |
| 2 | written checklist | 31 | 27 of 31 | **0.80** |

Round 2 broken down by which step decided the row:

| Subset | n | Agreement | Cohen's κ |
|---|---:|---:|---:|
| Rows decided by checklist step 1 (near-mechanical) | 11 | 11 of 11 | **1.00** |
| All other rows | 20 | 16 of 20 | **0.62** |

Both rounds are reported because the difference between them is a finding about the construct and not only a
quality-control step: "false alarm" was not a reliable label until a procedure existed, and a meaningful part of
the improvement comes from the one step that requires least judgement. All four remaining disagreements are sheet A
`missing_release` against sheet B `parse_error`; sheet A was not revised after seeing sheet B.

---

## Appendix F — The 2026 reconstructions in full

Seven transmissions, reconstructed from published reporting into `data/labels/real_2026_cases_A.csv`; the `events`
column of that sheet is still unlabelled, so these are case studies and carry no rate (§4.5). The Sonnet column is
read from `data/eval/real_2026/events-claude-sonnet-5.json`, whose provenance is currently `transcribed` rather
than `api` (§7). Regenerate with `python scripts/real_2026_cases.py`.

### F1. Goa (VAGO), 3 April 2026 — backtrack incursion

| # | Speaker | Transmission (normalised) | Rules parser | Sonnet 5 |
|---|---|---|---|---|
| 1 | controller | taxi via november two hold at holding point runway zero eight | — | `HOLD_SHORT` 08 |
| 2 | controller | hold at holding point and contact navy approach one one niner decimal seven at the holding point | `HANDOFF` approach [one one niner] | `HOLD_SHORT` 08; `HANDOFF` approach |
| 3 | pilot | taxi via november two for runway zero eight | `READBACK` | `READBACK` |
| 4 | controller | expect backtrack | — | — |
| 5 | pilot | entering runway | `READBACK` | — |

**Reservations opened: 0 on both arms**, so no conflict can be raised by either extractor.

### F2. Houston (KIAH), 24 April 2026 — callsign confusion

| # | Speaker | Transmission (normalised) | Rules parser | Sonnet 5 |
|---|---|---|---|---|
| 1 | controller | holding short november echo you need to listen to callsigns you followed two instructions that were not for you | — | — |
| 2 | controller | you are not listening to callsigns i said united not qatari you have been doing that all night long | — | — |

**Reservations opened: 0 on both arms**, so no conflict can be raised by either extractor.


### F3. What the two cases show

Neither case opens a reservation under either extractor, so the engine raises nothing. This is a property of the
engine's vocabulary, not of extraction: Goa is an aircraft entering a runway to backtrack, and Houston is a crew
acting on another aircraft's clearance. The engine represents exactly four reservation-opening kinds — `LAND`,
`TAKEOFF`, `LUAW`, `CROSS` — and neither event is an incompatible pair of runway clearances.

Three extractor differences appear and none changes the outcome. Sonnet reads "hold at holding point" as a
`HOLD_SHORT` where the rules parser's patterns do not; in row 2 it carries runway 08 forward from the previous
transmission, which names no runway, the same identity-resolution mechanism as §4.3; and the rules parser reads the
radio frequency "one one niner" as a callsign, an error of the same family as recording 533's misspelling. Sonnet
invented nothing on either case, which is a negative result for the completion mechanism of §2.2.2 on real text
(§4.5).

What neither extractor represents is the incursion itself: the pilot's "entering runway" in row 5 is the
safety-critical moment at Goa, and the engine has no event kind for an aircraft entering a runway other than via a
clearance it was issued.

---

## Appendix G — Consequence weighting in full

### G1. Method

One event in a recording's already-extracted event stream is edited, the stream is re-folded through the engine, and
the resulting alerts are compared with the original (`scripts/risk_score.py`,
[`risk-score.md`](results/risk-score.md)). Because it re-uses stored events, it requires no re-parsing and no API
call, which is why it can be run across every arm for free. Six perturbation kinds are generated, each editing
exactly one field of one event — except `dropped`, which removes an event, and the two `spurious` kinds, which
insert one.

### G2. Results

| Error kind | Changed the output | Lost a true detection | Created a false alarm |
|---|---:|---:|---:|
| `wrong_runway` | 23% | 27% | 6% |
| `dropped` (event removed) | 27% | 45% | **0%** |
| `wrong_type` | 24% | 26% | 8% |
| `wrong_callsign` | 19% | 13% | 9% |
| `spurious`, on a runway in use | 54% | 7% | **37%** |
| `spurious`, on the strip's other end | 71% | **0%** | **61%** |

*Rules arm, `window` context, gold transcripts, re-scored after §2's strip fix. All five structured gold arms agree
on which error kinds sit at the top and bottom of the ordering, as they should if these are properties of the engine
rather than of one extractor — but they do **not** agree on magnitude: the context-free rules arm puts
`wrong_runway`'s lost-detection rate at 33% against 49–54% elsewhere, and inverts the false-alarm ordering of
`wrong_type` and `wrong_callsign`. Read the ordering as the robust part and the percentages as specific to this arm
(`risk-score.md`).*

Percentages are rates per perturbation opportunity, not per recording: the denominator is the number of events of
the relevant kind available to perturb, which differs by row. They are therefore **not** convertible into a
per-extractor score without error counts from a properly sampled labelled set (§7).

### G3. The suppression row, stated plainly

`spurious` on a runway not in use is the row that matters most and reads most easily as a null result. It creates a
false alarm 37% of the time and still costs a true detection 7–11% of the time, because
a new reservation replaces whatever that aircraft already held, rewriting the *kind* of hold open and so the matrix
cell that would have been consulted. The failure produces no alert, no alarm, and no record. It is the only error
mode in this study that is invisible to every measure the study reports, and recording 3271 in Appendix A1 is an
instance of it occurring unprompted rather than by perturbation.

### G4. Caveats

The study edits one event at a time, so correlated errors are not modelled — an ASR digit failure that corrupts the
same runway across a whole recording is a single realistic fault that this method represents as several independent
ones. It also operates on an extractor's own event stream rather than on human gold events, because the
pre-registered event sheets were never labelled, so "lost a true detection" is measured against what that arm
originally produced rather than against ground truth.

---

## Appendix H — Reproducing every number in this report

Every command below reads committed files only. None needs the database, an API key, or any spend, with the single
exception noted. Use the project virtual environment (`.venv/bin/python`); the system interpreter lacks `jiwer` and
fails test collection.

| Table or claim | Command |
|---|---|
| §4.1 extraction table | `python scripts/score_pair_events.py` → [`extraction-pair-events.md`](results/extraction-pair-events.md) |
| §4.2 primary comparison, both transcript kinds | `python scripts/eval_conflicts.py report` → [`conflict-eval.md`](results/conflict-eval.md) |
| §4.3 contingency and failure taxonomy | same command; "case by case" lines in the same doc |
| §4.3 cross-arm replication and mechanism labels | `python scripts/cross_arm_replication.py --markdown` → [`cross-arm-replication.md`](results/cross-arm-replication.md) |
| §4.4 judge ablation | `python scripts/eval_conflicts.py report`; judge arms in the same table |
| §4.5 and Appendix F, the 2026 cases | `python scripts/real_2026_cases.py` |
| §4.5 Austin and Prague | `python scripts/pilot_cases.py --dry-run` to price, then without the flag (**billed**; Austin is not in the corpus so its parses are not cached) |
| §5 and Appendix G, consequence weights | `python scripts/risk_score.py` → [`risk-score.md`](results/risk-score.md) |
| Appendix A1, the ten divergent cases | `python scripts/divergent_cases.py` |
| Appendix B1-B2, the LaGuardia replay and designator test | the snippet in B1–B2; `atcdb.parse_rules.parse` on the normalised lines |
| Appendix B3's candidate-fix spot-check | a diff of the relaxed designator pattern against the scored one, over all gold transcripts; free, no API |
| Appendix B4, the JFK case under both orderings | the same replay snippet as B1, with the four JFK lines in each order, folded through `atcdb.engine.apply` |
| Appendix E, the κ figures | `python scripts/eval_conflicts.py adjudicate --kappa` |
| §2.1 word error rate | `python scripts/score_wer.py` → [`wer-baseline.md`](results/wer-baseline.md) |
| The full test suite | `.venv/bin/python -m pytest -q` — 426 pass; the two `tests/test_asr.py` failures need a GPU module this machine lacks |

`data/atc.sqlite` is required only to re-run a paid arm or to regenerate transcripts; it is not on `main` because
of its size. Install it with
`git cat-file -p origin/runway-watch-app:data/atc.sqlite > data/atc.sqlite`. If `eval_conflicts.py report` ever
prints `recall: n/a over 0 positives`, the database has lost its injections and its output must not be committed.

---

## References

### Academic sources

Chang, Y., Guleria, Y., Pham, D.-T., Pham, N.-H., Wang, N., Duong, V. N., & Alam, S. (2026). Safety-oriented
evaluation of language understanding systems for air traffic control. *arXiv preprint* arXiv:2605.11769.

Deng, Q., Zhang, M., Yang, Y., & Gao, Z. (2026). SCOPE: A lightweight-training LLM framework for air traffic
control readback monitoring. *arXiv preprint* arXiv:2605.29543.

Fischer, J. M., & Ravizza, M. (1998). *Responsibility and Control: A Theory of Moral Responsibility.* Cambridge
University Press. (Cited via Santoni de Sio & van den Hoven, 2018, for the reason-responsiveness and ownership
conditions on guidance control.)

Helmke, H., Ondřej, K., Shetty, S., Arilíusson, H., Simiganoschi, T. S., Kleinert, M., Ohneiser, O., Ehr, H.,
Zuluaga-Gomez, J., & Smrz, P. (2022). Readback error detection by automatic speech recognition and understanding:
Results of HAAWAII project for Isavia's enroute airspace. *SESAR Innovation Days 2022*, Budapest.

Matthias, A. (2004). The responsibility gap: Ascribing responsibility for the actions of learning automata.
*Ethics and Information Technology*, 6(3), 175–183.

Nozick, R. (1981). *Philosophical Explanations.* Harvard University Press. (Cited via Santoni de Sio & van den
Hoven, 2018, for the truth-tracking conditionals used in §6.2.)

Parasuraman, R., & Manzey, D. H. (2010). Complacency and bias in human use of automation: An attentional
integration. *Human Factors*, 52(3), 381–410. https://doi.org/10.1177/0018720810376055

Ruskin, K. J., Corvin, C., Rice, S., Richards, G., Winter, S. R., & Clebone Ruskin, A. (2021). Alarms, alerts, and
warnings in air traffic control: An analysis of reports from the Aviation Safety Reporting System.
*Transportation Research Interdisciplinary Perspectives*, 12, 100502. https://doi.org/10.1016/j.trip.2021.100502

Santoni de Sio, F., & Mecacci, G. (2021). Four responsibility gaps with artificial intelligence: Why they matter
and how to address them. *Philosophy & Technology*, 34(4), 1057–1084.
https://doi.org/10.1007/s13347-021-00450-x

Santoni de Sio, F., & van den Hoven, J. (2018). Meaningful human control over autonomous systems: A philosophical
account. *Frontiers in Robotics and AI*, 5, Article 15. https://doi.org/10.3389/frobt.2018.00015

Wickens, C. D., Rice, S., Keller, D., Hutchins, S., Hughes, J., & Clayton, K. (2009). False alerts in air traffic
control conflict alerting system: Is there a "cry wolf" effect? *Human Factors*, 51(4), 446–462.
https://doi.org/10.1177/0018720809344720

Zuluaga-Gomez, J., Veselý, K., Szöke, I., Blatt, A., Motlicek, P., Kocour, M., Rigault, M., Choukri, K., Prasad,
A., Sarfjoo, S. S., Nigmatulina, I., Cevenini, C., Kolčárek, P., Tart, A., Černocký, J., & Klakow, D. (2023).
ATCO2 corpus: A large-scale dataset for research on automatic speech recognition and natural language
understanding of air traffic control communications. *arXiv preprint* arXiv:2211.04054v2.

### Official reports and standards

DOT Office of Inspector General. (2025, March 12). *FAA has taken steps to prevent and mitigate runway incursions,
but work remains to improve data analytics and implement key initiatives* (Report No. AV2025026). U.S. Department
of Transportation. — Figure 3 and surrounding text, p. 5: of 1,758 fiscal-year-2024 runway incursions, 62% were
pilot deviations, 17.9% operational incidents and 17.4% vehicle/pedestrian deviations; of the nine Category A and B
incursions that year, four (44%) were pilot deviations and three (33%) operational incidents. Exhibit D, pp. 36–37,
lists all 47 Category A and B incursions since the start of fiscal year 2022; of these, 10 of the 17 Category A
events (59%) are operational incidents, transcribed in
[`docs/incidents/ab-incursions-fy2022-2024.csv`](incidents/ab-incursions-fy2022-2024.csv).

International Civil Aviation Organization. (2016). *Procedures for Air Navigation Services — Air Traffic
Management* (PANS-ATM, Doc 4444), 16th ed. — §7.9.2, §7.10.1 and the §7.10.2 proviso are the three provisions
cited in the engine's compatibility matrix (Appendix D).

National Transportation Safety Board. (2023). *Runway incursion and collision, Austin-Bergstrom International
Airport* (Aviation Investigation Report AIR-24-02; investigation DCA23FA149).
https://www.ntsb.gov/investigations/AccidentReports/Reports/AIR2402.pdf

National Transportation Safety Board. (2024). *Runway incursion involving American Airlines flight 106 and Delta
Air Lines flight 1943, John F. Kennedy International Airport* (Investigation DCA23LA125; abstract released 4 June
2024). https://www.ntsb.gov/investigations/Pages/DCA23LA125.aspx ; press release
https://www.ntsb.gov/news/press-releases/Pages/NR20240604a.aspx

National Transportation Safety Board. (2026). *Jazz Aviation, Air Canada Express flight 8646 collides with fire
truck on LaGuardia runway* (Investigation DCA26MA161; preliminary report released 23 April 2026, investigation
ongoing). https://www.ntsb.gov/investigations/Pages/DCA26MA161.aspx — the facts in §1 and §6.4 are taken from
published reporting of this preliminary report rather than from the report itself, which is not held locally;
see §7.

### Datasets and models

Zuluaga-Gomez, J. (n.d.). *UWB-ATCC corpus* [Data set]. https://huggingface.co/datasets/Jzuluaga/uwb_atcc —
free for research (University of West Bohemia); transcript text is not redistributed in this repository.

Zuluaga-Gomez, J. (n.d.). *ATCO2 corpus, one-hour test set* [Data set].
https://huggingface.co/datasets/Jzuluaga/atco2_corpus_1h — MIT licence (free subset).

`whisper-medium.en-atc`, CTranslate2 conversion `jacktol-ct2`, run through `faster-whisper`. Scored at 13.0% word
error rate on 2,927 transmissions of this corpus ([`wer-baseline.md`](results/wer-baseline.md)); its fine-tuning
split overlaps 80% of the recordings used here (§2.1, §7).

### Incident reporting used for the 2026 reconstructions

The Aviation Herald. (2026). *Accident: Goa, 3 April 2026* — avherald.com/h?article=5464af5a. Source for the five
Goa transmissions in Appendix F1.

The Aviation Herald. (2026). *Incident: Houston, 24 April 2026* — avherald.com/h?article=5388a27c. Source for the
two Houston transmissions in Appendix F2.

Both reconstructions are paraphrases of published quotations, not transcripts; they are reported as case studies
without a rate (§4.5) and their `events` column is unlabelled (§7).
