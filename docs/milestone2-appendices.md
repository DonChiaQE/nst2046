# Milestone 2 — Appendices

*Companion to the NST2046 Milestone 2 report, "Listening for Contradictions" (Don Chia, Jennifer Liu). Appendices do not count toward the page limit.*

Appendices do not count toward the page limit. Everything below is derived from material committed to the
repository, and Appendix H gives the command that regenerates each one. No appendix reproduces UWB-ATCC transcript
text, which the corpus licence does not permit us to redistribute (`decisions.md`, 2026-09-26); where a case needs
its wording, the text is NTSB public record, published incident reporting, or invented.

## Contents

| | Appendix | What it contains | Supports |
|---|---|---|---|
| **A** | Every divergent case, rules vs Sonnet 5 | All eleven gold-transcript disagreements (seven positives, four negatives) with the events each arm extracted, then all 25 divergent positives across four arm pairs with mechanism labels | §4.2 |
| **B** | The LaGuardia replay and the single-digit runway blind spot | The scored pattern catalogue and callsign heuristic verbatim, the opening incident run through the rules parser step by step, the designator test that explains the result, and a second real case (JFK) under both clearance orderings | §1, §2.2.1, §4.5, §7.2 |
| **C** | The LLM extractor's prompt and tool schema | The system prompt and JSON schema verbatim, the only place the model's instructions are fully visible | §2.2.2 |
| **D** | The compatibility matrix and its doctrinal basis | All 16 same-end cells plus the 16 opposite-end cells, with their ICAO citation or the absence of one | §2.3, §6.3 |
| **E** | Adjudication: verdicts, checklist, and agreement | The five verdicts, the written four-step procedure, the κ breakdown by step, and the context-window exposure that revised four verdicts | §3.3.2, §4.2, §6.1 |
| **F** | The 2026 reconstructions in full | All seven transmissions of the Goa and Houston cases with both arms' events | §4.5 |
| **G** | Consequence weighting in full | Every perturbation kind, the method, and its caveats | §4.3, §5 |
| **H** | Reproducing every number in this report | One command per table | §3 |
| **I** | AI-use log | Every case where AI output was used, rejected or changed, and how it was checked | §8 |
| **J** | Decision log | Every project decision with its reason, evidence and owner | §8 |
| **K** | Contribution statement | Each member's intellectual and practical work | §8 |

---

## Appendix A — Every divergent case, rules vs Sonnet 5

### A1. The eleven gold-transcript disagreements, with extracted events

All eleven recordings on which the primary pair disagrees. **Events and callsigns only, no transcript text.** "Trigger"
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
the §4.3 suppression finding occurring unprompted, an invented clearance converting a real conflict into a
compatible pair, with no alert raised to notice.

**Negatives — 4 of 309 (all UWB-ATCC; verdicts from adjudication sheet A)**

The fourth is recording 261, which §2's strip fix newly surfaces: Sonnet extracts a `TAKEOFF` on 13 and a `LAND` on
31, a departure and an arrival from opposite ends of one strip, which `OPPOSITE_MATRIX` rates `alert`. It is the
clearest worked example of the fix in the corpus. It was first adjudicated `parse_error`, since Sonnet read the
landing designator as 31 where it was 13, but on one strip that misreading does not cause the alert: the departing
aircraft's takeoff clearance on the same strip was never followed by a release, so the verdict is `missing_release`
(revised 2026-11-08, Appendix E4). (The fix's other new alert, on
recording 352, is raised by Haiku rather than Sonnet and is discussed in §4.2.)

| Rec | Rwy | What the rules parser did | What Sonnet did | Verdict | Reading |
|---|---|---|---|---|---|
| 74 | 31 | two `warning`s, both callsigns **blank** | one `alert`, both aircraft named | `missing_release` | Sonnet is *more* accurate; accuracy crosses the alert threshold |
| 242 | 31 | nothing — misses the other aircraft's clearance outright | `alert`, csa nine six one vs swiss one two five victor | `missing_release` | Sonnet extracts a real clearance the rules parser misses entirely; no release was transmitted for either aircraft |
| 261 | 31 | nothing | `alert`, csa seven three charlie vs speed bird eight six one | `missing_release` | a designator misread on the same strip, which does not change the conflict; no release was transmitted |
| 533 | 13 | `alert` — *austrian seven one two zulu* vs *ausrtian seven one two zulu* | nothing | `missing_release` | a transcript typo read as two aircraft; the regex flags one aircraft against itself |

None of the four false-alarm divergences is an invented conflict. In 74, 242 and 261 Sonnet extracts clearances the
rules parser misses or leaves anonymous, and the alert follows from a release that was never transmitted. In 533 the
rules parser is defeated by a misspelling.

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
| rules vs Sonnet 5 / gold | 242 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / gold | 261 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / gold | 533 | rules only | `missing_release` |
| rules vs Haiku 5.5 / gold | 74 | Haiku 5.5 only | `missing_release` |
| rules vs Haiku 5.5 / gold | 242 | Haiku 5.5 only | `missing_release` |
| rules vs Haiku 5.5 / gold | 261 | Haiku 5.5 only | `missing_release` |
| rules vs Haiku 5.5 / gold | 352 | Haiku 5.5 only | `parse_error` |
| rules vs Haiku 5.5 / gold | 533 | rules only | `missing_release` |
| rules vs Sonnet 5 / ASR | 242 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / ASR | 261 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / ASR | 1969 | Sonnet 5 only | `missing_release` |
| rules vs Sonnet 5 / ASR | 2306 | Sonnet 5 only | `parse_error` |
| rules vs Haiku 5.5 / ASR | 242 | Haiku 5.5 only | `missing_release`, `missing_release` |
| rules vs Haiku 5.5 / ASR | 261 | Haiku 5.5 only | `missing_release` |
| rules vs Haiku 5.5 / ASR | 1065 | Haiku 5.5 only | `parse_error` |

---

## Appendix B — The LaGuardia replay and the single-digit runway blind spot

The transmissions below are paraphrased from published reporting of NTSB preliminary report DCA26MA161 and
normalised to the corpus convention (lower case, digits as words). They are a reconstruction, not a transcript: the
NTSB docket transcript should replace them when the ATC Group Chair's factual report is released. The conclusion
does not depend on the exact wording, only on the runway designator.

### B0. The full pattern catalogue, as scored and as it now stands

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

**The callsign heuristic, verbatim.** §2.2.1 and §4.2 both rely on this coming back blank rather than wrong; this
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

`controller_callsign` tries `take_prefix` on the words before the matched phrase first, then the words after; `blank_values` first replaces every readback value (runway, frequency, level, heading, squawk) in the transcript with spaces, so a value already consumed by `RUNWAY_RE` or the others cannot also be misread as part of a callsign. `take_prefix` returns `[]` — an empty callsign — whenever no NATO-alphabet or digit word is found at all, which is the `identity (holder)` mechanism §4.2 reports in 17 of 25 divergent cases.

### B1. The LaGuardia sequence under the rules parser

| # | Speaker | Transmission (normalised) | Rules-parser events |
|---|---|---|---|
| 1 | controller | air canada eight six four six runway four cleared to land | **none** |
| 2 | pilot | cleared to land runway four air canada eight six four six | `READBACK` callsign=`air canada eight six four six` |
| 3 | controller | truck one and company cross runway four at delta | **none** |
| 4 | controller | stop stop stop truck one stop stop stop | **none** |

No reservation is opened, so no conflict is raised at any step.

**The same four lines with the US single-digit option on** (`parse_rules.make_parser(single_digit_runways=True)`, run
2026-11-08, free, no API call):

| # | Rules-parser events | Engine |
|---|---|---|
| 1 | `LAND` callsign=`air canada eight six four six` rwy=04 | reservation opened on 04 |
| 2 | `READBACK` | — |
| 3 | `CROSS` callsign=`truck one` rwy=04 | **`RUNWAY` alert** on 04: crossing against an open landing clearance |
| 4 | none | — |

With the option on, the rules parser raises a full alert at the moment the truck is cleared to cross (§7.2).

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
2. **The phrasing does occur in this corpus**, in 110 of 22,956 transcripts (73 gold, 37 ASR). A minority of those
   also carry a clearance phrase, and reading them shows truncated recordings — "line up runway three o", "hold
   short of runway one t" — where a two-token designator was clipped mid-word rather than a genuine single-digit
   clearance. We therefore do not claim a count of real missed clearances in this corpus.
3. **It is a known limitation of the scored baseline, not a hidden one.** A blanket relaxation of the designator
   pattern was measured and rejected: on this corpus it misreads clipped two-digit designators as single-digit ones
   in all 110 transcripts it changes. The single-digit form is therefore an opt-in per airport (B0, §7.2), used only
   for the US case studies, and B1 shows it working on the LaGuardia sequence.

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
that runway" is the mechanism behind the Goa row in §4.5, and the list of tracked callsigns is what lets the LLM name the prior holder in the `identity_holder` divergences of §4.2,
where Sonnet carries runway 08 forward into a transmission that names no runway. Extended thinking is disabled and
reasoning effort is set to low; neither model accepts a `temperature` parameter, so sampling is not pinned and
reproducibility comes from the cache rather than from determinism (§2.2.2).

---

## Appendix D — The compatibility matrix and its doctrinal basis

### D1. Both compatibility matrices, with their doctrinal basis

Rows are the arriving event, columns the reservation already open for a *different* aircraft on that runway.

| new \ active | `LAND` | `TAKEOFF` | `LUAW` | `CROSS` |
|---|---|---|---|---|
| `LAND` | **ok** <br>(icao-4444-7.10.2-proviso) | **alert** <br>(icao-4444-7.10.1) | **alert** | **alert** |
| `TAKEOFF` | **alert** <br>(icao-4444-7.9.2) | **warning** | **alert** | **alert** |
| `LUAW` | **alert** | **warning** | **warning** | **warning** |
| `CROSS` | **alert** | **alert** | **warning** | **ok** |

Since §2's strip fix, a clearance is also checked against a reservation held from the **other end of the same
strip**, against a second matrix. It is identical except for the two cells that are legal only because both aircraft
move the same way — two landings, or two departures, from opposite ends are head-on:

