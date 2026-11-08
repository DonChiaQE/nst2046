"""Rules parser: regexes over normalized transcript text -> engine events. The non-LLM baseline.

Known blind spots (report material): conditional clearances ("behind the landing airbus, line up"),
clipped or nonstandard phrasing, callsigns that are not at the start (controller) or end (pilot) of
the transmission, "go around" said *about* another aircraft, instructions to two aircraft in one call.
Bump VERSION whenever a pattern changes so cached events (atcdb/replay.get_events) are invalidated.
"""
import re

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated, normalize_runway)
from atcdb.parsing import Context, Parser, Transmission
from atcdb.readback import D, ITEM_PATTERNS

VERSION = "v3"

DIGITS = set("zero one two three four five six seven eight nine niner".split())
NATO = set("alfa alpha bravo charlie delta echo foxtrot golf hotel india juliett juliet kilo lima mike november oscar oskar "
           "papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu".split())
FILLER = set("roger ok okay tower ground hello hi good morning afternoon evening day bye thank you thanks and break copied "
             "wilco affirm yes yeah we are will expedite to the now sir again say please confirm correct that s is it for of "
             "your wait ruzyne".split())
_SIDE = r"(?: left| right| centre| center)?"
# A runway designator is two digit-words in ICAO practice ("zero four"). `_D_RWY` also accepts "oh" for the zero
# digit-word -- a colloquial substitution reported in non-native-English ATC communications (report §7) -- but only
# inside a designator: it deliberately does not extend the shared `D`/`DIGITS` used for callsigns and the other item
# patterns in atcdb.readback, since "oh" is a common interjection elsewhere in a transcript ("oh, roger"). `_desig`
# rewrites it before handing the match to `engine.normalize_runway`, which is shared with the LLM parser, the judge
# and the injection generator, each keying its cache on its own version.
#
# US controllers drop the leading zero and speak one digit-word ("runway four left") where ICAO keeps it ("zero four
# left"), and `_DESIG_US` matches that. It is NOT the default: on a corpus where two digit-words are always spoken, a
# lone digit-word is an ASR truncation ("runway three o", "runway two"), and accepting it turns a truncation into a
# confident wrong designator instead of letting `_runway_for` fall back to the active runway. Measured on this corpus:
# 109 transcripts (72 gold, 37 ASR) carry a lone digit-word after "runway" and not one is a real single-digit
# designator -- every airport here is European or Australian (LKPR, LSZH, LSGS, LSZB, LZIB, LKTB, YSSY). So the
# relaxed pattern is opt-in per replay, via `make_parser(single_digit_runways=True)`.
_D_RWY = rf"(?:{D}|oh)"
_DESIG = rf"{_D_RWY} {_D_RWY}{_SIDE}"
_DESIG_SINGLE = rf"{_D_RWY}(?: {_D_RWY})?{_SIDE}"
RUNWAY_RE = re.compile(rf"\brunway ({_DESIG})\b")
RUNWAY_RE_SINGLE = re.compile(rf"\brunway ({_DESIG_SINGLE})\b")


def _instruction_res(desig: str) -> list[tuple[str, re.Pattern]]:
    """kind, phrase regex. CROSS / HOLD_SHORT capture their runway directly, so they need the designator pattern."""
    return [
        ("LAND", re.compile(r"\bclear(?:ed)? to land\b")),
        ("TAKEOFF", re.compile(r"\bclear(?:ed)? (?:for|to) take ?off\b")),
        ("LUAW", re.compile(r"\bline up\b")),
        ("CROSS", re.compile(rf"\b(?:cross|crossing) runway ({desig})\b")),
        ("HOLD_SHORT", re.compile(rf"\bhold(?:ing)? short(?: of)?(?: runway)? ({desig})\b")),
    ]


INSTRUCTION_RES = _instruction_res(_DESIG)
INSTRUCTION_RES_SINGLE = _instruction_res(_DESIG_SINGLE)


def _runway_re(single: bool) -> re.Pattern:
    """The runway-mention regex for the replayed airport's phraseology convention."""
    return RUNWAY_RE_SINGLE if single else RUNWAY_RE


def _instructions(single: bool) -> list[tuple[str, re.Pattern]]:
    """The instruction regexes for the replayed airport's phraseology convention."""
    return INSTRUCTION_RES_SINGLE if single else INSTRUCTION_RES
