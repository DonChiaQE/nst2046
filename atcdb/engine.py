"""Runway-conflict engine: typed events, a pure state fold, and the conflict rules.

No I/O here. A parser (atcdb/parse_rules.py, later atcdb/parse_llm.py) turns a transmission into
a list of events; `apply` folds one event into a frozen `State` and returns the conflicts it raised.
Because the fold is pure, "state after transmission k" is just a fold over the first k transmissions'
events, and tests are event lists in, conflicts out.

Domain: LAND = cleared to land, TAKEOFF = cleared for takeoff, LUAW = line up and wait (enter the
runway and hold), CROSS = cross the runway while taxiing, HOLD_SHORT = stop before the runway.
"""
import re
from dataclasses import dataclass, field, replace
from typing import ClassVar, Iterable

from atcdb.readback import check_readback, extract_items

_DIGIT_WORD = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
               "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_SIDE = {"left": "L", "right": "R", "centre": "C", "center": "C", "l": "L", "r": "R", "c": "C"}
_RUNWAY_RE = re.compile(r"^(\d{1,2})([lrc])?$")


def normalize_runway(text: str) -> str | None:
    """'three one' -> '31', 'one six right' -> '16R', '16r' -> '16R', 'four left' -> '04L'. None if it is not a runway
    designator. A single digit is zero-padded: US controllers say "runway four left" where ICAO says "zero four left"."""
    words = (text or "").strip().lower().split()
    if not words:
        return None
    if words[0] in _DIGIT_WORD:
        if len(words) >= 2 and words[1] in _DIGIT_WORD:
            digits, rest = _DIGIT_WORD[words[0]] + _DIGIT_WORD[words[1]], words[2:]
        else:
            digits, rest = "0" + _DIGIT_WORD[words[0]], words[1:]
    else:
        m = _RUNWAY_RE.match(words[0])
        if not m:
            return None
        digits, rest = m.group(1).zfill(2), ([m.group(2)] if m.group(2) else []) + words[1:]
    if not 1 <= int(digits) <= 36:
        return None
    if len(rest) > 1 or (rest and rest[0] not in _SIDE):
        return None
    return digits + (_SIDE[rest[0]] if rest else "")


# --- events -----------------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class Event:
    callsign: str = ""   # normalized transcript words, e.g. "csa one two three"; "" = unknown
    t: float = 0.0       # transmission start_s; drives the staleness timeout
    text: str = ""       # source transmission text; on an instruction, what the pilot must read back


@dataclass(frozen=True, kw_only=True)
class RunwayInstruction(Event):
    runway: str          # normalized designator, e.g. "31", "16R"
    kind: ClassVar[str] = ""


class ClearToLand(RunwayInstruction):
    kind = "LAND"


class ClearTakeoff(RunwayInstruction):
    kind = "TAKEOFF"


class LineUpAndWait(RunwayInstruction):
    kind = "LUAW"


class ClearToCross(RunwayInstruction):
    kind = "CROSS"


class HoldShort(RunwayInstruction):
    kind = "HOLD_SHORT"