| new \ active | `LAND` | `TAKEOFF` | `LUAW` | `CROSS` |
|---|---|---|---|---|
| `LAND` | **alert** *(was ok)* | **alert** | **alert** | **alert** |
| `TAKEOFF` | **alert** | **alert** *(was warning)* | **alert** | **alert** |
| `LUAW` | **alert** | **warning** | **warning** | **warning** |
| `CROSS` | **alert** | **alert** | **warning** | **ok** |

3 of the 16 same-end cells carry a verified ICAO Doc 4444 citation in `MATRIX_BASIS`; the other 13 encode the
team's judgement. None of the 16 opposite-end cells carries one, by design — the ICAO paragraphs cited describe
same-direction traffic, so `apply` attaches no basis to an opposite-end conflict rather than borrowing one. Across
every structured arm's stored events, 833 of 1,476 RUNWAY alerts (56%) carry no citation and 643 (44%) do, the
latter all from `icao-4444-7.10.1` (495) and `icao-4444-7.9.2` (148). So **most of the alerts this engine raises
rest on the team's reading rather than on doctrine**, and that share grew with the strip fix.
A conflict in which either party's callsign is unknown is capped at `warning` by `apply`, whatever these matrices say.

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

### E4. The context-window exposure, and what it moved

The sheet originally showed only a six-line context window above each alert, which hid earlier lines in 35 of the
94 alerts then on it; it now shows the whole recording up to the trigger. Of the 96 alerts now adjudicated, 23
have a clearance or release in the part that window hid. Three of these had been marked `parse_error` and were
re-walked against the checklist:
`242:RUNWAY:31:2055`, `242:RUNWAY:31:5199`, `261:RUNWAY:13:5923`, originally `parse_error` on the ground that no
other aircraft was cleared onto the runway, where the hidden line was exactly such a clearance with no release
following it. Under full context the checklist routes all three to `missing_release` (revised 2026-11-08; the
sheet records each original verdict and reason). A fourth, `261:RUNWAY:31:5923`, was reclassified separately:
step 1 asks whether a different aircraft was cleared onto *the same runway*, and since §2's strip fix the engine
treats 13 and 31 as one runway, so a takeoff clearance on 13 counts as exactly that, the only alert on the sheet
whose prior clearance names the reciprocal end rather than the same designator.

No rate, interval, or agreement figure in this report depends on these four: every verdict but `genuine` counts
as a false alarm, so moving between the four non-genuine causes cannot move a false-alarm rate, and none of the
four is in sheet B's 30% overlap, so κ = 0.80 is unaffected. What moved is the taxonomy (sheet A, 35/28/33 →
31/32/33 for `parse_error`/`missing_release`/`engine_rule`) and the per-arm `parse_error` counts, from 2 to 0 on
Sonnet gold and 3 to 1 on Sonnet ASR (§4.2). The remaining 20 exposed-but-unaffected rows were not individually
re-walked, so the taxonomy is accurate to within a few reclassifications between non-genuine causes, not exact.
Since all four corrections moved alerts *out of* `parse_error`, the uncorrected rows are if anything more likely
to overstate the extractor's contribution than to understate it.

---

## Appendix F — The 2026 reconstructions in full

Seven transmissions, reconstructed from published reporting into `data/labels/real_2026_cases_A.csv`; the `events`
column of that sheet is still unlabelled, so these are case studies and carry no rate (§4.5). The Sonnet column is
read from `data/eval/real_2026/events-claude-sonnet-5.json`, whose provenance is currently `transcribed` rather
than `api`. Regenerate with `python scripts/real_2026_cases.py`.

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
transmission, which names no runway, the same identity-resolution mechanism as §4.2; and the rules parser reads the
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

*Rules arm, `window` context, gold transcripts, re-scored after §2's strip fix. The Sonnet arm agrees within a few points; every other arm's
figures are in `risk-score.md`.*

Percentages are rates per perturbation opportunity, not per recording: the denominator is the number of events of
the relevant kind available to perturb, which differs by row. They are therefore **not** convertible into a
per-extractor score without error counts from a properly sampled labelled set.

### G3. The suppression row, stated plainly

`spurious` on a runway already in use is the row that reads most easily as a null result. It creates a
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
| §4.3 extraction table | `python scripts/score_pair_events.py` → [`extraction-pair-events.md`](results/extraction-pair-events.md) |
| §4.1 primary comparison, both transcript kinds | `python scripts/eval_conflicts.py report` → [`conflict-eval.md`](results/conflict-eval.md) |
| Whether any alert is unadjudicated, and what it could change | `python scripts/pending_sensitivity.py` — reports nothing outstanding as of 2026-11-08; if an engine or model change surfaces a new alert, it bounds the effect under every verdict that alert could receive. Free, no API |
| §4.2 contingency and failure taxonomy | same command; "case by case" lines in the same doc |
| §4.2 cross-arm replication and mechanism labels | `python scripts/cross_arm_replication.py --markdown` → [`cross-arm-replication.md`](results/cross-arm-replication.md) |
| §4.4 judge ablation | `python scripts/eval_conflicts.py report`; judge arms in the same table |
| §4.5 and Appendix F, the 2026 cases | `python scripts/real_2026_cases.py` |
| §4.5 Austin and Prague | `python scripts/pilot_cases.py --dry-run` to price, then without the flag (**billed**; Austin is not in the corpus so its parses are not cached) |
| §4.3 and Appendix G, consequence weights | `python scripts/risk_score.py` → [`risk-score.md`](results/risk-score.md) |
| Appendix A1, the eleven divergent cases | `python scripts/divergent_cases.py` |
| Appendix B1-B2, the LaGuardia replay and designator test | the snippet in B1–B2; `atcdb.parse_rules.parse` on the normalised lines |
| §7.2 and Appendix B3, the designator measurement | a diff of the relaxed designator pattern against the default, over all 22,956 transcripts (gold and ASR); free, no API. The default is verified identical to the frozen baseline across 66,273 comparisons — 22,956 transcripts × 3 context modes, `parse` and `count_unresolved` |
| Appendix B4, the JFK case under both orderings | the same replay snippet as B1, with the four JFK lines in each order, folded through `atcdb.engine.apply` |
| Appendix E, the κ figures | `python scripts/eval_conflicts.py adjudicate --kappa` |
| §2.1 word error rate | `python scripts/score_wer.py` → [`wer-baseline.md`](results/wer-baseline.md) |
| The full test suite | `.venv/bin/python -m pytest -q` — **430 pass, 2 skip, 0 fail**. The two skips are the live-app smoke tests, which skip without `ANTHROPIC_API_KEY`, so `env -u ANTHROPIC_API_KEY pytest` spends nothing |

`data/atc.sqlite` is required only to re-run a paid arm or to regenerate transcripts; it is not on `main` because
of its size. Install it with
`git cat-file -p origin/runway-watch-app:data/atc.sqlite > data/atc.sqlite`. If `eval_conflicts.py report` ever
prints `recall: n/a over 0 positives`, the database has lost its injections and its output must not be committed.

---

---

## Appendix I — AI-use log

Verbatim from [`docs/logs/ai-use.md`](logs/ai-use.md), plus the final row for the report itself.

