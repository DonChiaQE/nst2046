"""Rules parser: regexes over normalized transcript text -> engine events. The non-LLM baseline.

Known blind spots (report material): conditional clearances ("behind the landing airbus, line up"),
clipped or nonstandard phrasing, callsigns that are not at the start (controller) or end (pilot) of
the transmission, "go around" said *about* another aircraft, instructions to two aircraft in one call.
Bump VERSION whenever a pattern changes so cached events (atcdb/replay.get_events) are invalidated.
"""
import re

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated, normalize_runway)
from atcdb.parsing import Context, Transmission
from atcdb.readback import D, ITEM_PATTERNS

VERSION = "v1"

DIGITS = set("zero one two three four five six seven eight nine niner".split())
NATO = set("alfa alpha bravo charlie delta echo foxtrot golf hotel india juliett juliet kilo lima mike november oscar oskar "
           "papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu".split())
FILLER = set("roger ok okay tower ground hello hi good morning afternoon evening day bye thank you thanks and break copied "
             "wilco affirm yes yeah we are will expedite to the now sir again say please confirm correct that s is it for of "
             "your wait ruzyne".split())
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


def _runway_for(text: str, m: re.Match, kind: str, ctx: Context) -> str | None:
    if kind in ("CROSS", "HOLD_SHORT"):
        return normalize_runway(m.group(1))
    mentions = [(min(abs(r.start() - m.end()), abs(m.start() - r.end())), r.group(1)) for r in RUNWAY_RE.finditer(text)]
    if mentions:
        return normalize_runway(min(mentions)[1])
    if ctx.mode == "window" and len(ctx.active_runways) == 1:
        return ctx.active_runways[0]
    return None


def _controller_events(tx: Transmission, ctx: Context) -> list[Event]:
    text = tx.text
    found: list[tuple[int, int, str, str | None]] = []   # (start, end, kind, runway-or-handoff-target)
    for kind, rx in INSTRUCTION_RES:
        for m in rx.finditer(text):
            runway = _runway_for(text, m, kind, ctx)
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


def _pilot_events(tx: Transmission, ctx: Context) -> list[Event]:
    return []   # Task 8


def parse(tx: Transmission, ctx: Context) -> list[Event]:
    """Events for one transmission. Controller-side phrasing is only extracted for controller / mixed / unknown
    roles; pilot transmissions become readbacks (plus pilot-reported releases). Mode `none` has no role, so
    every transmission is treated as controller-side — a pilot's readback then becomes a reservation, which is
    exactly the failure the context ablation is meant to measure."""
    role = ctx.role if ctx.mode != "none" else "unknown"
    events = _pilot_events(tx, ctx) if role == "pilot" else _controller_events(tx, ctx)
    return events or [NoOp(t=tx.start_s, text=tx.text)]
