"""Live sessions for the Runway Watch demo app (spec 2026-10-20-live-demo-app-design.md, Sections 5 and 6).

A session is an ordered list of lines (transmissions) and one `Track` per extractor. A track folds each line through
its parser and its own copy of the engine, in `window` context, as `replay.build_timeline` does but without the events
cache: live lines are not in the corpus DB. `LiveSession` adds the order and the threads: lines are numbered when they
are submitted, transcribed one at a time in that order, then handed to one worker per track, so the rules track never
waits for Claude. Everything a session does is an event in one list, which the web layer streams and the session
folder logs. No web code here: atcdb/live_api.py routes to it.
"""
import io
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import soundfile as sf

from atcdb.asr import Transcriber, normalize_asr_text
from atcdb.engine import Conflict, Event, NoOp, State, apply
from atcdb.parsing import Parser, Transmission
from atcdb.replay import build_context
from atcdb.serialize import board_dict, conflict_dict, event_dict

ROLES = ("controller", "pilot")
SOURCES = ("speech", "typed", "replay")
TRANSCRIBERS = ("whisper", "apple")
MIN_CLIP_S = 0.5          # shorter clips are dropped: Whisper invents words on near-silence
WHISPER_TIMEOUT_S = 8.0   # after this, the line uses Apple's text instead


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


def clip_seconds(wav: bytes) -> float:
    """Duration of a WAV clip; ValueError if the bytes are not a readable audio file."""
    try:
        info = sf.info(io.BytesIO(wav))
    except Exception as e:
        raise ValueError(f"not a readable WAV clip: {e}") from None
    return info.frames / info.samplerate


class Transcription:
    """A clip's text for a line: Whisper with a timeout, else Apple's preview text, both normalized like the corpus's
    ASR transcripts. One Whisper call runs at a time; while a timed-out call is still running, later lines use Apple's
    text at once instead of queueing behind it."""

    def __init__(self, whisper: Callable[[], Transcriber | None], timeout_s: float = WHISPER_TIMEOUT_S):
        self.whisper, self.timeout_s = whisper, timeout_s
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="whisper")
        self._running = None

    def __call__(self, clip: Path, preview_text: str, prefer: str) -> tuple[str, str]:
        """(normalized text, "whisper" or "apple")."""
        transcriber = self.whisper() if prefer == "whisper" else None
        if transcriber is not None and not (self._running and not self._running.done()):
            self._running = self._pool.submit(transcriber, clip)
            try:
                return normalize_asr_text(self._running.result(timeout=self.timeout_s)["text"]), "whisper"
            except Exception:   # timed out or failed: fall back for this line
                pass
        return normalize_asr_text(preview_text), "apple"


@dataclass
class _Pending:
    seq: int
    role: str
    t: float
    source: str
    text: str = ""                 # typed or scripted text, already final
    clip: Path | None = None       # a recorded clip still to transcribe
    preview_text: str = ""
    prefer: str = "whisper"