| Tool + purpose | Input / request summary | Used, rejected or changed | Verification + effect |
|---|---|---|---|
| 2026-08-25. Claude Code: research on audio sources | Where can we legally get ATC audio while based in Singapore? | Used: build on free research corpora (jacktol/atc-dataset, from ATCO2-1h and UWB-ATCC) and ask LiveATC before any automated capture. Rejected: our own radio receiver, which needs an IMDA licence in Singapore. | Each claim links its source (IMDA rules, LiveATC terms of use) in `docs/2026-08-25-atc-capture-research.md` §1 and §4. Effect: the corpus database was built on jacktol/atc-dataset (commit 56f3855). |
| 2026-08-29. Claude Code: readback checkers | Build and score readback models (rules, logistic regression, BERT) | Changed how the result was read: the rules' 99.3% was not accepted as a result, because the test labels were derived from the same rules. Human-labelled sheets were made the real test. | `docs/results/readback-models-comparison.md` ("Reading this honestly"); commit 401d66f. Effect: carried into the engine spec as the "label-circularity caution" (spec 2026-09-12, Section 2). |
| 2026-09-14. Claude Code: architecture brainstorm | Options for a runway-conflict system | Used A: deterministic event-sourced engine, with the LLM limited to extraction. Rejected B: an LLM agent that holds runway state. Changed C (an end-to-end LLM judge) into an evaluation arm only. | Spec `2026-09-12-conflict-engine-design.md`, "Decisions locked" item 6. Sections 1 to 4 were approved one at a time on 2026-09-14 (commit f0f0bab). |
| 2026-09-15. Claude Code: engine core and its final whole-branch review | Reviewer subagent checked the phase 1 branch | Used three fixes: an empty parse left a permanent cache miss (now stored as a NOOP row); a conflict with an unknown callsign might be one aircraft against itself (now capped at warning); no way to clear stale window caches (`clear_events`). Rejected a parser-side fix (give an unknown callsign to the only active aircraft), because a wrong guess would overwrite another aircraft's reservation. | Commit 8705d51; plan `2026-09-15-conflict-engine-core.md`, "Phase-1 review carry-overs". The plan's code was first run in a scratchpad: 88 tests green (commit 2bd2e2d). |
| 2026-09-17. Claude Code: replay UI and its reviews | Reviewer subagents checked the phase 2 branch | Used fixes: two different parses racing on one cache entry could leave a mix of both; a missing database was silently created empty (now a 503 error); a failed recording-list fetch was not handled. Other findings were recorded as carry-overs for phase 3. | Commits 2df117c, b34ebf9; plan `2026-09-17-replay-ui.md`, "Phase-2 review carry-overs". Browser smoke run on the corpus (commit aa7c263); 155 tests (handoff 2026-09-18). |
| 2026-09-19. Claude Code: Claude parser design | The spec said both models run at temperature 0 | Changed: Sonnet 5 rejects `temperature` with a 400 error, so it runs with thinking disabled and effort "low". Reproducibility comes from the cache and a strict tool schema, not from temperature. | Spec addendum A.4 ("Section 2's temperature 0 is superseded"); commit 8e88943. |
| 2026-09-26. Claude Code: implementation plans | Plans for phases 2.5, 3a and 3b-1, written before any subagent ran them | Used only after a check: each plan's code was built in a scratchpad, then the repo was rebuilt from the plan text alone and compared. | Byte-identical rebuilds: phase 2.5 (commit f2edf2b; handoff 2026-09-26 "About the phase-2.5 plan"), 3a (handoff 2026-09-29-conflict-engine, "What phase 3a delivered"), 3b-1 with 285 tests (commit 215bfa0). |
| 2026-09-26. Claude Code: Austin 2023 test fixture | The spec said to hand-key the NTSB tower transcript and re-check it against the PDF | Changed: the fixture was generated from the PDF's text layer (`pdftotext -raw`), not retyped. | Handoff 2026-09-26, "About the phase-2.5 plan"; header of `tests/fixtures/austin_dca23fa149.txt`. A test requires the replay to raise a RUNWAY conflict on 18L (spec A.3.9). |
| 2026-09-27. Claude Code: engine tuning fix wave | Review of the phase 2.5 branch | Used fixes: `doctrine.seed` compared the whole shared table, so it rewrote every rule on each API request (f2c184c); a test scenario could never happen with the real parser (54e035d); a test left a database handle open (f24b96a). Changed Claude's own gloss of ICAO Doc 4444 §7.10.2 from "successive landing clearances are lawful" to "conditionally lawful", since the quoted text needs the first lander past the threshold (1f7ff65). | Commits listed; 183 tests after the fix wave (commit 854d283). The engine's gap (it does not model the threshold) is noted in the gloss. |
| 2026-09-27. Claude API (Haiku 4.5, Sonnet 5) as extractor: recorded replies | Six transmissions (Austin NTSB text or invented) sent to both models to record test fixtures | Kept as findings; the prompt was not tuned. Haiku turned the pilot's takeoff readback heading "one seven zero" into a new TAKEOFF clearance. Sonnet reported a READBACK but missed the callsign. Both parsed the landing clearance and the US callsigns that the rules parser drops. | Plan `2026-09-27-claude-parser.md` (recorded replies paragraph); tests pin these outputs (commit ce7e4c5); handoff 2026-09-29-conflict-engine, "Measured so far". Effect: any prompt change must bump `parse_llm.VERSION`. |
| 2026-09-27/28. Claude Code: Claude parser final review | Final whole-branch review of phase 3a | Used fixes: after a failed `window` parse, later parses were cached against incomplete engine state (now served from cache only, 7d1dacf); `--refresh` with `--recording` would delete paid Claude parses for every recording (now refused, e7da086); any model name was accepted, so rules output could be cached under a Claude model (6e11f8d); the API client's default 10-minute timeout (now 60 s, 6c98221). | Commits listed; the window-failure rule was added to spec A.4; 215 tests (commit 0457f4c). |
| 2026-09-29. Claude API as extractor: corpus recording 528 | Replay of recording 528 with both models, compared step by step with the rules parser | Recorded as findings. Sonnet reproduced the predicted false RUNWAY alert at step 17. Haiku avoided it only by inventing a "runway vacated" for Air France: right output for the wrong reason. Both models raised a READBACK alert at step 13 that the rules parser missed. | Handoff 2026-09-29-conflict-engine, "Measured so far" (one recording, so not a result). |
| 2026-09-29. Claude Code: conflict injection design | Make synthetic conflicts by editing real transcripts | Claude measured that text edits find only about 10 candidates (34 of 309 recordings hold two clearances) and proposed a fifth kind: splice two real recordings from the same airport. Used (user approved). | Plan `2026-09-29-evaluation-3b1.md`, "Decisions taken while planning (user-approved 2026-09-29)"; commit 215bfa0. Effect: seed 0 stores 100 positives, 92 of them splices (handoff 2026-10-01). |
| 2026-09-29. Claude Code: ASR leakage claim | The spec said 12 recordings are entirely in the ASR model's test split (about 0.23 h) and would be the ASR headline | Rejected after measuring: no recording is entirely test split. The headline was made recall-only. Claude's next estimate ("about 4%" of positives usable) was replaced by the measured 25 of 100. | Commits 320f1bb, 64a0ddf; 3b-1 spec §3 keeps a note of the wrong claim. |
| 2026-09-29. Claude Code: evaluation final review | Final whole-branch review of phase 3b-1 | Used fixes: partial transcripts could reach the parse and judge caches; injection could run before the originals had ASR; the ASR headline needed the gold arms beside it and a leakage share; `run --set` dropped the other set's rows; four caveats added to the report. | Commit f3a09d3. |
| 2026-09-29/30. Claude Code: ASR run step | Plan step `run_asr.py --split train`, "about 2 h CPU" | Changed: that command would transcribe all of the about 11,900 train clips (12 h or more), so Claude added `--replayable` to limit it to the 1,611 clips the evaluation needs. The time estimate was still wrong: the run took 4.9 h (about 10 s per clip, not 4.5 s). | Commit 5dc3f3f; handoff 2026-10-01, "Where things stand" row 1. |
| 2026-10-11. Claude API (Haiku 4.5, Sonnet 5) as extractor, checked against human labels | readback_sheet_A came back labelled with instruction events, not readback consistency. Claude converted the labels and scored both models on the 200 instructions (role context, gold transcripts, about $1). | Used as a supplementary check only (not a uniform sample; mostly approach/radar). Sonnet found all 32 labelled runway events; its 7 false positives were approach clearances (for example "cleared for ILS approach runway one three") read as LAND. Haiku also read "taxi to holding point" as line-up. Handoff scores were not used: the labeller marked only 36 of 92 "contact (frequency)" lines as handoffs. | Commit 2077939 (`scripts/score_pair_events.py`, `data/labels/pair_events_A.csv`); Claude Code memory note `conflict-engine-design-in-progress.md`, 2026-10-11 entry. |
| 2026-10-19. Claude Code: check of the injection after Milestone 1 feedback | Do the synthetic positives favour one extractor? | Claude re-read `atcdb/inject.py` and confirmed what the 2026-09-29 handoff had noted: every injected trigger is found by textbook-verb regexes ("cleared to land", "line up", "cross runway"), which favours the rules parser. To be reported as a bias, not changed. | `atcdb/inject.py` lines 43 to 46; memory note `milestone-2-feedback.md`. Consistent with the rules arm's 86 of 100 strict hits on gold (handoff 2026-09-29-evaluation, "Measured while building"). |
| 2026-10-19. Claude Code: cost of the evaluation run | Dry run of all 18 arms plus the judge: about $105 (handoff 2026-10-01). Claude recommended staging it. | Proposed, not yet decided: after the professor's feedback, Claude recommended the primary comparison only (rules vs Sonnet, window, gold and ASR, plus the judge), about $30 instead of about $105. | Handoff 2026-10-01, "Cost decision pending" (estimate good to about a factor of two); Claude Code session 2026-10-19 (not in the repo). |
| 2026-10-20. Claude Code: cost estimate | Cost of scoring Sonnet (window context) on the 200 labelled lines | Rejected: Claude had said "about $1"; the tool's dry run said $6.55, because window context must parse each recording from its start (1,828 transmissions in 191 recordings). Claude corrected the estimate and the user skipped that run for now. | `scripts/parse_events.py --dry-run` in the Claude Code session of 2026-10-20 (not in the repo). |
| 2026-10-20. Claude API (Sonnet 5) as extractor: the Milestone 1 pilot cases | Austin (NTSB transcript, from 0628:26) and Prague (recording 528) replayed under the rules parser and Sonnet, window context, gold transcripts (about $0.12) | Used to replace the predicted column. Confirmed: Sonnet extracts Austin's landing clearance and alerts at the conflicting takeoff clearance; both extractors raise the Prague false alarm. Changed a Milestone 1 claim: the rules parser does not stay silent at Austin, it warns 36 s late. New finding: Sonnet read "fedex is on the go" (a go-around) as a TAKEOFF. | `docs/results/pilot-cases.md`; `scripts/pilot_cases.py`. The rules output matches the existing Austin test (`tests/test_incidents.py`). |
| 2026-10-20. Rules parser vs Claude API, checked against human labels | The 2026-10-11 scoring extended to the rules parser on the same 200 instructions (role context; every parse cached, so free) | Used as a supplementary result. Runway events (32 labelled): rules found 30 and invented 0; Haiku 31 and 7; Sonnet 32 and 9. The rules parser missed "cleared for immediate takeoff". | `docs/results/extraction-pair-events.md`; `scripts/score_pair_events.py` (`--model rules`). |
| 2026-11-08. Claude Code: cross-arm replication of the divergence analysis | Extend Appendix A's case-by-case reading from rules vs Sonnet 5 on gold to all four rules-vs-LLM pairs on both transcript kinds, and classify each divergence's mechanism in code | Used after two corrections, both to Claude's own first implementation. The first classifier re-derived runway state by scanning the event list, which ignores that a hold-short, a `VACATED`, a go-around or a handoff releases a reservation; it agreed with the engine on all 50 lookups in this data by luck. Rewritten to fold the stored events through `engine.apply`. The second version then over-corrected with a kinds-equality guard that pushed 5 explained cases to `unclassified` | Output baselines for `divergent_cases.py`, `cross_arm_replication.py` and `risk_score.py` captured before the work and required byte-identical after; both errors were caught by that diff, not by reading. 16 tests, including the released-reservation case the first version got wrong. `docs/results/cross-arm-replication.md`; commit 752320f. |
| 2026-11-08. Claude Code: a draft claim checked against the new data | The draft said the divergence mechanism is "callsign resolution across transmissions, which only the windowed LLM does" | Rejected and corrected. Recording 3291 is the rules parser resolving a bare-numeric callsign (`two six two three`) that Haiku 5.5 leaves blank, so the regex catches a conflict the LLM only warns about: the mechanism is identity resolution, and which arm wins it varies by transmission. The hand reading had also merged two variants — the unresolved callsign sits on the prior holder in 17 of 25 divergences and on the conflicting clearance itself in 2, and only the former needs context | `cross-arm-replication.md` §3 per-recording table; report §4.3 rewritten. The engine's own condition (`apply` caps at warning when either party is unknown) is what makes both variants equivalent downstream. |
| 2026-11-08. Claude Code: shared-helper refactor | `load`, `caught` and `false_alarms` were byte-identical in `divergent_cases.py` and the new script; promote them to `atcdb/evaluate.py`, whose header states everything below `read_rows` is pure | Used, but the refactor introduced a regression: `detection` was dropped from `divergent_cases.py`'s imports while line 60 still calls it, which would have been a `NameError` on every run of a script the report's Appendix A cites | Caught by the pre-refactor output baselines, then fixed and re-diffed identical. 5 tests added to `tests/test_evaluate.py` for the promoted predicates. Commit 752320f. |
| 2026-11-08. Claude API (Sonnet 5) as extractor: the two 2026 real incidents | Goa (2026-04-03) and Houston (2026-04-24), reconstructed from published reporting into 7 transmissions, replayed under the rules parser and Sonnet 5, window context (about $0.02) | Used as a **negative** result: Sonnet invented nothing. "expect backtrack" and a pilot's "entering runway" are the lines most likely to invite a fabricated clearance, and no `TAKEOFF` or `LAND` was produced, so the §2 completion mechanism did not fire on this real text. Three differences all favour Sonnet: it reads the hold-short the regex misses, carries runway 08 across a transmission that names no runway, and declines to treat the frequency `one one niner` as a callsign where the rules parser does | `scripts/real_2026_cases.py`; report §4.5. Neither arm produces a runway reservation, so the finding is about the engine's four-kind vocabulary rather than either parser, and a test now asserts that. Commit 9ebee1e. |
| 2026-11-08. Claude Code: how to commit the Sonnet arm for the 2026 cases | The Sonnet output existed only as a run pasted into the session, so the keyless path had nothing to replay. Claude first declined to write the recording from that paste | Changed after the user pushed back, and the objection turned out to have an engineering answer rather than a refusal. The data is a real run; the risk was that a hand-seeded file is indistinguishable from one written against the API, and that the terminal view is lossy (it prints `runway or to`, so those fields must be inferred back). Resolved by adding a `provenance` field: `derive()` always stamps `api`, the committed file is stamped `transcribed`, and the script warns on every load until `--record` replaces it | Transcription checked by re-rendering the recording and diffing it against the pasted run byte-for-byte; the sheet supplies text and roles so only the events came from the paste. `test_a_transcribed_recording_is_announced_as_such`. Commit 9ebee1e. |
| 2026-11-08. Claude Code: audit of its own code against the repo's conventions | Asked to check the new scripts for alignment with the existing structure, then asked again whether the code was really correct | Used; the second pass found more than the first. Dead code Claude had itself orphaned (`describe()`, and the `Handoff`/`KINDS` imports only it used), an unused constant copied from `divergent_cases.py`, two overlong lines, a hardcoded date default where the repo generates one, a no-op `.replace()`, and a `taxonomy()` total that counted unadjudicated alerts into a sum with no column for them | All fixed and re-verified against the output baselines; `docs/results/cross-arm-replication.md` unchanged apart from its heading date format. An AST sweep for unused imports and unreferenced definitions reports both scripts clean. Commits 752320f, 9ebee1e. |
| 2026-11-08. Claude Code: fix the single-digit runway blind spot the report's own case studies had exposed | User pushed back on treating the gap as merely a US-specific curiosity and asked for a fix, plus whether other international phraseology conventions needed similar handling | Used. Changed `parse_rules`'s three runway-designator regexes (`RUNWAY_RE`, and the `CROSS`/`HOLD_SHORT` patterns) to make the second digit-word optional, matching what `normalize_runway` already accepted; bumped `VERSION` to `v3` rather than editing `v1` in place, since the module's own header says to bump it whenever a pattern changes and `v1`'s cached events are what every number in report §4 is scored against. Checked for other conventions: ICAO's alternate numeral words ("tree", "fower", "fife") do not appear anywhere in the 17,039-transcript gold corpus (only "niner", already handled, with 22 occurrences), so no further change was made there | 25 existing `test_parse_rules.py` cases plus 51 more across `test_evaluate.py`/`test_cross_arm_replication.py` still pass. Replayed the LaGuardia and both JFK clearance orderings directly against the patched code: LaGuardia now correctly alerts, and JFK no longer flips between silent and a false alarm depending on clearance order. Checked against the gold transcripts for regressions. **This check was later found to be wrong and too narrow** (re-measured 08 Nov 2026): the change alters 9 rows over 8 distinct transmissions, not 6; "17,039 gold transmissions" are transcripts, of which 16,174 are distinct transmissions; and it was run on gold only. Re-run over gold **and ASR**, it changes events in 7 scored recordings (gold 193, 210, 228, 1167; ASR 193, 228, 1519), all negatives, so recall is untouched — but recording 210 gains a second `LineUpAndWait` (a reservation, not a `HOLD_SHORT`) and ASR recording 1519 the same, so the stated reason the change was harmless ("only `HOLD_SHORT`, which cannot raise a `RUNWAY` conflict") is doubly wrong: `HoldShort` is a `RunwayInstruction` and does release reservations. Corpus-wide, 110 transcripts (73 gold, 37 ASR) of 22,956 contain a lone single digit-word after "runway" and none is a genuine single-digit designator, so on this data the relaxed pattern only ever fires on ASR-truncated mentions. (Counted 109 at first; re-counted by comparing what the relaxed pattern captures and the strict one does not.) Every airport the corpus names is European or Australian — LKPR, LSZH, LSGS, LSZB, LZIB, LKTB, YSSY — and 99 of the 110 carry no `airport_icao` at all, so the evidence is the designators themselves rather than the metadata. `atcdb/parse_rules.py`; report Appendix B3-B4; `decisions.md` three 2026-11-08 rows. |
| 2026-11-08. WebSearch: other international ATC phraseology conventions beyond the US/ICAO leading-zero split | Asked whether anything else needed similar handling, after the `v3` fix; searched for runway-designator conventions and regional phraseology variation worldwide | Used to find one concrete, actionable gap — "oh" colloquially substituted for "zero", a documented confusion source especially with non-native-English controllers — and one non-actionable context finding (reports of no standardized runway-entry phraseology in China; broader English-proficiency variation by region), written into §7 as a scope boundary rather than a code change | Checked "oh" against the corpus before deciding how to scope it: zero occurrences as a digit, confirming it would be a zero-regression addition here but still a reasonable robustness fix for text this corpus doesn't contain. `docs/logs/decisions.md` 2026-11-08 rows; report §7. |
| 2026-11-08. Claude Code: scope-check a proposed runway-validity checker before deciding not to build it | User proposed checking an extracted runway designator against the known valid runways for that recording's airport | Rejected as currently infeasible, not implemented speculatively. `recordings.airport_icao` is populated for only 560/3,300 recordings and 4/407 of the scored corpus; 305 of the 309 scored negatives (all UWB-ATCC) carry no airport tag at all, so there is nothing to validate against for 99% of what the report scores | Checked by query before concluding infeasibility rather than assuming it; written into report §7 as a next test naming the missing metadata, not as a built feature. |
| 2026-11-08. Claude Code: implement and verify the "oh" digit-word fix (`v3`) | Extend `_DESIG`'s digit-word alternation to accept "oh" for zero, scoped to the runway-designator regexes only; map it to the zero digit-word inside the rules parser only | Used. Deliberately did not add "oh" to the shared `DIGITS`/`D` vocabulary used for callsigns and other item patterns (frequency, altitude, heading, squawk), since "oh" is a common interjection elsewhere in a transcript and widening digit recognition there risked misreading it as part of a different field | 390 tests pass (same 2 pre-existing GPU-only failures as before). Checked the corpus: "oh" appears 0 times after "runway" in all 22,956 transcripts, so the change is zero-regression and zero-effect on every number already reported — a documented robustness fix for text this corpus doesn't contain, not a result. Implemented in `atcdb/parse_rules.py` (`_D_RWY`, `_desig`) only: an earlier version added "oh" to `atcdb/engine.py`'s shared `_DIGIT_WORD`, which was reverted on 08 Nov 2026 because `normalize_runway` is shared by six modules that key separate caches on their own versions, so widening it there would have required $25.65-$28.47 of paid re-runs to stay honest. Report §7. |
| 2026-11-08. Claude API (Sonnet 5) as extractor: JFK 2023, both clearance orderings | User supplied an API key and asked to confirm, rather than merely assume, that the LLM extractor does not share the rules parser's single-digit designator gap; four JFK lines replayed in both orders, window context (about one cent, billed on the spot, not cached) | Used to close an open assumption in Appendix B4, which had said the LLM was "not expected to share this failure mode... but that expectation is untested." Confirmed: Sonnet reads "four left" as `04L` and "three one left" as `31L` correctly in both orders and raises no conflict either way, matching the patched `v3` rules parser exactly | Report Appendix B4 updated from "untested expectation" to "confirmed"; no cached row exists for this case (it is not in the corpus database), so the run is not reproducible keyless the way `real_2026_cases.py`'s cases are — it is reported as a one-off confirmation, not a scored result. |
| 2026-11-08. Claude Code: report review and editing | Review draft 2; shorten and rewrite §2.3, §5, §7 and §8; draft the contribution statement and the reference list; assemble these appendices | Changed: the review found stale numbers and claims ("absorbed by the engine", "19 to 34%", the lenient-recall definition, recording 261's verdict in §4.1, JFK "not run", "no verbal release phraseology") and they were corrected; two uncited references were removed; the Kamm citation in §6.3 was flagged as unsourced. The team chose which rewrites to keep | Every changed number checked against `docs/results/*.md` and `atcdb/evaluate.py`; the LaGuardia single-digit replay (Appendix B1) was run locally, free; contribution facts taken from these logs, to be confirmed by both members |

---

## Appendix J — Decision log

Verbatim from [`docs/logs/decisions.md`](logs/decisions.md).

| Date | Decision | Reason | Evidence | Owner |
|---|---|---|---|---|
| 2026-08-25 | Build on free research corpora (jacktol/atc-dataset, from ATCO2-1h and UWB-ATCC), not our own radio receiver or scraped LiveATC audio | A receiver needs an IMDA licence in Singapore; LiveATC's terms forbid automated retrieval without permission; the corpora come with human transcripts to measure against | `docs/2026-08-25-atc-capture-research.md` §1 and §4; commit 56f3855 | Don |
| 2026-09-14 | Deterministic event-sourced engine; parsers (rules / LLM) limited to extraction; LLM-as-judge only as an evaluation arm | Auditable state; LLM state-tracking drifts | Spec 2026-09-12-conflict-engine-design.md | Don, Jennifer |
| 2026-09-14 | Runways only: the engine tracks land, takeoff, line-up-and-wait and cross reservations, and flags conflicts on the same runway. No taxiways, no altitudes | Set as the v1 scope; intersecting-runway geometry kept as a stretch goal | Spec 2026-09-12, "Decisions locked" item 3 | Don |
| 2026-09-14 | Parser gold labels are written blind to every parser's output, sampled by transmission, with a 50-row overlap labelled by a second person | In the readback round the labels came from the rules, so the rules scored about 99% by construction | Spec 2026-09-12, Section 2 ("Label-circularity caution") and Section 4; `docs/results/readback-models-comparison.md` | Don |
| 2026-09-14 | Synthetic conflicts are injected at the text level into real transcripts and stored under a separate source | Real conflicts are close to zero in normal operations; editing text runs the whole pipeline, parser included, and scores the LLM judge on the same set | Spec 2026-09-12, "Context / pivot" and Section 4 | Don |
| 2026-09-26 | Rules parser frozen at v1 as the pre-registered baseline. Its runway-token, US-callsign and elliptical-handoff gaps are reported as findings. Only `normalize_runway`, shared by every extractor, is fixed | The gaps were found on the Austin test case, and the report's appendix already shows v1's behaviour | Spec addendum A.7.1; commit a788362 (Claude's recommendation, approved) | Don |
| 2026-09-26 | A hold-short for a different runway releases nothing, so corpus recording 528 stays a false RUNWAY alert on purpose | The transmission that clears Air France across 13 also tells it to hold short of 24; releasing on it would erase the crossing as it is issued. The parse is correct; the release was never spoken | Spec addendum A.2 and A.3.2; regression test, commit 66dba7c | Don |
| 2026-09-26 | Staleness timeout set per reservation kind, all at 300 s, with LAND pinned at 284 s or more | At Austin 2023 the landing clearance and the conflicting takeoff clearance were 284 s apart | Spec addendum A.3.6; commit a7b6a74 | Don |
| 2026-09-26 | Framing: the engine detects incompatible clearances, a proxy for loss of separation. We do not claim ICAO compliance | ICAO Doc 4444 (7.9.2, 7.10.1) governs physical separation, and the engine has no position data | Spec addendum A.2 ("Framing") | Don |
| 2026-09-26 | UWB-ATCC transcript text never goes into tests, fixtures or prompts. Fixtures use NTSB public record or invented text; the recording-528 test reads the local database and skips without it | UWB-ATCC is licensed CC BY-NC-ND, so it is not redistributed in the repo | Spec addendum A.3.9; plan `2026-09-26-engine-tuning.md`, "Global Constraints" | Don |
| 2026-09-26 | Pre-registered primary comparison: rules vs Sonnet, window context, human transcripts. Extractor, context and transcript kind vary around it. The false-alarm rate is a finding, not a parameter to tune away | Follows the written report's investigation plan (section 4), which is the commitment | Spec addendum A.5 | Don |
| 2026-09-29 | CROSS and LUAW timeouts stay at 300 s. A 30 to 300 s sweep is reported as a finding; no value is chosen from it | The longest replayable recording spans 139 s, so every value from 139 s to 300 s gives the same output. On the rules arms, shortening removed no negative alert and lost real crossings at 30 s | 3b-1 spec §2; handoff 2026-09-29-evaluation, "Measured while building"; commit 34aba7b | Don |
| 2026-09-29 | Splicing added as a fifth injection kind: a real recording that ends holding a runway is joined to another real recording from the same airport that clears a conflicting use of it | The four text edits find only about 10 candidates (34 of 309 recordings hold two clearances); a splice edits no text, so its ASR is real | Plan `2026-09-29-evaluation-3b1.md`, "Decisions taken while planning (user-approved 2026-09-29)"; 3b-1 spec §4; commit 215bfa0 | Don |
| 2026-09-29 | The ASR headline reports recall only, on positives whose trigger transmission is in the ASR model's test split (25 of 100) | The dataset's train/test split is per clip, and every one of the 309 recordings mixes both, so there is no clean negative. Train clips were probably seen when Whisper was fine-tuned | 3b-1 spec §3; commits 320f1bb, 64a0ddf | Don |
| 2026-09-29 | Every alert on real recordings is adjudicated, pooled across arms, with one of four verdicts: genuine, parse_error, missing_info, engine_rule. A second person checks a fixed 30% for Cohen's kappa | Each alert is a candidate false alarm until a person judges it; the verdicts form the failure taxonomy | 3b-1 spec §6; commit 6fd681a | Don |
| 2026-09-29 | Report that the synthetic positives favour the rules parser | Injection sites are found by textbook-verb regexes ("cleared to land", "line up", "cross runway"), the clean phrasing the rules parser handles. The rules arm scored 86 of 100 strict on gold | Handoff 2026-09-29-evaluation, "Measured while building"; `atcdb/inject.py` lines 43 to 46; rechecked 2026-10-19 (memory note `milestone-2-feedback.md`) | Don |
| 2026-09-29 | Conditional clearances ("behind the landing airbus, line up runway 31 behind") are deferred to a later phase; until then their alerts are adjudicated as engine_rule | Events have no condition field, so a correct parse still raises a false RUNWAY alert. About 17 human transcripts match. A fix needs its own design pass and cache-key bumps | Handoff 2026-10-01, "Also open"; memory note `conditional-clearances-todo.md` | Don |
| 2026-10-11 | Use the event labels on readback_sheet_A as a supplementary check of the Claude parser, not as the Level 1 extraction measure | The sheet came back labelled with instruction events instead of readback consistency. Its 200 instructions are not a uniform sample, and most come from approach/radar recordings | Commit 2077939 (`scripts/score_pair_events.py` docstring) | Don |
| 2026-10-19 | (Proposed, awaiting decision) Stage the paid run: the primary comparison only (rules vs Sonnet, window, on gold and ASR) plus the LLM judge. Haiku and the other contexts only if time allows | The professor's Milestone 1 feedback suggested cutting to the pre-registered comparison. About $30 instead of about $105 for all 18 arms | Handoff 2026-10-01, "Cost decision pending"; memory note `milestone-2-feedback.md` item 2; Claude Code session 2026-10-19 (not in the repo) | Don |
| 2026-10-20 | Replace the Milestone 1 pilot table's predicted LLM column with real output (rules vs Sonnet, window context, gold) | The professor's feedback: a prediction is a hypothesis, not data | `docs/results/pilot-cases.md`; `scripts/pilot_cases.py` | Don |
| 2026-10-20 | Split the missing_info verdict into missing_release (never spoken) and other_frequency (on a frequency we do not record), and state that every real recording is tower frequency | The professor's feedback: some false alarms do not come from extraction. The split shows which false alarms the choice of extractor can change. No sheet had verdicts yet | 3b-1 spec §6 (amended 2026-10-20); `atcdb/evaluate.py` VERDICTS | Don |
| 2026-10-20 | Skip scoring Sonnet with window context on the 200 labelled lines for now | The dry run said $6.55, not the "about $1" first estimated. The lines are mostly approach/radar, and the main run already covers Sonnet with window context on tower recordings | Claude Code session 2026-10-20 (not in the repo); memory note `milestone-2-feedback.md` | Don |
| 2026-10-20 | Keep Haiku 5.5 (`claude-haiku-5-5`) as the live demo app's Claude model; it stays out of the evaluation's arms | It passed the week-1 gate against Sonnet 5 on the 200 labelled lines: 31 of 32 runway events found (Sonnet 32; at most 2 fewer allowed), 6 invented (Sonnet 9; at most 18 allowed). On Austin it raises the same alert as Sonnet at the takeoff clearance. About a tenth of Sonnet's price; the check cost about 5 cents | `docs/results/extraction-pair-events.md`; `docs/results/pilot-cases.md`; live demo spec Section 8 | Don |
| 2026-10-22 | Skip the Level 1 event sheets (200 random tower transmissions, 50 labelled twice) for Milestone 2; report extraction from the readback sheet's 200 labelled instructions, stating its limits (mostly approach and radar, controller lines only, one labeller) | No time to label. The professor's request, every extractor on the labelled transmissions, is met by the readback sheet; the event sheets were our own pre-registered measure (3b-1 spec, section 8), so this is a deviation from our plan | `docs/results/extraction-pair-events.md`; `data/labels/README.md` | Don |
| 2026-10-25 | Run the paid arms with Sonnet 5 and Haiku 5.5 (`claude-haiku-5-5`, replacing Haiku 4.5): window context, gold and ASR, plus the LLM judge with both models. This settles the 2026-10-19 proposal and brings Haiku 5.5 into the evaluation, which the 2026-10-20 row kept out | API credits became available, so Sonnet stays and the pre-registered primary comparison (rules vs Sonnet) runs as registered. Haiku 5.5 is the live app's model; Haiku 4.5 is cut, as the professor advised narrowing to the pre-registered comparison. The positives are the 98 injections marked valid on the check sheet (2 rejected as implausible phraseology) | `atcdb/evaluate.py` EVAL_MODELS; `atcdb/judge.py` MODELS; `data/labels/injection_check.csv`; Claude Code session 2026-10-25 (not in the repo) | Don |
| 2026-10-25 | Adjudicate RUNWAY alerts only (94 on sheet A, 31 on Jennifer's sheet B); report READBACK alerts as raw alerts per hour, an upper bound on their false alarms | All 335 pooled alerts were too many to label in time, and 241 of them were READBACK. The pre-registered false-alarm measure counts RUNWAY alerts only, so the primary comparison is unchanged. This is a deviation from the 3b-1 spec, which committed to adjudicating every alert | 3b-1 spec §6 (amended 2026-10-25); `atcdb/evaluate.py` ADJUDICATED_TYPES; Claude Code session 2026-10-25 (not in the repo) | Don |

| 2026-11-02 | Adjudicators follow a written four-step checklist; a line-up issued while another aircraft holds the runway is engine_rule; the sheets show the whole recording up to the alarm, and rows decided on less are re-checked | Neither adjudicator is a controller, so verdicts follow stated steps rather than expertise (reported as a limitation). The six-line context had hidden earlier lines in 35 of the 94 alarms | `data/labels/README.md` §3; `atcdb/evaluate.py` adjudication_rows; Claude Code session 2026-11-02 (not in the repo) | Don |
| 2026-11-03 | Jennifer re-labels her 31 alarms with the written checklist, without seeing sheet A; her first round is kept and both rounds are reported | Round 1, labelled without the checklist, agreed with sheet A on 14 of 30 alarms (Cohen's kappa 0.12; one cell used the retired verdict missing_info). Of her 11 alarms that sheet A set by checklist step 1, she marked 7 engine_rule. Round 2's agreement is partly produced by the near-mechanical step 1, which the report must say. Round 2 result: kappa 0.80 over 31 (27 agree); 11 of 11 on the step-1 alarms, 16 of 20 (kappa 0.62) on the rest. All four disagreements are sheet A missing_release, sheet B parse_error; sheet A is not changed after seeing B | `data/labels/adjudication_B_round1.csv`; `data/labels/adjudication_B.csv`; `data/labels/README.md` §3; Claude Code session 2026-11-03 (not in the repo) | Don |
| 2026-11-07 | Commit the raw evaluation rows (`data/eval/conflicts/*.jsonl`, `data/eval/pair_events/*.jsonl`) instead of keeping them git-ignored | Jennifer needs the per-recording rows behind the results docs. They carry corpus text: callsigns and phrases in the conflict rows, whole transcripts in the pair rows. The repo is private, and the label sheets with transcript text are already tracked | `.gitignore` (`!data/eval/`); Claude Code session 2026-11-07 (not in the repo) | Don |

| 2026-11-08 | Report two consequence weights rather than one scalar Risk Score | Omission and invention cause opposite harms — omission costs recall and raises a false alarm 0% of the time; invention costs false alarms and barely touches recall — so collapsing them into one weighted score would hide the finding the project set out to measure. A deliberate deviation from Milestone 1's "a Risk Score" and from Chang et al.'s single weighted score, and it needs a justifying sentence in the report | `docs/results/risk-score.md`; `scripts/risk_score.py`; report §5 finding 2 | Jennifer |
| 2026-11-08 | Build the consequence-weighted perturbation study rather than leaving Milestone 1's Risk Score commitment unmet | The commitment was made in Milestone 1 after Chang et al. (2026). Perturbing one event in a stored stream and re-folding it through the engine is free and deterministic: no re-parsing and no API call | `scripts/risk_score.py` (17 tests); `docs/results/risk-score.md` | Jennifer |
| 2026-11-08 | Do not spend the remaining API credit on the LLM context sweep; report it as a named gap | About 4,000 live calls on the afternoon of the deadline (dry run 2026-11-08: Sonnet at `none` $6.88, at `role` $6.90). §2 and §7 already name it as the first thing to buy; revisit for the Week 13 presentation | report §2 ("Honest gap") and §7; handoff `2026-11-08-milestone2-submission-handoff.md`, open decision 3 | Jennifer |
| 2026-11-08 | Git-ignore the report draft and `docs/figures/`; track `notebooks/milestone2_pipeline_walkthrough.ipynb` and the Goa label sheets instead | The draft and figures are the deliverable and are written outside the repo, while `docs/results/` holds the tracked evidence they cite. The notebook is the report's technical artefact and the sheets are the 2026 reconstruction | commit 12768f4; `.gitignore`; `data/labels/real_2026_cases_A.csv` / `_B.csv` | Jennifer |
| 2026-11-08 | Consolidate the Milestone 2 work onto `main`, delete the working branch, and push | One place for the submission's evidence, so the report's links resolve for a reader with only `main` | commits 12768f4, then 1129789 | Jennifer |
| 2026-11-08 | Defer §6's central claim — which of the three candidate threads is the report's actual argument — to the team | The submission checklist penalises concepts used "to reason, not merely to name-drop theories", so the choice has to be the team's. The draft supplies structure, evidence and three threads without picking one | report §6; handoff `2026-11-08-milestone2-submission-handoff.md`, next step 1; reaffirmed in the 2026-11-08 session ("work on section 6 later") | Jennifer |
| 2026-11-08 | Retract Milestone 1's tokenisation/attention/softmax passage and its temperature-0 determinism claim, visibly rather than by quiet deletion | Feedback 5 asked for it; the guidelines forbid architecture detail that never enters the analysis; and the determinism claim is factually wrong for this API — Sonnet 5 rejects a `temperature` parameter, so reproducibility comes from caching every parse against a strict tool schema | report §2 opening parenthesis; spec addendum A.4; `atcdb/parse_llm.py` | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Restructure §6 onto pipeline-vs-judge rather than rules-vs-LLM | Feedback 6: the four-field extractor stays auditable whether it is a regex or an LLM, and it is the end-to-end judge that cannot be traced. "Rules are traceable, LLMs are not" is the wrong cut, and the project's own architecture is the reason | report §1 and §6 | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Move the LLM-judge ablation out of §6 and into §4.4 as a result | It is a pre-registered arm whose numbers appeared nowhere in Results. Jennifer's catch | report §4.4; `atcdb/judge.py`; `docs/results/conflict-eval.md` | Jennifer (identified); Claude (implemented) |
| 2026-11-08 | Merge the former §4.3 and §4.4 into one section running shared mass then divergences | The results read better from what no choice of extractor affects to the ten recordings that carry the whole difference. Jennifer's prompt | report §4.3 | Jennifer (identified); Claude (implemented) |
| 2026-11-08 | Also git-ignore `docs/references/` | 42 MB of papers that are not ours to redistribute. Not asked for; proposed by Claude alongside the draft and figures decision | commit 12768f4; `.gitignore` | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Install Don's `data/atc.sqlite` from branch `runway-watch-app`, backing the previous copy up to `data/atc.sqlite.bak-20261108` | Jennifer's copy had 0 injections, 882 cached events and 0 judgments, so `eval_conflicts.py report` silently dropped all 98 positives and wrote `recall: n/a over 0 positives`. Don's copy carries 100 injections, 36,001 cached events and 1,628 judgments | branch `runway-watch-app` commit aa889ee; verified by regenerating `conflict-eval.md` byte-identically against the committed doc | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Add `PRIMARY_ASR` so the primary pair gets its own paired interval on ASR transcripts | Milestone 1 motivated the LLM by robustness to ASR noise, so the comparison that tests that motivation needs a paired interval rather than two intervals read side by side (feedback 4). The result contradicts the Milestone 1 hypothesis and is the only interval in the study that excludes zero | `atcdb/evaluate.py` `PRIMARY_ASR`; `atcdb/eval_report.py`; commit 1129789; report §4.2 | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | (Proposed, awaiting decision) Report the hybrid extractor in §7 as the most informative next test with a preliminary number, not in §4 as a result | It scores 94% lenient recall at 4.5 RUNWAY false alarms per hour against rules at 87%/4.1 and Sonnet at 90%/4.9, but it was designed after reading the divergences and scored on the same 98 positives that motivated it, so presenting it as a finding would be overfitting. It is also not cheaper than Sonnet, since the callsigns still need the LLM. **Its script is not in the repo**, so the number is currently unreproducible and cannot be cited until it is rebuilt | handoff `2026-11-08-milestone2-submission-handoff.md`, open decision 1; handoff `2026-11-08-cross-arm-analysis-handoff.md`, closing section | Claude (recommended; undecided) |
| 2026-11-08 | (Proposed, awaiting decision) Add one caveat sentence to §4.1 about Sonnet's 9 invented events | They rest on one labeller with no second reader and no kappa, and 7 of the 9 are approach clearances read as landing clearances, which is arguably a judgment call rather than a clear error. The precedent is already in `extraction-pair-events.md`, where the handoff scores were discarded for exactly this reason | handoff `2026-11-08-milestone2-submission-handoff.md`, open decision 2; `docs/results/extraction-pair-events.md` | Claude (recommended; undecided) |
| 2026-11-08 | (Proposed, awaiting decision) Use the readback/hearback barrier literature as a §6 thread | Proposed in the 2026-11-08 session while §6 was deferred; not yet evaluated against the other three candidate threads | report §6 ("What still needs the team's own judgment") | Claude (recommended; undecided) |
| 2026-11-08 | Extend the case-by-case comparison from one arm pair to all four rules-vs-LLM pairs on both transcript kinds, reading only the committed rows | Appendix A's mechanisms were read off rules vs Sonnet 5 on gold alone, which §7 listed as a limitation: a mechanism seen in one arm pair on one transcript kind is an anecdote until it replicates. The rows were committed on 2026-11-07, so this needs no database and no paid call | `scripts/cross_arm_replication.py`; `docs/results/cross-arm-replication.md`; commit 752320f | Jennifer |
| 2026-11-08 | Classify the divergence mechanisms in code rather than by hand | The report cites the mechanism counts, and a hand reading of ten recordings cannot be re-checked by a reader or re-run on another arm | `cross_arm_replication.classify`; `tests/test_cross_arm_replication.py`; commit 752320f | Jennifer |
| 2026-11-08 | Split Appendix A's first mechanism into `identity_holder` and `identity_trigger` | An unresolved callsign on the aircraft already holding the runway and one on the conflicting clearance itself have the same engine consequence (`apply` caps at warning when either party is unknown) but different causes: only the holder needs identity carried across transmissions, which is what the §4.3 claim about context rests on. 17 of 25 divergences are the holder, 2 the trigger | `classify` docstring; `docs/results/cross-arm-replication.md` §3; commit 752320f | Jennifer |
| 2026-11-08 | Keep an explicit `unclassified` label instead of forcing every divergence into a mechanism | The honest claim is "all 25 are explained", which is only checkable if the classifier is able to say it cannot explain one | `classify`; `test_an_unexplained_divergence_is_reported_as_unclassified_not_forced`; commit 752320f | Jennifer |
| 2026-11-08 | Derive runway state by folding the stored events through `engine.apply`, never by scanning the event list | Holding a runway is engine state, not a property of an event: a hold-short for the same runway, a `VACATED`, a go-around and a handoff to ground or departure all release a reservation, and reservations go stale. The first version scanned the event list and agreed with the engine on all 50 lookups in this data by luck; it would have drifted wherever a release precedes the trigger | `cross_arm_replication.holders`; `test_holders_come_from_the_engine_so_a_released_reservation_is_not_one`; commit 752320f | Jennifer |
| 2026-11-08 | Treat more than one aircraft holding a runway as the normal case, comparing holders as a set | 5 of the 50 holder lookups have two reservations open at once, and Appendix A's hand reading had already noted it for recording 3260 (`LUAW`+`TAKEOFF`). An earlier version collapsed them to the last reservation extracted | `cross_arm_replication.holders`, `anonymous`; `test_more_than_one_aircraft_can_hold_a_runway_at_once`; commit 752320f | Jennifer |
| 2026-11-08 | Report the two 2026 reconstructions (Goa, Houston) as a boundary of the framing, not as scored cases | Their `events` column is unlabelled, and no transmission in either maps to one of the engine's four reservation kinds, so no extractor can raise an alert. Goa is a backtrack incursion and Houston a callsign-confusion event: the limitation is the conflict model's vocabulary, not either parser | `scripts/real_2026_cases.py`; report §4.5; `data/labels/real_2026_cases_A.csv`; commit 752320f | Jennifer |
| 2026-11-08 | Report Sonnet 5 inventing nothing on the 2026 rows as a negative result rather than omitting it | "expect backtrack" and "entering runway" are the lines most likely to invite a fabricated clearance, so this was the sharpest test of §2's completion mechanism on real text. The §2 argument rests on the 9 invented events at Level 1 and on recording 242, not on inventions being ubiquitous | report §4.5; `data/eval/real_2026/events-claude-sonnet-5.json`; commit 9ebee1e | Jennifer |
| 2026-11-08 | Commit the LLM arm's output for the 2026 cases so the table reproduces with no key, and add `--verify` so it also re-derives with one | These recordings are not in the corpus database, so the evaluation's usual cache does not cover them. A recording that can only ever be replayed is hardcoded data; one that can be re-derived and checked is a falsifiable claim | `real_2026_cases.py --verify`; `data/eval/real_2026/`; commit 9ebee1e | Jennifer |
| 2026-11-08 | `--verify` fails only on the invariant the report cites (no runway reservation) and reports every other difference as drift, rather than requiring byte-equality | §2 retracts Milestone 1's temperature-0 determinism claim: Sonnet 5 rejects a `temperature` parameter, so identical prompts need not give identical replies and a strict diff would be unsound by the report's own argument | `real_2026_cases.drift`, `reservations_in`; commit 9ebee1e | Jennifer |
| 2026-11-08 | Recordings carry a `provenance` field; the committed Sonnet recording is marked `transcribed` and warns on every load until `--record` replaces it | Its events are real output from a 2026-11-08 run, but they were read back from that run's terminal output, which prints `runway or to` and so loses which field a value came from. A hand-seeded file is otherwise indistinguishable from one the script wrote against the API. Checked by re-rendering the recording and diffing it against the pasted run byte-for-byte | `real_2026_cases.PROVENANCE_TRANSCRIBED`; `test_a_transcribed_recording_is_announced_as_such`; commit 9ebee1e | Jennifer |
| 2026-11-08 | `--record` and `--verify` require an explicit `--model` and refuse to run together | Both spend money. Requiring the model name means no billed call can happen as a side effect of a default, and refusing the combination stops a check silently becoming an overwrite | `real_2026_cases.main`; commit 9ebee1e | Jennifer |
| 2026-11-08 | Test the mechanism classifier and the 2026 replay to the same standard as `risk_score.py`, rather than treating analysis scripts as throwaway | The report cites both scripts' output, and `tests/test_risk_score.py` already set the precedent that a script feeding a reported number is tested. 37 tests added, taking the suite from 348 to 390 | `tests/test_cross_arm_replication.py` (16), `tests/test_real_2026_cases.py` (20), `tests/test_evaluate.py` (5 added); commits 752320f, 9ebee1e | Jennifer |
| 2026-11-08 | Assert §4.5's claim in a test: no arm may produce a runway reservation on the 2026 rows | The claim is load-bearing — it is what makes those two cases evidence about the framing rather than about a parser. A parser change that broke it would otherwise invalidate a report section silently | `test_neither_2026_incident_yields_a_runway_reservation_under_the_rules_parser`; `test_the_committed_sonnet_recording_also_yields_no_reservation`; commit 9ebee1e | Jennifer |
| 2026-11-08 | Exercise the billed `--record` / `--verify` paths with a stub parser, and skip rather than fail the committed-recording test while no recording exists | The paid path needs coverage, but no test may require a key or spend money; and the repo had to stay usable before the recording was committed. That test now runs rather than skipping | `tests/test_real_2026_cases.py` (`_fake_parser`, round-trip and drift tests); commit 9ebee1e | Jennifer |
| 2026-11-08 | Capture output baselines for `divergent_cases.py`, `cross_arm_replication.py` and `risk_score.py` before refactoring shared code, and require them byte-identical afterwards | The refactor touched a committed script the report's Appendix A cites. The baselines caught a real regression (`detection` dropped from `divergent_cases.py`'s imports while line 60 still calls it) and a classifier rule that was too strict and pushed 5 cases to `unclassified` | handoff `2026-11-08-cross-arm-analysis-handoff.md`, "Refactor that touched existing files"; commit 752320f | Jennifer |
| 2026-11-08 | Promote `caught`, `false_alarms` and `scored` from the analysis scripts into `atcdb/evaluate.py` | They were byte-identical in `divergent_cases.py` and the new script. `evaluate.py`'s own header states that everything below `read_rows` is pure scoring and the scripts already import from it, so library-grade predicates duplicated in a script did not match the repo's structure | `atcdb/evaluate.py`; `tests/test_evaluate.py`; commit 752320f | Jennifer |
| 2026-11-08 | Keep the repo's two script conventions rather than unifying them: stored-rows analysis scripts take no shebang and `from __future__ import annotations`; replay scripts that can call the API take a shebang | `divergent_cases.py` and `risk_score.py` follow the first, `pilot_cases.py` the second. The split marks which scripts can spend money, so it is worth preserving | `scripts/cross_arm_replication.py` (analysis), `scripts/real_2026_cases.py` (replay); commit 752320f | Jennifer |
| 2026-11-08 | Write this session's handoff into `docs/superpowers/handoffs/` instead of the OS temp directory the `handoff` skill specifies | Eight handoffs already live there and are tracked; a temp directory is not findable by the next agent, which was the point of writing it | `docs/superpowers/handoffs/2026-11-08-cross-arm-analysis-handoff.md`; commit 752320f | Jennifer |

| 2026-11-08 | Patch the rules parser's runway-designator pattern to accept a single digit-word, bumping `parse_rules.VERSION` to `v3` rather than editing `v1` in place | The report's own LaGuardia and JFK case studies exposed that `v1` cannot read "runway four", only "runway zero four", because US controllers commonly drop the leading zero where ICAO phraseology keeps it (`normalize_runway` already zero-pads correctly; only the phrase regex was too narrow). A version bump keeps `v1`'s cached events and every number already reported in §4 untouched, consistent with the module's own stated convention of bumping `VERSION` whenever a pattern changes | `atcdb/parse_rules.py`; report Appendix B3-B4 | Jennifer (identified); Claude (implemented) |
| 2026-11-08 | Adopt `v3` as verified-safe against the scored corpus without re-running the paid evaluation | Checked `v3` against all 17,039 gold transmissions: it changes output on only 6, of which 3 are outside the 98 positives/309 negatives entirely and the other 3 (all in scored negatives 193, 228, 1167) produce only `HOLD_SHORT` events, which `engine.apply` never turns into a `RUNWAY` conflict. So re-scoring with `v3` would not move any number in §4, and the frozen `v1` baseline there is not retroactively claimed to have been something it wasn't | snippet in report Appendix B3; `atcdb/engine.py` `apply` (`RunwayInstruction` branch is the only source of `RUNWAY` conflicts) | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Report `v3`'s new truncated-recording failure mode rather than treat the fix as a free win | On the same 17,039-transmission check, 4 of the 6 changed transmissions are clipped recordings ("runway three **o**", "...runway one **t**") that `v3` now misreads as a genuine single-digit designator on the wrong runway, a failure mode `v1`'s stricter pattern did not have. None land in the scored corpus, but the trade-off is real and belongs in the report, not just the fix | report Appendix B3 | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Accept "oh" as a zero digit-word inside a runway designator only (`v3`), not in the shared `D`/`DIGITS` vocabulary used for callsigns and other item patterns | A web search for other international phraseology conventions (requested after the `v3` fix) surfaced "oh" substituted for "zero" as a documented real-world confusion source, especially with non-native-English controllers. Scoped narrowly because "oh" is a common interjection elsewhere in a transcript ("oh, roger"); widening the general digit vocabulary would risk misreading it inside a callsign or another field | `atcdb/parse_rules.py` (`_D_RWY`, `_desig`); report §7 | Jennifer (identified); Claude (implemented) |
| 2026-11-08 | Do not implement a per-airport runway-validity checker | Checked `recordings.airport_icao` before building it: populated for only 560/3,300 recordings overall and 4/407 of the scored corpus (the other 403, including 305/309 negatives, are all UWB-ATCC with no airport tag at all). There is nothing to validate a runway designator against for 99% of the scored corpus as currently labelled. Reported as a next test requiring airport metadata this dataset does not carry, not built on a guess | report §7 | Claude (recommended; Jennifer to sign off) |
| 2026-11-08 | Rewrite "oh" to the zero digit-word inside `parse_rules._desig`, leaving `engine.normalize_runway`'s `_DIGIT_WORD` untouched | `normalize_runway` is shared by the rules parser, the LLM parser, the judge, the injection generator, `event_labels` and `score_pair_events`, each keying its cache on its own hand-bumped version, so widening it there changes output for all six while their cache keys stay identical. Doing it honestly would mean bumping `parse_llm.VERSION` and `judge.VERSION` (measured: $28.47 of paid re-runs) or `ENGINE_VERSION` ($25.65). Handling it in the one parser that needs it costs $0.00 and the `v3` bump already covers it. Verified: `normalize_runway('oh four left')` is `None` again, while `_desig('oh four left')` is `04L` | `atcdb/parse_rules.py` (`_desig`); `atcdb/engine.py` (`normalize_runway` docstring); costs measured per arm with `evaluate.uncached` | Claude (implemented); Jennifer (approved) |
| 2026-11-08 | Make the two-digit designator the default again, and reach the US single-digit form through an opt-in instead | The relaxed pattern was applied to every recording, which is wrong in one direction on this data: where two digit-words are always spoken, a lone one is an ASR truncation, so reading it as a designator invents a runway the transmission never named. Measured: 110 transcripts (73 gold, 37 ASR) of 22,956 carry a lone digit-word after "runway" and not one is a genuine single-digit designator. "runway three o" became `LUAW 03` instead of falling back to the active runway 13, and "runway zero niner cleared to land" became `NoOp` -- the clearance dropped outright. The strict default is identical to `v1` on all 22,956 transcripts (0 differences), so every number already reported stands | `atcdb/parse_rules.py` (`_DESIG`); report §7, Appendix B3 | Claude (measured and implemented); Jennifer (approved) |
| 2026-11-08 | Keep the single-digit reading as a per-airport opt-in (`parse_rules.make_parser(single_digit_runways=True)`), enabled for the US case studies only | The first attempt applied one convention everywhere and broke the European data; the fix is not a better pattern but an extra condition that says *which* convention a recording follows. That is the point worth reporting: what limits this system here is not which extractor reads the text but whether the phraseology convention has been encoded for that airport. The two are separable -- the convention is a hardcoded condition in front of the parser, so once it is right, both the rules parser and the LLM read the same designator, and once it is wrong, neither can. Our data cannot settle the rest: every airport the corpus names is European or Australian (LKPR, LSZH, LSGS, LSZB, LZIB, LKTB, YSSY), none uses single-digit designators, and even the US reconstruction never speaks one -- so the condition is correct by construction and untestable on the evidence available, which is a limitation of the corpus, not of the extractors | `atcdb/parse_rules.py` (`make_parser`); `scripts/pilot_cases.py` (KAUS), `scripts/real_2026_cases.py` (`SINGLE_DIGIT_CASES`, KIAH); report §7 | Jennifer (framing); Claude (implemented) |
| 2026-11-08 | Leave the read-back item extractor on the ICAO two-digit pattern, and report the asymmetry rather than widen it | `readback.extract_items` is called from inside `engine.apply`, so switching it per airport would push phraseology into the engine; widening it unconditionally would make the read-back check see a runway item in the 110 truncated mentions that carry no designator, moving every published read-back number for a convention no transcript here uses. The cost is real and is reported: under the single-digit convention the clearance side books "runway four left" while the read-back side cannot, so a runway read-back miss on a single-digit designator goes undetected. Pinned by a test so it is not "fixed" by accident | `atcdb/readback.py` (`ITEM_PATTERNS`); `tests/test_readback.py`; report §7 | Claude (recommended); Jennifer (approved) |
| 2026-11-08 | Report the §4.2 false-alarm interval with a three-treatment sensitivity bound rather than withholding it while two alerts await adjudication | `evaluate.false_alarm_units` raises `Pending` when any RUNWAY alert has no verdict, which is the right default -- each alternative biases in a known direction -- but refusing a number says nothing about how much the missing verdicts could matter. The strip fix leaves exactly two unadjudicated keys (261:RUNWAY:31:5923, 352:RUNWAY:13:393). Bounding them shows the conclusion cannot move: the ASR gap excludes zero under all three treatments (-1.51, -1.52, -1.88) and the gold gap includes zero under all three. §4.2 publishes the treatment least favourable to the claim, so an adjudication finding either alert not-genuine widens the gap rather than closing it. Dropping the recording -- the intuitive fix -- is rejected as selection on the outcome: it removes a negative *because* an arm alerted on it, which systematically flatters the arm that alerted, and is shown only for comparison | `scripts/pending_sensitivity.py`; `tests/test_pending_sensitivity.py`; report §4.2, Appendix A2 | Jennifer (challenged the withheld number); Claude (measured and implemented) |
| 2026-11-08 | Adjudicate the two alerts the strip fix newly raised as `parse_error`, and rule that step 1's "the same runway" means the designator, not the strip | 261:RUNWAY:31:5923 — Sonnet read "csa seven three charlie runway **three one three** clear to land" as runway 31, but the clearance is runway one three: 13 is the active runway throughout the recording ("ils one three", "runway one three cleared for immediate takeoff") and Haiku read the same words as 13, while the rules parser read 31 and swallowed the stray word into the callsign. Nobody was cleared onto 31, so step 1 answers No. 352:RUNWAY:13:393 — Haiku split one callsign ("austrian seven one one zulu" / "austrian seven one zulu") into two aircraft and gave the invented second one a landing clearance built from a truncated line naming no designator; the second plane is the extractor's own, which is what step 1's `No` branch describes. The designator reading is chosen because `parse_error` is the only verdict the choice of extractor can move (report §3.3.2): filing an extractor-specific misread under `missing_release` would hide it behind a cause that is independent of extraction quality | `data/labels/adjudication_A.csv`; `data/labels/README.md` §3; report §4.2, §4.3, Appendix A2 | Jennifer (adjudicated and ruled) |
| 2026-11-08 | Drop §4.2's sensitivity bound now that nothing is pending, and keep the script as a standing guard | All 96 RUNWAY alerts on the 309 negatives carry a verdict, so the rates are over the full set and the three-treatment table is redundant. `scripts/pending_sensitivity.py` stays: it reports when nothing is outstanding, and bounds the effect automatically if a future engine or model change surfaces an alert at a key no sheet covers -- which is how this situation arose in the first place. The adjudicated ASR gap is -1.9 (-3.6 to -0.4), wider than the -1.5 (-3.0 to -0.4) it replaces, because both new alerts count against the arm that raised them | `scripts/pending_sensitivity.py`; report §4.2, §3.3.2, Appendix H | Claude (recommended); Jennifer (approved) |
| 2026-11-08 | Repin `torch` from `2.13.0` to `2.11.0`, the newest release that exists for this interpreter | `torch==2.13.0` was never a real release, so `pip install -r requirements.txt` could not succeed and the two GPU-transcriber tests in `tests/test_asr.py` had been failing on a missing module ever since -- written off in the report as "a GPU module this machine lacks" rather than as an uninstallable pin. Because the pin never installed, no reported number can depend on a particular torch version: the published WER comes from `make_faster_whisper_transcriber` (faster-whisper, CPU int8), and torch serves only the Mac GPU path (`hf_whisper_transcriber`) and `scripts/train_readback_bert.py`. With 2.11.0 installed the suite is 430 pass, 2 skip, 0 fail; the 2 skips are the live-app smoke tests that need an API key | `requirements.txt`; `tests/test_asr.py`; report Appendix H | Claude (found and fixed); Jennifer (approved) |
| 2026-11-08 | Supersede the earlier ruling: step 1's "the same runway" means the **strip**, not the designator, and 261:RUNWAY:31:5923 becomes `missing_release` | The engine was changed to treat 13 and 31 as one runway (`OPPOSITE_MATRIX`), so a checklist step that asks whether a different aircraft was cleared onto "the same runway" should be read the way the engine reads it; the earlier row chose the designator reading on the ground that `parse_error` is the only verdict extraction can move, which is a reason to prefer a classification, not evidence about what happened. Speed bird eight six one's takeoff clearance on 13 is therefore a clearance onto this runway: step 1 yes, step 2 finds no release, step 3 is not a line-up, so step 4. Checked for collateral before applying: of the 96 adjudicated alerts, 61 have a prior clearance on the same designator and exactly **1** -- this one -- on the reciprocal end, so the reading changes no other verdict. No rate, interval or kappa moves (every non-genuine verdict counts as a false alarm; the key is not in sheet B's overlap). Taxonomy 32/31/33 -> 31/32/33, and per-arm `parse_error` falls to 0 on Sonnet gold and 1 on Sonnet ASR | `data/labels/adjudication_A.csv`; report §3.3.2, §4.3, §4.4 | Jennifer (decided); Claude (measured the collateral and applied) |

Owner conventions. Rows marked **Don** are decisions approved in Claude Code sessions; check whether Jennifer was consulted — several look wrong, since Jennifer did the injection check (100 rows) and adjudication sheet B (31 rows, both rounds). Resolve this while writing the contribution statement. Rows added on 2026-11-08 use three more precise labels: **Jennifer** for decisions she took; **Jennifer (identified); Claude (implemented)** where she spotted the problem and Claude carried it out; and **Claude (recommended; Jennifer to sign off)** for changes Claude proposed and implemented that have not been formally approved. Rows beginning "(Proposed, awaiting decision)" are not decisions yet.

---

## Appendix K — Contribution statement

Don Chia built the pipeline, including the transcriber, both extractors, the conflict engine, and the replay and
evaluation scripts. He ran the paid evaluation, generated the 100 synthetic conflict candidates, and adjudicated all 96
RUNWAY alerts raised on the real recordings. He also found and fixed a flaw where the engine treated the two ends of one
runway as separate runways, and he wrote sections 5 and 7.

Jennifer Liu designed the evaluation and the labelling protocol. She checked all 100 synthetic candidates without
seeing any extractor output, and labelled the second adjudication sheet (31 alerts, over two rounds) that we used to
measure how well our judgements agreed. She also built the consequence-weighting study and the cross-arm replication,
wrote the societal and philosophical analysis, and put the report together.

Claude Code (Anthropic) wrote most of the code under our direction and helped draft and edit parts of this report. We
checked every reported number against the committed results, and the AI-use log (Appendix I) records where we used its
output and where we rejected it.
