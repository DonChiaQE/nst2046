"""Live sessions for the Runway Watch demo app (spec 2026-10-20-live-demo-app-design.md, Sections 5 and 6).

A session is an ordered list of lines (transmissions) and one `Track` per extractor. A track folds each line through
its parser and its own copy of the engine, in `window` context, as `replay.build_timeline` does but without the events
cache: live lines are not in the corpus DB. `LiveSession` adds the order and the threads: lines are numbered when they
are submitted, transcribed one at a time in that order, then handed to one worker per track, so the rules track never
waits for Claude. Everything a session does is an event in one list, which the web layer streams and the session
folder logs. No web code here: atcdb/live_api.py routes to it.
"""
from dataclasses import dataclass

from atcdb.engine import Conflict, Event, NoOp, State, apply
from atcdb.parsing import Parser, Transmission
from atcdb.replay import build_context
from atcdb.serialize import board_dict, conflict_dict, event_dict


@dataclass(frozen=True)
class Line:
    seq: int
    role: str                # controller | pilot
    t: float                 # engine time, seconds
    text: str                # the normalized transcript every extractor reads
    source: str              # speech | typed | replay
    transcriber: str         # whisper | apple | none (typed or scripted text)
    preview_text: str = ""   # Apple's text while the person spoke, as the app sent it

    def transmission(self) -> Transmission:
        return Transmission(id=self.seq, transcript_id=self.seq, text=self.text, role=self.role, start_s=self.t)


@dataclass(frozen=True)
class TrackStep:
    seq: int
    events: tuple[Event, ...]
    conflicts: tuple[Conflict, ...]
    state: State                 # this track's engine after the line
    error: str | None = None     # the parser failed: no events, state unchanged


class Track:
    """One extractor's view of a session: its parser and its own engine, one step per line it has handled."""

    def __init__(self, name: str, parse: Parser):
        self.name, self.parse, self.steps = name, parse, []

    @property
    def state(self) -> State:
        return self.steps[-1].state if self.steps else State()

    def compute(self, line: Line, history: list[Line]) -> TrackStep:
        """The step for `line` after the current state, in `window` context over `history` (the lines before it,
        oldest first). Does not change the track. A parser exception gives an error step with the state unchanged."""
        tx = line.transmission()
        state = self.state
        ctx = build_context("window", tx, [h.transmission() for h in history], state)
        try:
            events, error = tuple(self.parse(tx, ctx)), None
        except Exception as e:   # an API error or an unusable reply must not stop the demo
            events, error = (), f"{type(e).__name__}: {e}"
        conflicts: list[Conflict] = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        return TrackStep(line.seq, events, tuple(conflicts), state, error)

    def push(self, step: TrackStep) -> None:
        self.steps.append(step)

    def apply(self, line: Line, history: list[Line]) -> TrackStep:
        step = self.compute(line, history)
        self.push(step)
        return step

    def undo(self, seq: int) -> bool:
        """Drop the step for `seq` if it is the last one; whether it was."""
        if self.steps and self.steps[-1].seq == seq:
            self.steps.pop()
            return True
        return False

    def truncate(self, seq: int) -> None:
        """Drop every step from `seq` on, so the track can redo them (Retry)."""
        self.steps = [s for s in self.steps if s.seq < seq]


def step_payload(track: str, step: TrackStep) -> dict:
    """The `extraction` event for one track's step, in the JSON API's shapes (atcdb/serialize.py). NOOP events are left
    out: an empty list means the extractor understood nothing in the line."""
    return {"seq": step.seq, "extractor": track, "events": [event_dict(e) for e in step.events if not isinstance(e, NoOp)],
            "conflicts": [conflict_dict(c) for c in step.conflicts], "runways": board_dict(step.state),
            "error": step.error}
