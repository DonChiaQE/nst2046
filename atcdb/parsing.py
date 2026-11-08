"""Types shared by every parser (rules now, Claude later) and the `events` table serialization.

A parser is `parse(tx: Transmission, ctx: Context) -> list[Event]`. `Context` is the ablatable
knob from the spec: mode `none` gives the parser nothing but the text, `role` adds the speaker role
from the DB, `window` adds the last WINDOW transmissions and what the engine currently tracks.
"""
import json
from dataclasses import dataclass
from typing import Callable

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort, LineUpAndWait,
                          NoOp, ReadbackObserved, RunwayInstruction, RunwayVacated, Unresolved)

CONTEXT_MODES = ("none", "role", "window")
WINDOW = 4   # how many previous transmissions `window` mode carries


@dataclass(frozen=True)
class Transmission:
    id: int              # transmissions.id
    transcript_id: int   # transcripts.id that `text` came from (gold or asr)
    text: str            # normalized transcript text
    role: str            # pilot | controller | mixed | unknown (from the DB)
    start_s: float


@dataclass(frozen=True)
class Context:
    mode: str = "window"                            # none | role | window
    role: str = "unknown"                           # speaker role; 'unknown' in mode none
    history: tuple[tuple[str, str], ...] = ()       # (role, text) of the previous WINDOW transmissions, oldest first
    active_callsigns: tuple[str, ...] = ()          # aircraft the engine currently tracks (window mode only)
    active_runways: tuple[str, ...] = ()            # runways with an active reservation (window mode only)


Parser = Callable[[Transmission, Context], list[Event]]

KINDS: dict[type, str] = {ClearToLand: "LAND", ClearTakeoff: "TAKEOFF", LineUpAndWait: "LUAW", ClearToCross: "CROSS",
                          HoldShort: "HOLD_SHORT", RunwayVacated: "VACATED", GoAround: "GO_AROUND", Handoff: "HANDOFF",
                          ReadbackObserved: "READBACK", NoOp: "NOOP", Unresolved: "UNRESOLVED"}
_BY_KIND = {v: k for k, v in KINDS.items()}


def event_to_row(e: Event) -> tuple[str, str, str | None, str | None]:
    """(kind, callsign, runway, extra_json). `t` and `text` are not stored: they are re-attached from the transcript."""
    runway = e.runway if isinstance(e, RunwayInstruction) else None
    extra = None
    if isinstance(e, Handoff):
        extra = json.dumps({"to": e.to})
    elif isinstance(e, Unresolved):
        extra = json.dumps({"raw": e.raw})
    return KINDS[type(e)], e.callsign, runway, extra


def row_to_event(kind: str, callsign: str, runway: str | None, extra_json: str | None, t: float = 0.0, text: str = "") -> Event:
    cls = _BY_KIND[kind]   # KeyError on an unknown kind is deliberate
    extra = json.loads(extra_json) if extra_json else {}
    if issubclass(cls, RunwayInstruction):
        return cls(callsign=callsign, runway=runway, t=t, text=text)
    if cls is Handoff:
        return Handoff(callsign=callsign, to=extra["to"], t=t, text=text)
    if cls is Unresolved:
        return Unresolved(callsign=callsign, raw=extra.get("raw", ""), t=t, text=text)
    if cls is ReadbackObserved:
        return ReadbackObserved(callsign=callsign, text=text, t=t)
    return cls(callsign=callsign, t=t, text=text)