HANDOFF_RE = re.compile(r"\bcontact (?:[a-z]+ ){0,2}?(ground|apron|departure|tower|approach|radar)\b")
GO_AROUND_RE = re.compile(r"\bgo around\b")
_TAIL_NOISE_RE = re.compile(r"\b(?:winds?|good ?bye|bye)\b.*$")
_TO = {"ground": "ground", "apron": "ground", "departure": "departure", "tower": "tower", "approach": "approach", "radar": "approach"}
_EVENT = {"LAND": ClearToLand, "TAKEOFF": ClearTakeoff, "LUAW": LineUpAndWait, "CROSS": ClearToCross, "HOLD_SHORT": HoldShort}


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


def blank_values(text: str) -> str:
    """Same-length copy of `text` with readback item values (runway/frequency/level/heading/squawk) and the trailing
    wind clause replaced by spaces, so callsign extraction cannot mistake a value for a callsign."""
    out = text
    for _, rx in ITEM_PATTERNS:
        out = rx.sub(lambda m: " " * len(m.group()), out)
    return _TAIL_NOISE_RE.sub(lambda m: " " * len(m.group()), out)


def controller_callsign(blanked: str, first_start: int, last_end: int) -> str:
    before = take_prefix(blanked[:first_start].split())
    if before:
        return " ".join(before)
    after = take_prefix(blanked[last_end:].split())
    return " ".join(after)


_VALUE_LEAD = set("runway level heading squawk flight altitude speed wind contact descend climb maintain reduce".split())
# Words that can sit right before a callsign's id tokens without being part of its name ("reducing one sixty csa ...").
_NOT_NAME = FILLER | _VALUE_LEAD | set(
    "land takeoff up short cross left right centre center hundred thousand ten twenty thirty forty fifty sixty seventy "
    "eighty ninety vacated vacating around established ready going holding lining landing climbing descending reducing "
    "passing leaving maintaining request copied".split())
PILOT_VACATED_RE = re.compile(r"\bvacat(?:ed|ing)\b")
PILOT_GO_AROUND_RE = re.compile(r"\bgoing around\b")


def take_suffix(words: list[str]) -> list[str]:
    """Callsign at the end of `words`: trailing filler dropped, then the trailing run of id tokens plus up to 2 name
    words before it. [] if there is no id run or it is a value ("runway one three")."""
    j = len(words)
    while j > 0 and words[j - 1] in FILLER:
        j -= 1
    i = j
    while i > 0 and is_id(words[i - 1]):
        i -= 1
    if i == j:
        return []
    if i > 0 and words[i - 1] in _VALUE_LEAD:
        return []
    k = i
    while k > 0 and i - k < 2 and not is_id(words[k - 1]) and words[k - 1] not in _NOT_NAME:
        k -= 1
    return words[k:j]


def pilot_callsign(text: str) -> str:
    return " ".join(take_suffix(text.split()))


def _ids(callsign: str) -> list[str]:
    return [w for w in callsign.split() if is_id(w)]


def _names(callsign: str) -> list[str]:
    return [w for w in callsign.split() if not is_id(w)]


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    it = iter(long)
    return all(any(x == y for y in it) for x in short)


def snap_callsign(raw: str, candidates: tuple[str, ...]) -> str:
    """Map an abbreviated pilot callsign onto the one active aircraft it can only be; otherwise return it unchanged."""
    ids = _ids(raw)
    if len(ids) < 1:
        return raw
    hits = [c for c in candidates
            if _is_subsequence(ids, _ids(c)) and (not _names(raw) or not _names(c) or _names(raw) == _names(c))]
    return hits[0] if len(hits) == 1 else raw


def _desig(text: str) -> str | None:
    """`engine.normalize_runway` for a designator captured by `_DESIG`, with "oh" read as the zero digit-word. The
    substitution lives here, not in `normalize_runway`, for the reason given in the `_D_RWY` note above."""
    return normalize_runway(" ".join("zero" if w == "oh" else w for w in text.split()))


def _runway_for(text: str, m: re.Match, kind: str, ctx: Context, single: bool) -> str | None:
    if kind in ("CROSS", "HOLD_SHORT"):
        return _desig(m.group(1))
    mentions = [(min(abs(r.start() - m.end()), abs(m.start() - r.end())), r.group(1))
                for r in _runway_re(single).finditer(text)]
    if mentions:
        return _desig(min(mentions)[1])
    if ctx.mode == "window" and len(ctx.active_runways) == 1:
        return ctx.active_runways[0]
    return None


