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
from typing import ClassVar

from atcdb.readback import check_readback, extract_items

_DIGIT_WORD = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
               "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_SIDE = {"left": "L", "right": "R", "centre": "C", "center": "C", "l": "L", "r": "R", "c": "C"}
_RUNWAY_RE = re.compile(r"^(\d{2})([lrc])?$")


def normalize_runway(text: str) -> str | None:
    """'three one' -> '31', 'one six right' -> '16R', '16r' -> '16R'. None if it is not a runway designator."""
    words = (text or "").strip().lower().split()
    if not words:
        return None
    if all(w in _DIGIT_WORD for w in words[:2]) and len(words) >= 2:
        digits = _DIGIT_WORD[words[0]] + _DIGIT_WORD[words[1]]
        rest = words[2:]
    else:
        m = _RUNWAY_RE.match(words[0])
        if not m:
            return None
        digits, rest = m.group(1), ([m.group(2)] if m.group(2) else []) + words[1:]
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


@dataclass(frozen=True, kw_only=True)
class Handoff(Event):
    to: str              # ground | departure | tower | approach


@dataclass(frozen=True, kw_only=True)
class ReadbackObserved(Event):
    text: str


@dataclass(frozen=True, kw_only=True)
class NoOp(Event):
    pass


RESERVATION_KINDS = ("LAND", "TAKEOFF", "LUAW", "CROSS")
