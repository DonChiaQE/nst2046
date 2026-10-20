"""What the live demo's web routes share (spec 2026-10-20-live-demo-app-design.md, Sections 2, 5 and 6): the Whisper
model, loaded once in the background; the Claude parser the app uses; the sessions; and the replay scenarios (the
Austin transcript and saved sessions). No web code here: atcdb/live_api.py routes to it.
"""
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from atcdb import parse_llm, parse_rules
from atcdb.asr import Transcriber, hf_whisper_transcriber, load_hf_whisper
from atcdb.incidents import austin_lines
from atcdb.live import ROLES, LiveSession, Track, Transcription
from atcdb.parsing import Parser

ROOT = Path(__file__).resolve().parents[1]
# The app's Claude model (spec Section 8); RUNWAY_WATCH_CLAUDE_MODEL=claude-sonnet-5 is the fallback if Haiku 5.5 fails
# the week-1 check.
CLAUDE_MODEL = os.environ.get("RUNWAY_WATCH_CLAUDE_MODEL", "claude-haiku-5-5")
CLAUDE_TIMEOUT_S = 10.0
AUSTIN_ID = "austin-2023"


class WhisperLoader:
    """Loads Whisper once, on a background thread, when `start` is first called. `get` is the transcriber, or None
    while it is idle, loading or failed."""

    def __init__(self, load: Callable[[], Transcriber]):
        self._load, self._lock = load, threading.Lock()
        self.status, self.reason, self._transcriber = "idle", None, None

    def start(self) -> None:
        with self._lock:
            if self.status != "idle":
                return
            self.status = "loading"
        threading.Thread(target=self._run, daemon=True, name="whisper-load").start()

    def _run(self) -> None:
        try:
            transcriber = self._load()
        except Exception as e:
            self.status, self.reason = "failed", f"{type(e).__name__}: {e}"
            return
        self._transcriber, self.status = transcriber, "ready"

    def get(self) -> Transcriber | None:
        return self._transcriber if self.status == "ready" else None


def gpu_whisper(model_dir: Path, device: str = "mps") -> Callable[[], Transcriber]:
    """The loader for the Hugging Face weights in `model_dir` (fetched by scripts/bench_whisper.py)."""
    def load() -> Transcriber:
        if not (model_dir / "model.safetensors").exists():
            raise FileNotFoundError(f"no Whisper weights in {model_dir}; run scripts/bench_whisper.py once")
        return hf_whisper_transcriber(*load_hf_whisper(model_dir, device), device=device)
    return load


def live_claude_parser(model: str = CLAUDE_MODEL) -> Parser:
    """The Claude parser with the live client: a 10 s timeout and one retry, so a dead connection shows as an error on
    the line within seconds. Without a key, every parse raises (the line shows why) instead of the session failing."""
    state: dict = {}

    def parse(tx, ctx):
        ok, reason = parse_llm.availability()
        if not ok:
            raise RuntimeError(reason)
        if "parser" not in state:
            import anthropic
            state["parser"] = parse_llm.make_parser(model, anthropic.Anthropic(timeout=CLAUDE_TIMEOUT_S, max_retries=1))
        return state["parser"](tx, ctx)

    return parse


def default_tracks() -> dict[str, Track]:
    return {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", live_claude_parser())}


class LiveHub:
    """The sessions and what they share. Only the newest session is live; older ones stay on disk for replays."""

    def __init__(self, sessions_dir: Path, whisper: WhisperLoader,
                 make_tracks: Callable[[], dict[str, Track]] = default_tracks, claude_model: str = CLAUDE_MODEL):
        self.sessions_dir, self.whisper, self.make_tracks, self.claude_model = sessions_dir, whisper, make_tracks, claude_model
        self.transcription = Transcription(whisper.get)
        self.sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    @classmethod
    def default(cls, root: Path = ROOT) -> "LiveHub":
        return cls(root / "data/live/sessions", WhisperLoader(gpu_whisper(root / "data/models/whisper-medium.en-atc-hf")))

    def new_session(self) -> LiveSession:
        with self._lock:
            for old in self.sessions.values():
                old.close()
            sid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            session = LiveSession(sid, self.make_tracks(), self.transcription, self.sessions_dir / sid)
            self.sessions[sid] = session
            return session

    def get(self, sid: str) -> LiveSession | None:
        return self.sessions.get(sid)

    def health(self) -> dict:
        ok, reason = parse_llm.availability()
        return {"whisper": {"status": self.whisper.status, "reason": self.whisper.reason},
                "claude": {"model": self.claude_model, "available": ok, "reason": reason},
                "extractors": ["rules", "claude"], "parser_versions": {"rules": parse_rules.VERSION,
                                                                       "claude": parse_llm.VERSION}}

    # --- replay scenarios -----------------------------------------------------------------------------------------------

    def label(self, sid: str, label: str) -> None:
        folder = self.sessions_dir / sid
        if not (folder / "session.jsonl").exists():
            raise KeyError(sid)
        (folder / "meta.json").write_text(json.dumps({"label": label}) + "\n")

    def scenarios(self) -> list[dict]:
        """The Austin transcript, then every labelled session, newest first."""
        out = [{"id": AUSTIN_ID, "title": "Austin 2023 (NTSB DCA23FA149)", "lines": len(_austin()), "audio": False}]
        for folder in sorted(self.sessions_dir.glob("*/meta.json"), reverse=True):
            sid = folder.parent.name
            out.append({"id": sid, "title": json.loads(folder.read_text())["label"], "lines": len(self._saved(sid)),
                        "audio": True})
        return out

    def scenario_lines(self, sid: str) -> list[dict]:
        """Lines to replay, in order: role, t, text, Apple's preview text, and the clip's URL for a saved session."""
        if sid == AUSTIN_ID:
            return _austin()
        if not (self.sessions_dir / sid / "session.jsonl").exists():
            raise KeyError(sid)
        return self._saved(sid)

    def clip_path(self, sid: str, seq: int) -> Path | None:
        path = self.sessions_dir / sid / f"clip_{seq}.wav"
        return path if path.is_file() else None

    def _saved(self, sid: str) -> list[dict]:
        events = [json.loads(x) for x in (self.sessions_dir / sid / "session.jsonl").read_text().splitlines()]
        undone = {e["seq"] for e in events if e["type"] == "undone"}
        return [{"role": e["role"], "t": e["t"], "text": e["text"], "preview_text": e["preview_text"],
                 "audio": f"/api/live/sessions/{sid}/clips/{e['seq']}" if self.clip_path(sid, e["seq"]) else None}
                for e in events if e["type"] == "transcript" and not e["error"] and e["seq"] not in undone]


def _austin() -> list[dict]:
    """The Austin lines as replay lines. Unidentified speakers (UNK: off-frequency chatter) are left out."""
    return [{"role": tx.role, "t": tx.start_s, "text": tx.text, "preview_text": "", "audio": None}
            for _, tx in austin_lines() if tx.role in ROLES]