def _controller_events(tx: Transmission, ctx: Context, single: bool) -> list[Event]:
    text = tx.text
    found: list[tuple[int, int, str, str | None]] = []   # (start, end, kind, runway-or-handoff-target)
    for kind, rx in _instructions(single):
        for m in rx.finditer(text):
            runway = _runway_for(text, m, kind, ctx, single)
            if runway:
                found.append((m.start(), m.end(), kind, runway))
    for m in HANDOFF_RE.finditer(text):
        found.append((m.start(), m.end(), "HANDOFF", _TO[m.group(1)]))
    for m in GO_AROUND_RE.finditer(text):
        found.append((m.start(), m.end(), "GO_AROUND", None))
    if not found:
        return []
    found.sort()
    callsign = controller_callsign(blank_values(text), found[0][0], found[-1][1])
    events: list[Event] = []
    seen: set[tuple[str, str | None]] = set()
    for _, _, kind, arg in found:
        if (kind, arg) in seen:   # a mixed transmission repeats the instruction in the readback: keep the first
            continue
        seen.add((kind, arg))
        if kind == "HANDOFF":
            events.append(Handoff(callsign=callsign, to=arg, t=tx.start_s, text=text))
        elif kind == "GO_AROUND":
            events.append(GoAround(callsign=callsign, t=tx.start_s, text=text))
        else:
            events.append(_EVENT[kind](callsign=callsign, runway=arg, t=tx.start_s, text=text))
    return events


def _pilot_events(tx: Transmission, ctx: Context, single: bool) -> list[Event]:
    text = tx.text
    callsign = pilot_callsign(text)
    if ctx.mode == "window" and callsign:
        callsign = snap_callsign(callsign, ctx.active_callsigns)
    events: list[Event] = [ReadbackObserved(callsign=callsign, text=text, t=tx.start_s)]
    if PILOT_VACATED_RE.search(text):
        events.append(RunwayVacated(callsign=callsign, t=tx.start_s, text=text))
    if PILOT_GO_AROUND_RE.search(text):
        events.append(GoAround(callsign=callsign, t=tx.start_s, text=text))
    return events


def count_unresolved(tx: Transmission, ctx: Context, single_digit_runways: bool = False) -> int:
    """How many instruction kinds `parse` recognised in this transmission but dropped because no runway could be placed
    on them (spec addendum A.3.5). A diagnostic beside `parse`, not part of it: `parse`'s output is unchanged, so the
    frozen baseline is untouched. Pilot transmissions never yield instructions, so they count 0.

    Takes the same phraseology convention as `parse`, so the diagnostic counts what that parser actually dropped."""
    role = ctx.role if ctx.mode != "none" else "unknown"
    if role == "pilot":
        return 0
    placed, unplaced = set(), set()
    for kind, rx in _instructions(single_digit_runways):
        for m in rx.finditer(tx.text):
            (placed if _runway_for(tx.text, m, kind, ctx, single_digit_runways) else unplaced).add(kind)
    return len(unplaced - placed)


def parse(tx: Transmission, ctx: Context, single_digit_runways: bool = False) -> list[Event]:
    """Events for one transmission. Controller-side phrasing is only extracted for controller / mixed / unknown
    roles; pilot transmissions become readbacks (plus pilot-reported releases). Mode `none` has no role, so
    every transmission is treated as controller-side — a pilot's readback then becomes a reservation, which is
    exactly the failure the context ablation is meant to measure."""
    role = ctx.role if ctx.mode != "none" else "unknown"
    events = (_pilot_events(tx, ctx, single_digit_runways) if role == "pilot"
              else _controller_events(tx, ctx, single_digit_runways))
    return events or [NoOp(t=tx.start_s, text=tx.text)]


def make_parser(single_digit_runways: bool = False) -> Parser:
    """`parse` bound to one airport's phraseology convention, mirroring `parse_llm.make_parser`.

    `single_digit_runways=True` reads a lone digit-word as a designator ("runway four left" at a US tower). Keep the
    default anywhere the airport is unknown or follows ICAO practice: there a lone digit-word is an ASR truncation,
    and reading it as a designator invents a runway the transmission never named (see the `_DESIG_SINGLE` note above). The
    convention is a property of the airport, so it is bound here rather than carried on `Context`, which is the
    spec's context-ablation knob.
    """
    if not single_digit_runways:
        return parse
    return lambda tx, ctx: parse(tx, ctx, single_digit_runways=True)