@dataclass
class LiveSession:
    """One demo session. `submit_text` and `submit_audio` return the line's number at once; the work happens on the
    session's threads, and every result is appended to `events` (see `events_after`)."""

    session_id: str
    tracks: dict[str, Track]
    transcription: Transcription
    folder: Path                  # clips and session.jsonl
    lines: dict[int, Line] = field(default_factory=dict)
    undone: set[int] = field(default_factory=set)

    def __post_init__(self):
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._events: list[dict] = []
        self._next_seq = 0
        self._intake: queue.Queue = queue.Queue()
        self._queues = {name: queue.Queue() for name in self.tracks}
        self._done_through = {name: -1 for name in self.tracks}   # highest seq each track has handled
        self.folder.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._intake_worker, daemon=True, name=f"{self.session_id}-intake").start()
        for name in self.tracks:
            threading.Thread(target=self._track_worker, args=(name,), daemon=True,
                             name=f"{self.session_id}-{name}").start()

    # --- submitting ---------------------------------------------------------------------------------------------------

    def _take_seq(self) -> int:
        with self._lock:
            seq, self._next_seq = self._next_seq, self._next_seq + 1
            return seq

    def submit_text(self, role: str, t: float, text: str, source: str = "typed") -> int:
        _check(role, source)
        seq = self._take_seq()
        self._intake.put(_Pending(seq, role, t, source, text=text))
        return seq

    def submit_audio(self, role: str, t: float, wav: bytes, preview_text: str = "", prefer: str = "whisper",
                     source: str = "speech") -> int | None:
        """The line's number, or None for a clip under MIN_CLIP_S (a `dropped` event says so)."""
        _check(role, source)
        if prefer not in TRANSCRIBERS:
            raise ValueError(f"unknown transcriber {prefer!r}; expected one of {TRANSCRIBERS}")
        seconds = clip_seconds(wav)
        if seconds < MIN_CLIP_S:
            self._emit("dropped", {"role": role, "t": t, "reason": "Too short", "seconds": round(seconds, 2)})
            return None
        seq = self._take_seq()
        clip = self.folder / f"clip_{seq}.wav"
        clip.write_bytes(wav)
        self._intake.put(_Pending(seq, role, t, source, clip=clip, preview_text=preview_text, prefer=prefer))
        return seq

    # --- undo and retry -------------------------------------------------------------------------------------------------

    def undo(self) -> int | None:
        """Undo the newest line not yet undone (even one still being transcribed or parsed); its number, or None."""
        with self._lock:
            live = [s for s in range(self._next_seq) if s not in self.undone]
            if not live:
                return None
            seq = live[-1]
            self.undone.add(seq)
            for track in self.tracks.values():
                track.undo(seq)
            self._emit("undone", {"seq": seq})
            return seq

    def retry(self, extractor: str, seq: int) -> None:
        """Redo `extractor` from line `seq` on: that line and every later line it has handled, in order."""
        if extractor not in self.tracks:
            raise ValueError(f"unknown extractor {extractor!r}; expected one of {sorted(self.tracks)}")
        self._queues[extractor].put(("retry", seq))

    # --- events ---------------------------------------------------------------------------------------------------------

    def _emit(self, kind: str, payload: dict) -> None:
        with self._changed:
            event = {"id": len(self._events), "type": kind, **payload}
            self._events.append(event)
            with (self.folder / "session.jsonl").open("a") as fh:
                fh.write(json.dumps(event) + "\n")
            self._changed.notify_all()

    def events_after(self, after: int = -1, timeout: float | None = None) -> list[dict]:
        """Events with an id above `after`, waiting up to `timeout` seconds for one if there are none yet."""
        with self._changed:
            self._changed.wait_for(lambda: len(self._events) > after + 1, timeout=timeout)
            return list(self._events[after + 1:])

    def wait_for(self, predicate: Callable[[list[dict]], bool], timeout: float = 5.0) -> list[dict]:
        """Block until `predicate(all events)` holds; the events. TimeoutError if it does not within `timeout`."""
        with self._changed:
            if not self._changed.wait_for(lambda: predicate(self._events), timeout=timeout):
                raise TimeoutError(f"condition not met; events so far: {self._events}")
            return list(self._events)

    # --- workers --------------------------------------------------------------------------------------------------------

    def close(self) -> None:
        """Stop the session's threads once they finish what they hold."""
        self._intake.put(None)
        for q in self._queues.values():
            q.put(None)

    def _intake_worker(self) -> None:
        while (p := self._intake.get()) is not None:
            if p.clip is not None:
                text, transcriber = self.transcription(p.clip, p.preview_text, p.prefer)
            else:
                text, transcriber = normalize_asr_text(p.text), "none"
            with self._lock:
                if p.seq in self.undone:
                    continue
                line = Line(p.seq, p.role, p.t, text, p.source, transcriber, p.preview_text)
                self._emit("transcript", {"seq": p.seq, "role": p.role, "t": p.t, "text": text,
                                          "source": p.source, "transcriber": transcriber,
                                          "preview_text": p.preview_text,
                                          "error": None if text else "No speech recognized"})
                if not text:
                    continue
                self.lines[p.seq] = line
            for q in self._queues.values():
                q.put(("line", p.seq))

    def _history(self, seq: int) -> list[Line]:
        return [self.lines[s] for s in sorted(self.lines) if s < seq and s not in self.undone]

    def _handle(self, name: str, seq: int) -> None:
        track = self.tracks[name]
        with self._lock:
            if seq in self.undone:
                return
            line, history = self.lines[seq], self._history(seq)
        step = track.compute(line, history)   # the slow part (a Claude call), outside the lock
        with self._lock:
            self._done_through[name] = max(self._done_through[name], seq)
            if seq in self.undone:   # undone while it was being parsed
                return
            track.push(step)
            self._emit("extraction", step_payload(name, step))

    def _track_worker(self, name: str) -> None:
        while (item := self._queues[name].get()) is not None:
            kind, seq = item
            if kind == "line":
                self._handle(name, seq)
                continue
            with self._lock:   # retry: redo every line from seq that this track has already handled
                redo = [s for s in sorted(self.lines) if seq <= s <= self._done_through[name] and s not in self.undone]
                self.tracks[name].truncate(seq)
            for s in redo:
                self._handle(name, s)


def _check(role: str, source: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")