@dataclass(frozen=True, kw_only=True)
class RunwayVacated(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class GoAround(Event):
    pass


HANDOFF_TARGETS = ("ground", "departure", "tower", "approach")


@dataclass(frozen=True, kw_only=True)
class Handoff(Event):
    to: str              # one of HANDOFF_TARGETS; anything else releases nothing and is counted in State.ignored


@dataclass(frozen=True, kw_only=True)
class ReadbackObserved(Event):
    text: str


@dataclass(frozen=True, kw_only=True)
class NoOp(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class Unresolved(Event):
    raw: str = ""        # what the parser reported, verbatim (e.g. a runway that does not normalise); never acted on


RESERVATION_KINDS = ("LAND", "TAKEOFF", "LUAW", "CROSS")


# --- state ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Reservation:
    callsign: str
    kind: str            # LAND | TAKEOFF | LUAW | CROSS
    seq: int             # event seq that created it
    t: float             # transmission time it was created at


@dataclass(frozen=True)
class Aircraft:
    callsign: str
    runway: str | None = None          # runway of its active reservation, if any
    kind: str | None = None            # kind of that reservation
    holding_short: str | None = None   # runway it was told to hold short of
    holding_short_t: float | None = None   # transmission time of that instruction; drives its staleness
    pending: str | None = None         # instruction text awaiting the pilot's readback
    last_seq: int = 0


@dataclass(frozen=True)
class Conflict:
    type: str                    # RUNWAY | READBACK
    severity: str                # alert | warning
    runway: str | None
    callsigns: tuple[str, ...]   # triggering callsign first
    seq: int                     # seq of the triggering event
    explanation: str             # what the app displays
    basis: str | None = None     # id of the phraseology_rules row this conflict rests on (atcdb/doctrine.py), if any


@dataclass(frozen=True)
class State:
    seq: int = 0
    runways: dict[str, tuple[Reservation, ...]] = field(default_factory=dict)
    aircraft: dict[str, Aircraft] = field(default_factory=dict)
    ignored: int = 0     # events so far that the engine received but could not act on (unknown handoff target, Unresolved)


# --- rules ------------------------------------------------------------------------------------

# Bumped by hand whenever a change to the rules below can change what the engine tracks. `window`-mode parses see the
# engine's active runways and callsigns, so the events cache keys them by this too (spec addendum A.7.2).
# "1" = the engine after phase 2.5.
ENGINE_VERSION = "1"

# A reservation (or hold-short) older than its kind's timeout, in transmission time, is dropped silently: we missed the
# release call. Per kind so that 3b can shorten CROSS and LUAW against the false-alarm metric (spec addendum A.3.6).
# LAND must stay >= 284 s: at Austin 2023 the landing and the conflicting takeoff clearance were 284 s apart.
STALE_S: dict[str, float] = {"LAND": 300.0, "TAKEOFF": 300.0, "LUAW": 300.0, "CROSS": 300.0, "HOLD_SHORT": 300.0}

# (new_kind, active_kind) -> verdict, checked against OTHER aircraft's reservations on the same runway.
# LAND after LAND is legal (anticipated separation). LUAW then LAND is the Austin 2023 pattern.
# A conflict where either side's callsign is unknown ("") is capped at warning in `apply`: the engine cannot
# tell whether an unidentified aircraft is a different aircraft from the one it conflicts with.
MATRIX: dict[tuple[str, str], str] = {
    ("LAND", "LAND"): "ok",        ("LAND", "TAKEOFF"): "alert",      ("LAND", "LUAW"): "alert",      ("LAND", "CROSS"): "alert",
    ("TAKEOFF", "LAND"): "alert",  ("TAKEOFF", "TAKEOFF"): "warning", ("TAKEOFF", "LUAW"): "alert",   ("TAKEOFF", "CROSS"): "alert",
    ("LUAW", "LAND"): "alert",     ("LUAW", "TAKEOFF"): "warning",    ("LUAW", "LUAW"): "warning",    ("LUAW", "CROSS"): "warning",
    ("CROSS", "LAND"): "alert",    ("CROSS", "TAKEOFF"): "alert",     ("CROSS", "LUAW"): "warning",   ("CROSS", "CROSS"): "ok",
}

# The same check against a reservation held from the strip's OTHER end (13 against 31). Identical to MATRIX except the
# two cells that are legal only because both aircraft move the same way: two landings or two departures from opposite
# ends are head-on. A crossing does not depend on direction, so CROSS/CROSS stays ok.
OPPOSITE_MATRIX: dict[tuple[str, str], str] = {**MATRIX, ("LAND", "LAND"): "alert", ("TAKEOFF", "TAKEOFF"): "alert"}

# (new_kind, active_kind) -> the atcdb/doctrine.py rule that cell encodes. Cells without an entry have no verified citation.
MATRIX_BASIS: dict[tuple[str, str], str] = {
    ("LAND", "LAND"): "icao-4444-7.10.2-proviso",
    ("TAKEOFF", "LAND"): "icao-4444-7.9.2",
    ("LAND", "TAKEOFF"): "icao-4444-7.10.1",
}

_PHRASE = {"LAND": "a landing clearance", "TAKEOFF": "a takeoff clearance",
           "LUAW": "a line-up-and-wait instruction", "CROSS": "a crossing clearance"}


def _name(callsign: str) -> str:
    return callsign or "an unidentified aircraft"


def reciprocal(runway: str) -> str:
    """The other end of the same strip, for a normalized designator: 13 -> 31, 04 -> 22, 18L -> 36R, 06C -> 24C."""
    m = re.match(r"^(\d{2})([LRC]?)$", runway)
    if not m:
        return runway
    number = (int(m.group(1)) + 17) % 36 + 1
    return f"{number:02d}{ {'L': 'R', 'R': 'L'}.get(m.group(2), m.group(2)) }".replace(" ", "")


def _release(runways: dict[str, tuple[Reservation, ...]], callsign: str, kinds: tuple[str, ...] = RESERVATION_KINDS,
             runway: str | None = None) -> tuple[dict[str, tuple[Reservation, ...]], bool]:
    """Drop `callsign`'s reservations of the given kinds (only on `runway`, if given). Returns (new runways, whether
    anything was dropped)."""
    out, dropped = {}, False
    for rwy, res in runways.items():
        keep = tuple(r for r in res if not (r.callsign == callsign and r.kind in kinds and runway in (None, rwy)))
        dropped = dropped or len(keep) != len(res)
        if keep:
            out[rwy] = keep
    return out, dropped


def _expire(state: State, now: float) -> tuple[dict[str, tuple[Reservation, ...]], dict[str, Aircraft]]:
    """Copy of the runway map and aircraft map with reservations and hold-shorts older than their STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for cs, a in aircraft.items():
        if a.holding_short and a.holding_short_t is not None and now - a.holding_short_t > STALE_S["HOLD_SHORT"]:
            aircraft[cs] = replace(a, holding_short=None, holding_short_t=None)
    for rwy, res in state.runways.items():
        keep = tuple(r for r in res if now - r.t <= STALE_S[r.kind])
        for r in res:
            if r not in keep and r.callsign in aircraft:
                aircraft[r.callsign] = replace(aircraft[r.callsign], runway=None, kind=None)
        if keep:
            runways[rwy] = keep
    return runways, aircraft


def apply(state: State, event: Event) -> tuple[State, list[Conflict]]:
    """Fold one event into the state. Pure: returns a new State and the conflicts this event raised."""
    seq = state.seq + 1
    runways, aircraft = _expire(state, event.t)
    conflicts: list[Conflict] = []
    ignored = state.ignored
    cs = event.callsign
    ac = aircraft.get(cs, Aircraft(callsign=cs)) if cs else None

    if isinstance(event, RunwayInstruction) and event.kind in RESERVATION_KINDS:
        if cs:
            runways, _ = _release(runways, cs)   # one aircraft is in one place: its old reservation is superseded
        other_end = reciprocal(event.runway)
        ends = [(event.runway, False)] + ([(other_end, True)] if other_end != event.runway else [])
        for rwy, opposite in ends:   # one strip, two designators: check reservations held from either end
            for r in runways.get(rwy, ()):
                verdict = (OPPOSITE_MATRIX if opposite else MATRIX)[(event.kind, r.kind)]
                if verdict == "ok":
                    continue
                if not cs or not r.callsign:
                    verdict = "warning"   # an unidentified aircraft may be the same aircraft: tunable, see spec Section 1
                conflicts.append(Conflict(
                    "RUNWAY", verdict, event.runway, (cs, r.callsign), seq,
                    f"{_name(cs)} given {_PHRASE[event.kind]} on runway {event.runway} while "
                    f"{_name(r.callsign)} still holds {_PHRASE[r.kind]} on runway {rwy}",
                    None if opposite else MATRIX_BASIS.get((event.kind, r.kind))))
        runways[event.runway] = runways.get(event.runway, ()) + (Reservation(cs, event.kind, seq, event.t),)
        if cs:
            aircraft[cs] = replace(ac, runway=event.runway, kind=event.kind, holding_short=None, holding_short_t=None,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, HoldShort):
        if cs:
            # "hold short runway 13" cancels this aircraft's clearance for 13; a hold-short of another runway releases
            # nothing (a crossing clearance for 13 often ends "... hold short of runway 24").
            runways, dropped = _release(runways, cs, runway=event.runway)
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   holding_short=event.runway, holding_short_t=event.t,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, RunwayVacated):
        runways, _ = _release(runways, cs) if cs else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None, kind=None, holding_short=None, holding_short_t=None, last_seq=seq)
    elif isinstance(event, GoAround):
        runways, dropped = _release(runways, cs, ("LAND",)) if cs else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind, last_seq=seq)
    elif isinstance(event, Handoff):
        if event.to not in HANDOFF_TARGETS:   # releases nothing, but the fold counts it (spec addendum A.3.4)
            ignored += 1
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
        runways, dropped = _release(runways, cs, kinds) if cs and kinds else (runways, False)
        if cs:
            leaving = event.to in ("ground", "departure")   # off the tower's runways: any hold-short no longer applies
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   holding_short=None if leaving else ac.holding_short,
                                   holding_short_t=None if leaving else ac.holding_short_t,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, ReadbackObserved):
        if ac is not None and ac.pending:
            missing = [(k, v) for k, v, verdict in check_readback(extract_items(ac.pending), event.text) if verdict == "missing"]
            if missing:
                severity = "alert" if any(k == "runway" for k, _ in missing) else "warning"
                what = ", ".join(f"{k} {v}" for k, v in missing)
                missed_runway = next((normalize_runway(v) for k, v in missing if k == "runway"), None)
                conflicts.append(Conflict(
                    "READBACK", severity, missed_runway or ac.runway or ac.holding_short, (cs,), seq,
                    f"{cs} did not read back {what} (instruction: '{ac.pending}'; readback: '{event.text}')"))
            aircraft[cs] = replace(ac, pending=None, last_seq=seq)
    elif isinstance(event, Unresolved):
        ignored += 1   # a parser saw an instruction it could not express as an event: counted, never acted on
    elif isinstance(event, NoOp):
        pass
    return State(seq=seq, runways=runways, aircraft=aircraft, ignored=ignored), conflicts


def fold(events: Iterable[Event], state: State | None = None) -> tuple[State, list[Conflict]]:
    """Apply events in order. Returns the final state and every conflict raised along the way."""
    state = state or State()
    conflicts: list[Conflict] = []
    for e in events:
        state, new = apply(state, e)
        conflicts.extend(new)
    return state, conflicts
