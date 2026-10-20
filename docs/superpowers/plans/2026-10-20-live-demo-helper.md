# Live demo helper (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Python side of the Runway Watch live demo: a local helper that takes spoken, typed or replayed radio lines, transcribes them with the ATC Whisper model on the Mac's GPU, runs the rules parser and Claude (Haiku 5.5) side by side, each with its own conflict engine, and streams the results to the Mac app.

**Architecture:** `atcdb/live.py` holds the session logic (one `Track` per extractor, a `LiveSession` that orders lines and runs one worker thread per track), with no web code. `atcdb/live_hub.py` holds what sessions share (the Whisper model loaded in the background, the live Claude parser, replay scenarios). `atcdb/live_api.py` routes `/api/live/` on the existing FastAPI app. The helper reuses the evaluated code (`engine.apply`, `parse_rules.parse`, `parse_llm`, `replay.build_context`, `asr.normalize_asr_text`) unchanged.

**Tech Stack:** Python 3, FastAPI (server-sent events through `StreamingResponse`), threads and queues, PyTorch `mps` + `transformers` for Whisper, `soundfile`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-live-demo-app-design.md` (with the planning amendments below). Plan B, the SwiftUI app, is written after this plan's operational steps, because their results (Whisper speed, the Haiku 5.5 check) shape it.

## Global Constraints

- Run tests with the key unset so no test can spend money: `env -u ANTHROPIC_API_KEY python -m pytest -q` (from the repo root, with `.venv` active).
- No paid API call anywhere in this plan's tasks. The paid steps are operational step O2, which the controlling session runs only after the user approves the spend.
- The app's Claude model: `claude-haiku-5-5`, settings `thinking: {type: "disabled"}`, `output_config: {effort: "low"}`, no sampling parameters. `RUNWAY_WATCH_CLAUDE_MODEL=claude-sonnet-5` is the fallback.
- The evaluation's arms stay on `evaluate.EVAL_MODELS = ("claude-haiku-4-5", "claude-sonnet-5")`; adding a parser model must not add paid arms.
- Helper port 8020, host 127.0.0.1. Sessions under `data/live/sessions/` (git-ignored through `data/*`).
- `MIN_CLIP_S = 0.5`; `WHISPER_TIMEOUT_S = 8.0`; `CLAUDE_TIMEOUT_S = 10.0` with one retry.
- Whisper weights `jacktol/whisper-medium.en-fine-tuned-for-ATC` in `data/models/whisper-medium.en-atc-hf`, on `mps`, half precision.
- API roles are `controller` and `pilot` (the app labels them Tower and Pilot); sources `speech`, `typed`, `replay`; transcribers `whisper`, `apple`.
- UWB-ATCC corpus text never goes into tests or fixtures (CC BY-NC-ND). Austin text (NTSB public record) and invented text are fine.
- Match the repo's style: a module docstring citing the spec, short comments only where the code cannot say it, no em dashes in docs.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Planning amendments to the spec (2026-10-20)

1. **Whisper gate (Section 9).** The first gate, the same text as the CTranslate2 model on 18 of 20 clips, measured decoding differences, not accuracy. The gate is now: median GPU time at most 2.0 s per clip, and a word error rate against the human transcripts at most 2 points above the CTranslate2 model's. Measured while planning on 20 test-split clips: **median 1.03 s; word error rate 9.3% on the GPU vs 11.0% for CTranslate2; gate passed.** The first model load takes about 18 s, not 6 s.
2. **Audio upload (Section 6).** A clip is the raw WAV body of `POST sessions/{id}/audio`, its fields in the query string (no multipart dependency); typed and replayed text goes to `POST sessions/{id}/text` as JSON.
3. **Session log (Section 6).** `session.jsonl` is the session's event log: every event the stream sent, in order (each `transcript` event carries the line's role, time, source, transcriber, Apple's text and the transcript; each `extraction` its events, conflicts, runways and error). Token use is not logged: the parser does not return it, and the per-line cost is known from the price.
4. **Austin test (Section 9).** The live path is checked against the reference fold (`incidents.fold_window`) with the rules parser and a scripted Claude stand-in, line for line. Haiku 5.5's real Austin replies are recorded in operational step O2 for the results doc, not as test fixtures.
5. **Normalization.** Typed and scripted text is normalized like ASR text (`normalize_asr_text`: lower case, digits spelled out), so "runway 31" reads as "runway three one".
6. **Austin scenario.** Lines whose speaker is unidentified (`UNK`) are left out.
7. **Whisper loading** starts on the first `GET /api/live/health` or `POST /api/live/sessions`, whichever comes first.
8. **Replay listing (Section 6).** `GET /api/live/scenarios` lists the Austin scenario and every labelled session, and
   `GET /api/live/scenarios/{id}` returns a scenario's lines, instead of `GET sessions` and `GET sessions/{id}/replay`:
   one list for the Replay menu, whatever the source.

## Review Focus

1. Both people press their talk keys at almost the same time: two clips arrive together. Every line gets its own number in submission order and each extractor handles each line once, in order. (Task 4: `test_overlapping_talk_keys_still_number_and_handle_every_line_once`.)
2. Whisper raises instead of hanging (for example the GPU runs out of memory): the line uses Apple's text, labelled as such. (Task 4: `test_a_whisper_that_raises_falls_back_to_apple_text`.)
3. Retry is pressed for a line the Claude side has not reached yet: nothing is redone twice, and later lines still arrive once, in order. (Task 4: `test_retry_for_a_line_the_track_has_not_reached_redoes_nothing`.)
4. Undo right after a key tap too short to keep: the tap never became a line, so Undo removes the line before it. (Task 4: `test_undo_after_a_dropped_short_clip_undoes_the_line_before_it`.)
5. The helper restarted while the app kept a session id: every route answers 404 for an unknown session, so the app can start a new one instead of hanging. (Task 6: `test_bad_input_is_422_and_an_unknown_session_is_404`.)

---

### Task 1: Haiku 5.5 in the Claude parser

**Files:**
- Modify: `atcdb/parse_llm.py` (models, settings, prices, cost estimate)
- Modify: `atcdb/evaluate.py` (the evaluation's own model list)
- Modify: `scripts/record_llm_fixtures.py` (`--model`, keeping other models' replies)
- Test: `tests/test_parse_llm.py`, `tests/test_evaluate.py`, `tests/test_api.py`, `tests/test_replay.py`

**Interfaces:**
- Produces: `parse_llm.MODELS == ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")`; `parse_llm.MODEL_SETTINGS["claude-haiku-5-5"]`; `parse_llm.PRICES_PER_MTOK["claude-haiku-5-5"] == (0.10, 0.50)`; `evaluate.EVAL_MODELS`; `replay.PARSER_MODELS["llm"]` gains the model through `parse_llm.MODELS`; `record_llm_fixtures.py --model M` (repeatable).

- [ ] **Step 1: Write the failing tests**

In `tests/test_parse_llm.py`, replace:

```python
    assert (sonnet["thinking"], sonnet["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert MODELS == ("claude-haiku-4-5", "claude-sonnet-5")

```

with:

```python
    assert (sonnet["thinking"], sonnet["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert MODELS == ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")


def test_haiku_5_5_runs_like_the_sonnet_arm_without_sampling_parameters():
    # Haiku 5.5 rejects any non-default temperature, and accepts disabled thinking at low effort and a forced tool call.
    r = request("claude-haiku-5-5", TX, ROLE)
    assert r["model"] == "claude-haiku-5-5" and "extra_body" not in r and "temperature" not in r
    assert (r["thinking"], r["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert r["tool_choice"] == {"type": "tool", "name": "report_events"}

```

In `tests/test_parse_llm.py`, replace:

```python
    assert estimate_cost("claude-sonnet-5", ["x" * 400]) == pytest.approx(2 * one)   # both prices are double Haiku's

```

with:

```python
    assert estimate_cost("claude-sonnet-5", ["x" * 400]) == pytest.approx(2 * one)   # both prices are double Haiku's
    # a tenth of Haiku 4.5's prices, but its newer tokenizer counts the same text as about 30% more tokens
    assert estimate_cost("claude-haiku-5-5", ["x" * 400]) == pytest.approx(0.13 * one)

```

In `tests/test_parse_llm.py`, replace:

```python
# (case, model) -> what the recorded reply maps to: (event type, callsign, runway or handoff target).
RECORDED = {
    **{("austin_landing_clearance", m): [("ClearToLand", "fedex fourteen thirty-two heavy", "18L")] for m in MODELS},
    **{("austin_takeoff_clearance", m): [("ClearTakeoff", "southwest seven zero eight", "18L")] for m in MODELS},
    # Findings, not expectations to fix here: Haiku reads the pilot's readback as a new clearance for the heading,
```

with:

```python
# (case, model) -> what the recorded reply maps to: (event type, callsign, runway or handoff target).
# Models whose replies are recorded; claude-haiku-5-5 joins once scripts/record_llm_fixtures.py has run for it.
RECORDED_MODELS = ("claude-haiku-4-5", "claude-sonnet-5")
RECORDED = {
    **{("austin_landing_clearance", m): [("ClearToLand", "fedex fourteen thirty-two heavy", "18L")] for m in RECORDED_MODELS},
    **{("austin_takeoff_clearance", m): [("ClearTakeoff", "southwest seven zero eight", "18L")] for m in RECORDED_MODELS},
    # Findings, not expectations to fix here: Haiku reads the pilot's readback as a new clearance for the heading,
```

In `tests/test_parse_llm.py`, replace:

```python
    ("austin_takeoff_readback", "claude-sonnet-5"): [("ReadbackObserved", "", None)],
    **{("austin_handoff", m): [("Handoff", "american nineteen thirteen", "departure")] for m in MODELS},
    **{("cross_then_hold_short", m): [("ClearToCross", "lufthansa four five six", "24"),
                                      ("HoldShort", "lufthansa four five six", "31")] for m in MODELS},
    **{("window_snaps_to_the_active_runway", m): [("ClearToLand", "csa one two three", "31")] for m in MODELS},
}
```

with:

```python
    ("austin_takeoff_readback", "claude-sonnet-5"): [("ReadbackObserved", "", None)],
    **{("austin_handoff", m): [("Handoff", "american nineteen thirteen", "departure")] for m in RECORDED_MODELS},
    **{("cross_then_hold_short", m): [("ClearToCross", "lufthansa four five six", "24"),
                                      ("HoldShort", "lufthansa four five six", "31")] for m in RECORDED_MODELS},
    **{("window_snaps_to_the_active_runway", m): [("ClearToLand", "csa one two three", "31")] for m in RECORDED_MODELS},
}
```

In `tests/test_evaluate.py`, replace:

```python
    assert len(ARMS) == 18 and len(set(ARMS)) == 18
    assert {a.parser for a in ARMS} == {"rule", "llm"} and {a.transcript for a in ARMS} == {"gold", "asr"}
```

with:

```python
    assert len(ARMS) == 18 and len(set(ARMS)) == 18
    # a model added to the parser (claude-haiku-5-5, for the live app) does not add paid arms by itself
    assert {a.model for a in ARMS} == {"rules", "claude-haiku-4-5", "claude-sonnet-5"}
    assert {a.parser for a in ARMS} == {"rule", "llm"} and {a.transcript for a in ARMS} == {"gold", "asr"}
```

In `tests/test_api.py`, replace:

```python
                    {"name": "llm", "model": "claude-sonnet-5", **unavailable},
                    {"name": "rule", "model": "rules", "model_version": VERSION, "available": True, "reason": None}],
```

with:

```python
                    {"name": "llm", "model": "claude-sonnet-5", **unavailable},
                    {"name": "llm", "model": "claude-haiku-5-5", **unavailable},
                    {"name": "rule", "model": "rules", "model_version": VERSION, "available": True, "reason": None}],
```

In `tests/test_replay.py`, replace:

```python
def test_the_registry_knows_both_parsers_and_their_models():
    assert PARSER_MODELS == {"rule": ["rules"], "llm": ["claude-haiku-4-5", "claude-sonnet-5"]}
    assert PARSER_VERSIONS == {"rule": VERSION, "llm": "p1"}
```

with:

```python
def test_the_registry_knows_both_parsers_and_their_models():
    assert PARSER_MODELS == {"rule": ["rules"], "llm": ["claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5"]}
    assert PARSER_VERSIONS == {"rule": VERSION, "llm": "p1"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_parse_llm.py tests/test_evaluate.py tests/test_api.py tests/test_replay.py`
Expected: FAIL: `test_request_settings_per_model`, `test_haiku_5_5_runs_like_the_sonnet_arm_without_sampling_parameters` and `test_estimate_cost_scales_with_the_calls_and_the_price` (KeyError `claude-haiku-5-5`), `test_capabilities`, `test_the_registry_knows_both_parsers_and_their_models`.

- [ ] **Step 3: Implement**

In `atcdb/parse_llm.py`, replace:

```python
VERSION = "p1"
MODELS = ("claude-haiku-4-5", "claude-sonnet-5")   # the cheap and the strong arm (spec addendum A.4)

# Both models do one-shot extraction with thinking off. anthropic 1.x has no `temperature` parameter, so Haiku's goes in
# extra_body; Sonnet 5 rejects temperature altogether and runs with thinking disabled at low effort instead.
MODEL_SETTINGS: dict[str, dict[str, Any]] = {
```

with:

```python
VERSION = "p1"
# The cheap and the strong evaluation arm (spec addendum A.4), then the live demo app's model (live demo spec, Section 8).
MODELS = ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")

# Every model does one-shot extraction with thinking off. anthropic 1.x has no `temperature` parameter, so Haiku 4.5's
# goes in extra_body; Sonnet 5 and Haiku 5.5 reject a non-default temperature and run with thinking disabled at low
# effort instead.
MODEL_SETTINGS: dict[str, dict[str, Any]] = {
```

In `atcdb/parse_llm.py`, replace:

```python
    "claude-sonnet-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
}
```

with:

```python
    "claude-sonnet-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
    "claude-haiku-5-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
}
```

In `atcdb/parse_llm.py`, replace:

```python

# For `parse_events.py --dry-run` only. USD per million tokens, (input, output), as listed 2026-06.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5": (2.00, 10.00)}
_TOOL_USE_OVERHEAD_TOKENS = 350   # the system prompt the API adds when tools are present (rough)
```

with:

```python

# For `parse_events.py --dry-run` only. USD per million tokens, (input, output), as listed 2026-06 (Haiku 5.5: 2026-10,
# prompts up to 100K tokens).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5": (2.00, 10.00),
                                                   "claude-haiku-5-5": (0.10, 0.50)}
# Tokens per token of the older tokenizers for the same text: Haiku 5.5's newer tokenizer counts about 30% more.
_TOKENIZER_FACTOR: dict[str, float] = {"claude-haiku-5-5": 1.3}
_TOOL_USE_OVERHEAD_TOKENS = 350   # the system prompt the API adds when tools are present (rough)
```

In `atcdb/parse_llm.py`, replace:

```python
    price_in, price_out = PRICES_PER_MTOK[model]
    return (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6

```

with:

```python
    price_in, price_out = PRICES_PER_MTOK[model]
    return _TOKENIZER_FACTOR.get(model, 1.0) * (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6

```

In `atcdb/evaluate.py`, replace:

```python

ARMS: tuple[Arm, ...] = tuple(Arm(p, m, c, t) for p, models in (("rule", ("rules",)), ("llm", parse_llm.MODELS))
                              for m in models for c in CONTEXT_MODES for t in TRANSCRIPTS)
```

with:

```python

# The evaluation's Claude models, named here so a model added to the parser (the live app's claude-haiku-5-5) does not
# add paid arms by itself; moving the evaluation to another model is its own decision.
EVAL_MODELS = ("claude-haiku-4-5", "claude-sonnet-5")
ARMS: tuple[Arm, ...] = tuple(Arm(p, m, c, t) for p, models in (("rule", ("rules",)), ("llm", EVAL_MODELS))
                              for m in models for c in CONTEXT_MODES for t in TRANSCRIPTS)
```

In `scripts/record_llm_fixtures.py`, replace:

```python
Usage:
    ANTHROPIC_API_KEY=... python scripts/record_llm_fixtures.py

Sends each case below to every model in parse_llm.MODELS with exactly the request the parser makes, and stores each
reply's stop reason and content blocks. Re-run it whenever parse_llm.VERSION is bumped, then update the expectations in
tests/test_parse_llm.py. The texts are NTSB public record (Austin, DCA23FA149) or invented: UWB-ATCC corpus text is
```

with:

```python
Usage:
    ANTHROPIC_API_KEY=... python scripts/record_llm_fixtures.py [--model claude-haiku-5-5]

Sends each case below to every model in parse_llm.MODELS (or only the `--model` ones, repeatable) with exactly the
request the parser makes, and stores each reply's stop reason and content blocks. With `--model`, the other models'
recorded replies are kept as they are. Re-run it whenever parse_llm.VERSION is bumped, then update the expectations in
tests/test_parse_llm.py. The texts are NTSB public record (Austin, DCA23FA149) or invented: UWB-ATCC corpus text is
```

In `scripts/record_llm_fixtures.py`, replace:

```python
"""
import json
```

with:

```python
"""
import argparse
import json
```

In `scripts/record_llm_fixtures.py`, replace:

```python
def main() -> None:
    client = anthropic.Anthropic()
```

with:

```python
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", choices=MODELS)
    models = ap.parse_args().model or list(MODELS)
    kept = [r for r in json.loads(OUT.read_text()) if r["model"] not in models] if OUT.exists() else []
    client = anthropic.Anthropic()
```

In `scripts/record_llm_fixtures.py`, replace:

```python
        tx = Transmission(id=0, transcript_id=0, text=text, role=role, start_s=0.0)
        for model in MODELS:
            reply = client.messages.create(**request(model, tx, ctx))
```

with:

```python
        tx = Transmission(id=0, transcript_id=0, text=text, role=role, start_s=0.0)
        records += [r for r in kept if r["case"] == name]
        for model in models:
            reply = client.messages.create(**request(model, tx, ctx))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q`
Expected: no failures. `python scripts/record_llm_fixtures.py --help` lists `--model {claude-haiku-4-5,claude-sonnet-5,claude-haiku-5-5}`. Do not run the recorder: it calls the API (operational step O2).

- [ ] **Step 5: Commit**

```bash
git add atcdb/parse_llm.py atcdb/evaluate.py scripts/record_llm_fixtures.py tests/test_parse_llm.py tests/test_evaluate.py tests/test_api.py tests/test_replay.py
git commit -m "feat: Haiku 5.5 in the Claude parser for the live app, outside the evaluation's arms

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Whisper on the GPU

**Files:**
- Modify: `atcdb/asr.py` (append the Hugging Face transcriber)
- Create: `scripts/bench_whisper.py` (the week-1 gate)
- Modify: `requirements.txt` (pin `torch` and `transformers`, already installed)
- Test: `tests/test_asr.py`

**Interfaces:**
- Produces: `asr.HF_WHISPER_REPO`; `asr.load_hf_whisper(model_dir, device="mps") -> (processor, model)`; `asr.hf_whisper_transcriber(processor, model, device="mps", num_beams=1) -> Transcriber`, where a `Transcriber` is `Callable[[Path], dict]` returning `{"text", "avg_logprob", "no_speech_prob", "words"}` like the faster-whisper one.

- [ ] **Step 1: Write the failing tests**

In `tests/test_asr.py`, replace:

```python
from atcdb.asr import normalize_asr_text, run_asr
from atcdb.loader import load_enriched_csv
```

with:

```python
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from atcdb.asr import hf_whisper_transcriber, normalize_asr_text, run_asr
from atcdb.loader import load_enriched_csv
```

In `tests/test_asr.py`, replace:

```python
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="train", recording_ids=[]) == 0
```

with:

```python
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="train", recording_ids=[]) == 0


# --- Whisper on the GPU (live demo spec, Section 5) --------------------------------------------------------------------

class _Features:
    def __init__(self, n):
        self.n, self.moved = n, None

    def to(self, device, dtype=None):
        self.moved = (device, dtype)
        return self


class FakeProcessor:
    """Stands in for WhisperProcessor: records the audio it was given and decodes token ids to a fixed text."""

    def __init__(self, text):
        self.text, self.audio = text, None

    def __call__(self, audio, sampling_rate, return_tensors):
        assert (sampling_rate, return_tensors) == (16000, "pt")
        self.audio = audio
        return SimpleNamespace(input_features=_Features(len(audio)))

    def batch_decode(self, ids, skip_special_tokens):
        assert skip_special_tokens
        return [f" {self.text} "]


class FakeModel:
    dtype = "float16"

    def __init__(self):
        self.calls = []

    def generate(self, features, **kwargs):
        self.calls.append((features, kwargs))
        return [[1, 2, 3]]


def test_the_gpu_transcriber_resamples_to_16_khz_and_returns_the_transcriber_shape(tmp_path):
    clip = tmp_path / "c.wav"
    sf.write(clip, np.zeros(8000, dtype=np.float32), 8000)   # 1 s at 8 kHz, as the jacktol clips are
    processor, model = FakeProcessor("CSA 123, runway 31, cleared to land."), FakeModel()
    out = hf_whisper_transcriber(processor, model, device="mps")(clip)
    assert len(processor.audio) == 16000 and processor.audio.dtype == np.float32
    features, kwargs = model.calls[0]
    assert features.moved == ("mps", "float16")
    assert kwargs == {"num_beams": 1}   # no language argument: an English-only model rejects it
    assert out == {"text": "CSA 123, runway 31, cleared to land.", "avg_logprob": None, "no_speech_prob": None, "words": []}
    assert normalize_asr_text(out["text"]) == "csa one two three runway three one cleared to land"


def test_the_gpu_transcriber_mixes_stereo_down_to_mono(tmp_path):
    clip = tmp_path / "s.wav"
    sf.write(clip, np.zeros((16000, 2), dtype=np.float32), 16000)
    processor = FakeProcessor("x")
    hf_whisper_transcriber(processor, FakeModel())(clip)
    assert processor.audio.shape == (16000,)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_asr.py`
Expected: FAIL at collection: `ImportError: cannot import name 'hf_whisper_transcriber'`.

- [ ] **Step 3: Implement**

In `atcdb/asr.py`, replace:

```python
    return transcribe
```

with:

```python
    return transcribe


# --- Whisper on the GPU (live demo spec, Section 5) --------------------------------------------------------------------
# faster-whisper (CTranslate2) has no Apple GPU backend: on this Mac it takes 7 to 10 s for a 2.8 s clip. The live app
# runs the same fine-tuned model from its Hugging Face weights with transformers on PyTorch's `mps` device instead.

HF_WHISPER_REPO = "jacktol/whisper-medium.en-fine-tuned-for-ATC"   # the weights behind the repo's CTranslate2 model
WHISPER_RATE = 16000


def load_hf_whisper(model_dir: Path | str, device: str = "mps"):
    """(processor, model) for the Hugging Face Whisper weights in `model_dir`, in half precision on `device`."""
    import torch  # imported lazily: heavy
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(str(model_dir))
    model = WhisperForConditionalGeneration.from_pretrained(str(model_dir), dtype=torch.float16).to(device).eval()
    return processor, model


def _mono_16k(audio, rate: int):
    """Float32 mono samples at 16 kHz: channels averaged, other rates resampled by linear interpolation."""
    import numpy as np

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != WHISPER_RATE and len(audio):
        n = int(round(len(audio) * WHISPER_RATE / rate))
        audio = np.interp(np.arange(n) * (rate / WHISPER_RATE), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def hf_whisper_transcriber(processor, model, device: str = "mps", num_beams: int = 1) -> Transcriber:
    """Transcriber over a loaded Hugging Face Whisper model, with the same result keys as the faster-whisper one (the
    scores it cannot give are None). No `language` argument: an English-only checkpoint rejects one. The length cap is
    the checkpoint's own (`max_length` 448 tokens), far above a transmission."""
    import soundfile as sf

    def transcribe(clip_path: Path) -> dict:
        import torch

        samples, rate = sf.read(str(clip_path), dtype="float32")
        features = processor(_mono_16k(samples, rate), sampling_rate=WHISPER_RATE, return_tensors="pt").input_features
        with torch.inference_mode():
            ids = model.generate(features.to(device, dtype=model.dtype), num_beams=num_beams)
        text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        return {"text": text, "avg_logprob": None, "no_speech_prob": None, "words": []}

    return transcribe
```

Create `scripts/bench_whisper.py`:

```python
#!/usr/bin/env python3
"""Week-1 gate for the live demo app (spec 2026-10-20-live-demo-app-design.md, Section 9): is Whisper on the GPU fast
enough, and does it read clips at least as accurately as the evaluation's CTranslate2 model?

Usage:
    python scripts/bench_whisper.py [--clips 20] [--model-dir data/models/whisper-medium.en-atc-hf]

Downloads the Hugging Face weights into --model-dir if they are missing (about 1.5 GB, free), then transcribes the first
--clips test-split clips of 2 to 8 s with both models, after one warm-up call. Prints each clip's GPU time and both
texts beside the human transcript, then the gate: median GPU time at most 2.0 s, and a word error rate against the human
transcripts at most 2 points above the CTranslate2 model's. (Planning, 2026-10-20: the spec's first gate, the same text
as the CTranslate2 model on 18 of 20 clips, measured decoding differences rather than accuracy: on the clips where the
two disagreed, the GPU model was as often right as wrong.)
"""
import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jiwer  # noqa: E402
import soundfile as sf  # noqa: E402

from atcdb.asr import (HF_WHISPER_REPO, hf_whisper_transcriber, load_hf_whisper, make_faster_whisper_transcriber,  # noqa: E402
                       normalize_asr_text)

MAX_MEDIAN_S = 2.0
MAX_WER_GAP = 0.02   # GPU word error rate at most 2 points above the CTranslate2 model's


def test_clips(clips_dir: Path, n: int) -> list[Path]:
    """The first `n` clips, in name order, lasting 2 to 8 s (a typical transmission)."""
    out = []
    for p in sorted(clips_dir.glob("*.wav")):
        if 2.0 <= sf.info(str(p)).duration <= 8.0:
            out.append(p)
            if len(out) == n:
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=int, default=20)
    ap.add_argument("--model-dir", type=Path, default=ROOT / "data/models/whisper-medium.en-atc-hf")
    ap.add_argument("--ct2-dir", type=Path, default=ROOT / "data/models/whisper-medium.en-atc-ct2")
    ap.add_argument("--clips-dir", type=Path, default=ROOT / "data/jacktol-atc/clips/test")
    ap.add_argument("--transcripts", type=Path, default=ROOT / "data/jacktol-atc/transcripts.csv")
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    if not (args.model_dir / "model.safetensors").exists():
        from huggingface_hub import snapshot_download
        print(f"downloading {HF_WHISPER_REPO} into {args.model_dir} (about 1.5 GB)", flush=True)
        snapshot_download(HF_WHISPER_REPO, local_dir=str(args.model_dir))
    clips = test_clips(args.clips_dir, args.clips)
    if not clips:
        sys.exit(f"no 2 to 8 s clips in {args.clips_dir}")
    with args.transcripts.open(newline="") as fh:
        human = {Path(r["path"]).name: normalize_asr_text(r["text"]) for r in csv.DictReader(fh)}

    t0 = time.perf_counter()
    gpu = hf_whisper_transcriber(*load_hf_whisper(args.model_dir, args.device), device=args.device)
    print(f"GPU model loaded in {time.perf_counter() - t0:.1f} s", flush=True)
    cpu = make_faster_whisper_transcriber(args.ct2_dir)
    gpu(clips[0])   # warm-up: the first call compiles the GPU kernels

    times, refs, gpus, cpus = [], [], [], []
    for clip in clips:
        t0 = time.perf_counter()
        g = normalize_asr_text(gpu(clip)["text"])
        times.append(time.perf_counter() - t0)
        c = normalize_asr_text(cpu(clip)["text"])
        refs.append(human[clip.name])
        gpus.append(g)
        cpus.append(c)
        print(f"{clip.name}  {sf.info(str(clip)).duration:4.1f} s audio  {times[-1]:4.2f} s GPU  "
              f"{'same' if g == c else 'differs'}\n    human: {refs[-1]}\n    gpu:   {g}\n    cpu:   {c}", flush=True)
    median = statistics.median(times)
    wer_gpu, wer_cpu = jiwer.wer(refs, gpus), jiwer.wer(refs, cpus)
    ok = median <= MAX_MEDIAN_S and wer_gpu <= wer_cpu + MAX_WER_GAP
    print(f"\nmedian GPU time {median:.2f} s (gate {MAX_MEDIAN_S} s); word error rate GPU {wer_gpu:.1%}, "
          f"CTranslate2 {wer_cpu:.1%} (gate: GPU at most {MAX_WER_GAP:.0%} above); same text on "
          f"{sum(g == c for g, c in zip(gpus, cpus))}/{len(clips)}; gate {'PASSED' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
```

In `requirements.txt`, replace:

```text
soundfile==0.14.0
uvicorn==0.53.0
```

with:

```text
soundfile==0.14.0
torch==2.13.0
transformers==5.16.1
uvicorn==0.53.0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q`
Expected: no failures. Do not run `scripts/bench_whisper.py` in this task (operational step O1; it downloads 1.5 GB).

- [ ] **Step 5: Commit**

```bash
git add atcdb/asr.py scripts/bench_whisper.py requirements.txt tests/test_asr.py
git commit -m "feat: ATC Whisper on the Mac GPU through transformers, with its speed and accuracy gate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Tracks, one extractor's view of a live session

**Files:**
- Create: `atcdb/live.py` (lines, track steps, `Track`, `step_payload`)
- Create: `tests/live_fakes.py` (the scripted Claude stand-in and a WAV maker, shared by the live tests)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: `replay.build_context(mode, tx, history, state)`, `engine.apply(state, event)`, `serialize.event_dict / conflict_dict / board_dict`.
- Produces: `Line(seq, role, t, text, source, transcriber, preview_text="")` with `.transmission()`; `TrackStep(seq, events, conflicts, state, error=None)`; `Track(name, parse)` with `.state`, `.compute(line, history) -> TrackStep` (no change to the track), `.push(step)`, `.apply(line, history)`, `.undo(seq) -> bool`, `.truncate(seq)`; `step_payload(track_name, step) -> dict` with keys `seq, extractor, events, conflicts, runways, error` (NOOP events left out). Test helpers: `live_fakes.Scripted(delay=0.0, fail_texts=(), fail_times=1)`, `live_fakes.wav(seconds, rate=16000) -> bytes`.

- [ ] **Step 1: Write the failing tests**

Create `tests/live_fakes.py`:

```python
"""Stand-ins shared by the live demo's tests (tests/test_live.py, tests/test_live_api.py)."""
import io
import time

import numpy as np
import soundfile as sf

from atcdb.engine import ClearTakeoff, ClearToLand


def wav(seconds, rate=16000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * rate), dtype=np.float32), rate, format="WAV")
    return buf.getvalue()


class Scripted:
    """A stand-in for the Claude parser: events chosen by the transmission's text; can be slow, fail, or record the
    context it was given."""

    def __init__(self, delay=0.0, fail_texts=(), fail_times=1):
        self.delay, self.fail = delay, {t: fail_times for t in fail_texts}
        self.contexts, self.calls = [], []

    def __call__(self, tx, ctx):
        self.calls.append(tx.text)
        self.contexts.append(ctx)
        time.sleep(self.delay)
        if self.fail.get(tx.text, 0) > 0:
            self.fail[tx.text] -= 1
            raise RuntimeError("Claude unavailable: no internet connection")
        if "cleared to land" in tx.text:
            rwy = "18L" if "one eight left" in tx.text else "31"
            return [ClearToLand(callsign=" ".join(tx.text.split()[:4]), runway=rwy, t=tx.start_s, text=tx.text)]
        if "cleared for takeoff" in tx.text:
            rwy = "18L" if "one eight left" in tx.text else "31"
            return [ClearTakeoff(callsign=" ".join(tx.text.split()[:4]), runway=rwy, t=tx.start_s, text=tx.text)]
        return []
```

Create `tests/test_live.py`:

```python
from live_fakes import Scripted

from atcdb import parse_rules
from atcdb.engine import State
from atcdb.live import Line, Track, step_payload

LAND_31 = "csa one two three runway three one cleared to land"
TAKEOFF_31 = "lufthansa four five six runway three one cleared for takeoff"
# a landing clearance without the word "runway": the rules parser drops it (spec addendum A.2), Claude reads it
BARE_LAND = "fedex one two three one eight left cleared to land"
TAKEOFF_18L = "southwest seven zero eight runway one eight left cleared for takeoff"


def line(seq, text, role="controller", t=None):
    return Line(seq, role, float(seq * 10 if t is None else t), text, "typed", "none")


# --- Track ----------------------------------------------------------------------------------------------------------

def test_a_track_folds_lines_through_its_own_engine():
    track = Track("rules", parse_rules.parse)
    first = track.apply(line(0, LAND_31), [])
    assert [type(e).__name__ for e in first.events] == ["ClearToLand"] and first.conflicts == ()
    second = track.apply(line(1, TAKEOFF_31), [line(0, LAND_31)])
    assert [(c.type, c.severity, c.runway) for c in second.conflicts] == [("RUNWAY", "alert", "31")]
    assert {r.kind for r in track.state.runways["31"]} == {"LAND", "TAKEOFF"}


def test_a_track_gives_the_parser_window_context():
    parser = Scripted()
    track = Track("claude", parser)
    track.apply(line(0, LAND_31), [])
    track.apply(line(1, "lufthansa four five six hold position", role="pilot"), [line(0, LAND_31)])
    ctx = parser.contexts[1]
    assert ctx.mode == "window" and ctx.role == "pilot"
    assert ctx.history == (("controller", LAND_31),) and ctx.active_runways == ("31",)


def test_a_parser_failure_is_an_error_step_that_keeps_the_state():
    track = Track("claude", Scripted(fail_texts=[TAKEOFF_31]))
    track.apply(line(0, LAND_31), [])
    before = track.state
    step = track.apply(line(1, TAKEOFF_31), [line(0, LAND_31)])
    assert step.events == () and step.conflicts == () and step.state is before
    assert step.error == "RuntimeError: Claude unavailable: no internet connection"


def test_undo_drops_only_the_last_step_and_truncate_drops_from_a_line_on():
    track = Track("rules", parse_rules.parse)
    for k, text in enumerate([LAND_31, TAKEOFF_31, LAND_31]):
        track.apply(line(k, text), [])
    assert not track.undo(1) and track.undo(2) and [s.seq for s in track.steps] == [0, 1]
    track.truncate(1)
    assert [s.seq for s in track.steps] == [0]
    assert Track("x", parse_rules.parse).state == State()


def test_step_payload_uses_the_api_shapes_and_leaves_out_noop():
    nothing = Track("rules", parse_rules.parse).apply(line(0, "csa one two three good morning"), [])
    assert [type(e).__name__ for e in nothing.events] == ["NoOp"] and step_payload("rules", nothing)["events"] == []
    step = Track("rules", parse_rules.parse).apply(line(0, LAND_31), [])
    assert step_payload("rules", step) == {
        "seq": 0, "extractor": "rules",
        "events": [{"kind": "LAND", "callsign": "csa one two three", "runway": "31", "to": None}],
        "conflicts": [], "runways": {"31": [{"callsign": "csa one two three", "kind": "LAND"}]}, "error": None}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'atcdb.live'`.

- [ ] **Step 3: Implement**

Create `atcdb/live.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live.py`
Expected: 5 passed. Then `env -u ANTHROPIC_API_KEY python -m pytest -q`: no failures.

- [ ] **Step 5: Commit**

```bash
git add atcdb/live.py tests/live_fakes.py tests/test_live.py
git commit -m "feat: live tracks, each extractor folding live lines through its own engine

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Live sessions: ordering, transcription, undo and retry

**Files:**
- Modify: `atcdb/live.py` (imports and constants; append `clip_seconds`, `Transcription`, `LiveSession`)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 3's `Line`, `Track`, `step_payload`; `asr.normalize_asr_text`; a `Transcriber` (Task 2's shape).
- Produces: constants `ROLES`, `SOURCES`, `TRANSCRIBERS`, `MIN_CLIP_S`, `WHISPER_TIMEOUT_S`; `clip_seconds(wav: bytes) -> float` (ValueError if unreadable); `Transcription(whisper: Callable[[], Transcriber | None], timeout_s=8.0)`, called as `(clip, preview_text, prefer) -> (text, "whisper" | "apple")`; `LiveSession(session_id, tracks, transcription, folder)` with `submit_text(role, t, text, source="typed") -> int`, `submit_audio(role, t, wav, preview_text="", prefer="whisper", source="speech") -> int | None`, `undo() -> int | None`, `retry(extractor, seq)`, `events_after(after=-1, timeout=None) -> list[dict]`, `wait_for(predicate, timeout=5.0) -> list[dict]`, `close()`. Events are dicts with `id` (0, 1, 2, ...) and `type` in `transcript`, `extraction`, `undone`, `dropped`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_live.py`, replace:

```python
from live_fakes import Scripted

```

with:

```python
import json
import threading
import time

import pytest
from live_fakes import Scripted, wav

```

In `tests/test_live.py`, replace:

```python
from atcdb.engine import State
from atcdb.live import Line, Track, step_payload

```

with:

```python
from atcdb.engine import State
from atcdb.live import MIN_CLIP_S, Line, LiveSession, Track, Transcription, clip_seconds, step_payload

```

In `tests/test_live.py`, replace:

```python
    return Line(seq, role, float(seq * 10 if t is None else t), text, "typed", "none")

```

with:

```python
    return Line(seq, role, float(seq * 10 if t is None else t), text, "typed", "none")


def session(tmp_path, claude=None, whisper=None, timeout_s=8.0):
    tracks = {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", claude or Scripted())}
    return LiveSession("s1", tracks, Transcription(lambda: whisper, timeout_s=timeout_s), tmp_path / "s1")


def extractions(events, extractor):
    return [e for e in events if e["type"] == "extraction" and e["extractor"] == extractor]

```

In `tests/test_live.py`, replace:

```python
        "conflicts": [], "runways": {"31": [{"callsign": "csa one two three", "kind": "LAND"}]}, "error": None}
```

with:

```python
        "conflicts": [], "runways": {"31": [{"callsign": "csa one two three", "kind": "LAND"}]}, "error": None}


# --- LiveSession: typed lines ------------------------------------------------------------------------------------------

def test_typed_lines_are_normalized_then_read_by_both_extractors(tmp_path):
    s = session(tmp_path)
    assert s.submit_text("controller", 0.0, "CSA 123 runway 31 cleared to land") == 0
    events = s.wait_for(lambda ev: len([e for e in ev if e["type"] == "extraction"]) == 2)
    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript == {"id": 0, "type": "transcript", "seq": 0, "role": "controller", "t": 0.0, "text": LAND_31,
                          "source": "typed", "transcriber": "none", "preview_text": "", "error": None}
    assert {e["extractor"] for e in events if e["type"] == "extraction"} == {"rules", "claude"}


def test_each_extractor_keeps_its_own_engine_so_they_can_disagree(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, BARE_LAND)
    s.submit_text("controller", 284.0, TAKEOFF_18L)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 2 and len(extractions(ev, "claude")) == 2)
    rules, claude = extractions(events, "rules"), extractions(events, "claude")
    assert rules[0]["events"] == [] and rules[1]["conflicts"] == []   # rules never reserved 18L
    assert [(c["type"], c["severity"], c["runway"]) for c in claude[1]["conflicts"]] == [("RUNWAY", "alert", "18L")]


def test_rules_never_wait_for_a_slow_claude_and_claude_keeps_line_order(tmp_path):
    s = session(tmp_path, claude=Scripted(delay=0.3))
    for k, text in enumerate([LAND_31, TAKEOFF_31, LAND_31]):
        s.submit_text("controller", k * 10.0, text)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 3, timeout=0.6)
    assert len(extractions(events, "claude")) < 3   # all three rules results arrived while Claude still worked
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 3)
    assert [e["seq"] for e in extractions(events, "claude")] == [0, 1, 2]


def test_a_claude_failure_leaves_rules_alone_and_retry_redoes_it_and_every_later_line(tmp_path):
    claude = Scripted(fail_texts=[LAND_31])
    s = session(tmp_path, claude=claude)
    s.submit_text("controller", 0.0, LAND_31)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 2 and len(extractions(ev, "rules")) == 2)
    failed, after = extractions(events, "claude")
    assert failed["error"].endswith("no internet connection") and failed["events"] == []
    assert after["conflicts"] == []   # parsed against the state without the failed line
    assert len(extractions(events, "rules")[1]["conflicts"]) == 1
    s.retry("claude", 0)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 4)
    redo = extractions(events, "claude")[2:]
    assert [e["seq"] for e in redo] == [0, 1] and redo[0]["error"] is None
    assert [c["type"] for c in redo[1]["conflicts"]] == ["RUNWAY"]
    assert [s.seq for s in s.tracks["claude"].steps] == [0, 1]
    with pytest.raises(ValueError, match="unknown extractor"):
        s.retry("sonnet", 0)


def test_undo_removes_the_last_line_from_both_engines(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    s.wait_for(lambda ev: len([e for e in ev if e["type"] == "extraction"]) == 4)
    assert s.undo() == 1
    assert [st.seq for st in s.tracks["rules"].steps] == [0] and [st.seq for st in s.tracks["claude"].steps] == [0]
    s.submit_text("controller", 20.0, LAND_31)   # line 2 sees line 0 only
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 3)
    assert extractions(events, "rules")[2]["conflicts"] == []   # LAND after LAND is lawful; the takeoff is gone
    assert any(e["type"] == "undone" and e["seq"] == 1 for e in events)
    assert s.undo() == 2 and s.undo() == 0 and s.undo() is None


def test_undo_while_claude_is_still_parsing_discards_its_late_result(tmp_path):
    s = session(tmp_path, claude=Scripted(delay=0.3))
    s.submit_text("controller", 0.0, LAND_31)
    s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    assert s.undo() == 0
    time.sleep(0.5)
    assert extractions(s.events_after(), "claude") == [] and s.tracks["claude"].steps == []


def test_bad_roles_and_sources_are_refused(tmp_path):
    s = session(tmp_path)
    with pytest.raises(ValueError, match="unknown role"):
        s.submit_text("tower", 0.0, LAND_31)
    with pytest.raises(ValueError, match="unknown source"):
        s.submit_text("pilot", 0.0, LAND_31, source="radio")


# --- LiveSession: audio ------------------------------------------------------------------------------------------------

def test_a_clip_is_transcribed_by_whisper_and_saved(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "CSA 123, runway 31, cleared to land."})
    seq = s.submit_audio("controller", 3.0, wav(1.0), preview_text="csa one two three runway three one")
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    transcript = next(e for e in events if e["type"] == "transcript")
    assert (transcript["text"], transcript["transcriber"], transcript["source"]) == (LAND_31, "whisper", "speech")
    assert clip_seconds((tmp_path / "s1" / f"clip_{seq}.wav").read_bytes()) == pytest.approx(1.0)


def test_a_clip_shorter_than_half_a_second_is_dropped(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "thank you"})
    assert s.submit_audio("pilot", 1.0, wav(MIN_CLIP_S - 0.2)) is None
    events = s.wait_for(lambda ev: any(e["type"] == "dropped" for e in ev))
    assert events[0]["reason"] == "Too short" and not list((tmp_path / "s1").glob("clip_*.wav"))
    with pytest.raises(ValueError, match="not a readable WAV"):
        s.submit_audio("pilot", 1.0, b"not audio")


def test_a_slow_whisper_falls_back_to_apple_text_and_later_lines_do_not_queue_behind_it(tmp_path):
    release = threading.Event()

    def stuck(clip):
        release.wait(5)
        return {"text": "too late"}

    s = session(tmp_path, whisper=stuck, timeout_s=0.2)
    s.submit_audio("controller", 0.0, wav(1.0), preview_text="CSA 123 runway 31 cleared to land")
    s.submit_audio("controller", 5.0, wav(1.0), preview_text="Lufthansa 456 runway 31 cleared for takeoff")
    events = s.wait_for(lambda ev: len([e for e in ev if e["type"] == "transcript"]) == 2, timeout=1.0)
    release.set()
    transcripts = [e for e in events if e["type"] == "transcript"]
    assert [(e["text"], e["transcriber"]) for e in transcripts] == [(LAND_31, "apple"), (TAKEOFF_31, "apple")]


def test_apple_text_is_used_when_asked_for_or_when_whisper_is_not_ready(tmp_path):
    preview = "CSA 123 runway 31 cleared to land"
    asked = session(tmp_path / "a", whisper=lambda clip: {"text": "unused"})
    asked.submit_audio("controller", 0.0, wav(1.0), preview_text=preview, prefer="apple")
    not_ready = session(tmp_path / "b", whisper=None)
    not_ready.submit_audio("controller", 0.0, wav(1.0), preview_text=preview)
    for s in (asked, not_ready):
        t = next(e for e in s.wait_for(lambda ev: any(e["type"] == "transcript" for e in ev)) if e["type"] == "transcript")
        assert (t["text"], t["transcriber"]) == (LAND_31, "apple")
    with pytest.raises(ValueError, match="unknown transcriber"):
        asked.submit_audio("controller", 0.0, wav(1.0), prefer="siri")


def test_a_clip_with_no_words_gets_an_error_and_no_extraction(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "  "})
    s.submit_audio("pilot", 0.0, wav(1.0))
    s.submit_text("controller", 5.0, LAND_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    first = next(e for e in events if e["type"] == "transcript")
    assert first["error"] == "No speech recognized" and extractions(events, "rules")[0]["seq"] == 1


def test_every_event_is_logged_to_the_session_folder(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.undo()
    events = s.wait_for(lambda ev: any(e["type"] == "undone" for e in ev))
    time.sleep(0.1)
    logged = [json.loads(x) for x in (tmp_path / "s1" / "session.jsonl").read_text().splitlines()]
    assert logged == s.events_after() and {e["type"] for e in events} >= {"undone"}


def test_events_after_returns_only_newer_events_and_waits_for_them(tmp_path):
    s = session(tmp_path)
    assert s.events_after(-1, timeout=0.05) == []
    s.submit_text("controller", 0.0, LAND_31)
    first = s.events_after(-1, timeout=2)
    assert first and first[0]["id"] == 0
    assert all(e["id"] > first[-1]["id"] for e in s.events_after(first[-1]["id"], timeout=0.05))


# --- review focus (plan A) -------------------------------------------------------------------------------------------

def test_overlapping_talk_keys_still_number_and_handle_every_line_once(tmp_path):
    s = session(tmp_path)
    seqs, threads = [], [threading.Thread(target=lambda k=k: seqs.append(s.submit_text("pilot", k, LAND_31)))
                         for k in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(seqs) == list(range(20))
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 20)
    assert [e["seq"] for e in extractions(events, "claude")] == list(range(20))


def test_a_whisper_that_raises_falls_back_to_apple_text(tmp_path):
    def broken(clip):
        raise RuntimeError("MPS backend out of memory")

    s = session(tmp_path, whisper=broken)
    s.submit_audio("controller", 0.0, wav(1.0), preview_text="CSA 123 runway 31 cleared to land")
    t = next(e for e in s.wait_for(lambda ev: any(e["type"] == "transcript" for e in ev)) if e["type"] == "transcript")
    assert (t["text"], t["transcriber"]) == (LAND_31, "apple")


def test_retry_for_a_line_the_track_has_not_reached_redoes_nothing(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.wait_for(lambda ev: len(extractions(ev, "claude")) == 1)
    s.retry("claude", 5)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 2)
    assert [e["seq"] for e in extractions(events, "claude")] == [0, 1]


def test_undo_after_a_dropped_short_clip_undoes_the_line_before_it(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "unused"})
    s.submit_text("controller", 0.0, LAND_31)
    assert s.submit_audio("pilot", 1.0, wav(0.1)) is None
    assert s.undo() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live.py`
Expected: FAIL at collection: `ImportError: cannot import name 'MIN_CLIP_S' from 'atcdb.live'`.

- [ ] **Step 3: Implement**

In `atcdb/live.py`, replace:

```python
"""
from dataclasses import dataclass

from atcdb.engine import Conflict, Event, NoOp, State, apply
```

with:

```python
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
```

In `atcdb/live.py`, replace:

```python
from atcdb.serialize import board_dict, conflict_dict, event_dict

```

with:

```python
from atcdb.serialize import board_dict, conflict_dict, event_dict

ROLES = ("controller", "pilot")
SOURCES = ("speech", "typed", "replay")
TRANSCRIBERS = ("whisper", "apple")
MIN_CLIP_S = 0.5          # shorter clips are dropped: Whisper invents words on near-silence
WHISPER_TIMEOUT_S = 8.0   # after this, the line uses Apple's text instead

```

In `atcdb/live.py`, replace:

```python
            "error": step.error}
```

with:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live.py` three times (the tests use threads; all three runs must pass).
Expected: 23 passed each time. Then `env -u ANTHROPIC_API_KEY python -m pytest -q`: no failures.

- [ ] **Step 5: Commit**

```bash
git add atcdb/live.py tests/test_live.py
git commit -m "feat: live sessions with ordered lines, Whisper with an Apple-text fallback, undo and retry

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The Austin scenario and the reference fold in atcdb/incidents.py

**Files:**
- Modify: `atcdb/incidents.py` (add `AUSTIN_FIXTURE`, `AUSTIN_FROM`, `austin_lines`, `fold_window`)
- Modify: `scripts/pilot_cases.py` (use them instead of its own copies)
- Test: `tests/test_incidents.py`

**Interfaces:**
- Produces: `incidents.AUSTIN_FROM == "0628:26"`; `incidents.austin_lines(start=AUSTIN_FROM) -> list[tuple[str, Transmission]]`; `incidents.fold_window(txs, parse) -> list[tuple[Transmission, list[Event], list[Conflict]]]`.

- [ ] **Step 1: Write the failing test**

In `tests/test_incidents.py`, replace:

```python
from atcdb.engine import Conflict, State, apply
from atcdb.incidents import load_ntsb_transcript
from atcdb.parsing import Transmission
```

with:

```python
from atcdb.engine import Conflict, State, apply
from atcdb.incidents import AUSTIN_FROM, austin_lines, fold_window, load_ntsb_transcript
from atcdb.parsing import Transmission
```

In `tests/test_incidents.py`, replace:

```python

@pytest.mark.skipif(not CORPUS.exists(), reason="corpus DB not present (UWB-ATCC is not redistributed)")
```

with:

```python

def test_the_austin_scenario_starts_at_spirits_departure_and_folds_like_the_rules_baseline():
    rows = austin_lines()
    assert (rows[0][0], rows[-1][0], len(rows)) == (AUSTIN_FROM, "0642:14", 32)
    folded = fold_window([tx for _, tx in rows], parse_rules.parse)
    raised = [(hhmm, c.severity) for (hhmm, _), (_, _, cs) in zip(rows, folded) for c in cs if c.type == "RUNWAY"]
    assert raised == [("0639:34", "warning")]   # as from the full transcript: late, and capped at warning


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus DB not present (UWB-ATCC is not redistributed)")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_incidents.py`
Expected: FAIL at collection: `ImportError: cannot import name 'AUSTIN_FROM' from 'atcdb.incidents'`.

- [ ] **Step 3: Implement**

In `atcdb/incidents.py`, replace:

```python
Austin (NTSB DCA23FA149) is public record and lives in tests/fixtures/austin_dca23fa149.txt, one `time|ident|text` line
per transmission. The tests pin the rules parser's result on it; scripts/pilot_cases.py replays it under each parser.
"""
```

with:

```python
Austin (NTSB DCA23FA149) is public record and lives in tests/fixtures/austin_dca23fa149.txt, one `time|ident|text` line
per transmission. The tests pin the rules parser's result on it; scripts/pilot_cases.py replays it under each parser,
and the live demo app offers it as a replay scenario (atcdb/live_hub.py). `fold_window` is the reference fold both use:
`window` context, no events cache.
"""
```

In `atcdb/incidents.py`, replace:

```python

from atcdb.parsing import Transmission

```

with:

```python

from atcdb.engine import Conflict, Event, State, apply
from atcdb.parsing import Parser, Transmission
from atcdb.replay import build_context

ROOT = Path(__file__).resolve().parents[1]
AUSTIN_FIXTURE = ROOT / "tests/fixtures/austin_dca23fa149.txt"
AUSTIN_FROM = "0628:26"   # Spirit 1145's 18R departure; every earlier 18L departure has already been sent to departure

```

In `atcdb/incidents.py`, replace:

```python
    return out
```

with:

```python
    return out


def austin_lines(start: str = AUSTIN_FROM) -> list[tuple[str, Transmission]]:
    """The Austin transcript from `start` on, as (time, transmission)."""
    rows = load_ntsb_transcript(AUSTIN_FIXTURE)
    k = next(i for i, (hhmm, _) in enumerate(rows) if hhmm == start)
    return rows[k:]


def fold_window(txs: list[Transmission], parse: Parser) -> list[tuple[Transmission, list[Event], list[Conflict]]]:
    """(transmission, events, conflicts) per transmission, folding as `replay.build_timeline` does in `window` context
    but without the events cache."""
    state, out = State(), []
    for k, tx in enumerate(txs):
        events = list(parse(tx, build_context("window", tx, txs[:k], state)))
        conflicts: list[Conflict] = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        out.append((tx, events, conflicts))
    return out
```

In `scripts/pilot_cases.py`, replace:

```python
from atcdb import parse_llm, parse_rules  # noqa: E402
from atcdb.engine import Handoff, NoOp, State, apply  # noqa: E402
from atcdb.incidents import load_ntsb_transcript  # noqa: E402
from atcdb.parsing import KINDS  # noqa: E402
```

with:

```python
from atcdb import parse_llm, parse_rules  # noqa: E402
from atcdb.engine import Handoff, NoOp, State  # noqa: E402
from atcdb.incidents import austin_lines, fold_window as fold  # noqa: E402
from atcdb.parsing import KINDS  # noqa: E402
```

In `scripts/pilot_cases.py`, replace:

```python

AUSTIN = ROOT / "tests/fixtures/austin_dca23fa149.txt"
AUSTIN_FROM = "0628:26"   # Spirit 1145's 18R departure; every earlier 18L departure has already been sent to departure
PRAGUE = 528              # Air France 198R crossing 13, then CSA 38W cleared to land 13 (spec addendum A.3.9)
```

with:

```python

PRAGUE = 528              # Air France 198R crossing 13, then CSA 38W cleared to land 13 (spec addendum A.3.9)
```

In `scripts/pilot_cases.py`, replace:

```python
def austin() -> tuple[list[str], list]:
    rows = load_ntsb_transcript(AUSTIN)
    k = next(i for i, (hhmm, _) in enumerate(rows) if hhmm == AUSTIN_FROM)
    return [hhmm for hhmm, _ in rows[k:]], [tx for _, tx in rows[k:]]


def fold(txs: list, parse) -> list[tuple]:
    """(tx, events, conflicts) per transmission, folding as build_timeline does but without the events cache."""
    state, out = State(), []
    for k, tx in enumerate(txs):
        events = parse(tx, build_context("window", tx, txs[:k], state))
        conflicts = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        out.append((tx, events, conflicts))
    return out

```

with:

```python
def austin() -> tuple[list[str], list]:
    rows = austin_lines()
    return [hhmm for hhmm, _ in rows], [tx for _, tx in rows]

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q`
Expected: no failures. Also `env -u ANTHROPIC_API_KEY python scripts/pilot_cases.py --dry-run` still prints a cost line (it reads the corpus DB; skip this check in a checkout without `data/atc.sqlite`).

- [ ] **Step 5: Commit**

```bash
git add atcdb/incidents.py scripts/pilot_cases.py tests/test_incidents.py
git commit -m "refactor: the Austin scenario and the reference window fold move into atcdb/incidents.py

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The hub and the /api/live/ routes

**Files:**
- Create: `atcdb/live_hub.py` (Whisper loader, live Claude parser, `LiveHub`, replay scenarios)
- Create: `atcdb/live_api.py` (the routes and the event stream)
- Modify: `atcdb/api.py` (mount the routes; capabilities say `live: true`)
- Modify: `README.md` (how to run the helper)
- Test: `tests/test_live_api.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: Task 4's `LiveSession`, `Track`, `Transcription`, `ROLES`; Task 2's `hf_whisper_transcriber`, `load_hf_whisper`; Task 5's `austin_lines`; `parse_llm.make_parser(model, client)`, `parse_llm.availability()`.
- Produces: `live_hub.CLAUDE_MODEL`, `AUSTIN_ID == "austin-2023"`; `WhisperLoader(load)` with `.start()`, `.get()`, `.status` in `idle | loading | ready | failed`, `.reason`; `gpu_whisper(model_dir, device="mps")`; `live_claude_parser(model=CLAUDE_MODEL) -> Parser`; `LiveHub(sessions_dir, whisper, make_tracks=default_tracks, claude_model=CLAUDE_MODEL)` with `.default(root)`, `.new_session()`, `.get(sid)`, `.health()`, `.label(sid, label)`, `.scenarios()`, `.scenario_lines(sid)`, `.clip_path(sid, seq)`; `live_api.make_router(hub) -> APIRouter`; `api.create_app(db_path, project_root, live_hub=None)`. Routes: `GET /api/live/health`; `POST /api/live/sessions`; `POST /api/live/sessions/{sid}/text` (JSON `role, t, text, source`); `POST /api/live/sessions/{sid}/audio?role&t&source&transcriber&preview_text` (raw WAV body); `POST .../undo`; `POST .../retry` (JSON `extractor, seq`); `POST .../label` (JSON `label`); `GET .../stream?after&max_events` (server-sent events, resumes from `Last-Event-ID`); `GET .../clips/{seq}`; `GET /api/live/scenarios`; `GET /api/live/scenarios/{sid}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live_api.py`:

```python
import json
import time

import pytest
from fastapi.testclient import TestClient
from live_fakes import Scripted, wav

from atcdb import parse_rules
from atcdb.api import create_app
from atcdb.asr import normalize_asr_text
from atcdb.incidents import austin_lines, fold_window
from atcdb.live import Line, Track
from atcdb.live_hub import AUSTIN_ID, LiveHub, WhisperLoader, gpu_whisper, live_claude_parser
from atcdb.parsing import Transmission
from atcdb.serialize import conflict_dict, event_dict

LAND_31 = "csa one two three runway three one cleared to land"


def make_hub(tmp_path, claude=None, whisper_text="CSA 123 runway 31 cleared to land"):
    tracks = lambda: {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", claude or Scripted())}
    return LiveHub(tmp_path / "sessions", WhisperLoader(lambda: (lambda clip: {"text": whisper_text})), tracks)


def ready(hub):
    """Start Whisper loading and wait for it, as the app does by polling /api/live/health at launch."""
    hub.whisper.start()
    for _ in range(100):
        if hub.whisper.status == "ready":
            return hub
        time.sleep(0.01)
    raise AssertionError(f"whisper is {hub.whisper.status}")


@pytest.fixture
def hub(tmp_path):
    return make_hub(tmp_path)


@pytest.fixture
def client(tmp_path, hub):
    return TestClient(create_app(tmp_path / "t.sqlite", tmp_path, live_hub=hub))


def read_stream(client, sid, n, after=-1, headers=None):
    """The first `n` events of a session's stream after `after`, parsed from the server-sent event text."""
    with client.stream("GET", f"/api/live/sessions/{sid}/stream", params={"after": after, "max_events": n},
                       headers=headers or {}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        data = json.loads(fields["data"])
        assert (int(fields["id"]), fields["event"]) == (data["id"], data["type"])
        events.append(data)
    return events


def new_session(client):
    r = client.post("/api/live/sessions")
    assert r.status_code == 200
    return r.json()["session_id"]


# --- the hub --------------------------------------------------------------------------------------------------------

def test_health_starts_loading_whisper_and_says_why_claude_cannot_run(client, hub, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert hub.whisper.status == "idle"
    body = client.get("/api/live/health").json()
    assert body["claude"] == {"model": "claude-haiku-5-5", "available": False, "reason": "ANTHROPIC_API_KEY not set"}
    assert body["extractors"] == ["rules", "claude"] and hub.whisper.status in ("loading", "ready")
    ready(hub)
    assert client.get("/api/live/health").json()["whisper"] == {"status": "ready", "reason": None}


def test_a_whisper_that_cannot_load_reports_failed_and_lines_use_apple_text(tmp_path):
    loader = WhisperLoader(gpu_whisper(tmp_path / "missing"))
    loader.start()
    for _ in range(50):
        if loader.status != "loading":
            break
        time.sleep(0.02)
    assert loader.status == "failed" and "run scripts/bench_whisper.py once" in loader.reason and loader.get() is None


def test_the_live_claude_parser_without_a_key_fails_each_line_not_the_session(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tx = Transmission(id=0, transcript_id=0, text=LAND_31, role="controller", start_s=0.0)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        live_claude_parser()(tx, None)


def test_a_new_session_closes_the_old_one_and_gets_its_own_folder(hub):
    first, second = hub.new_session(), hub.new_session()
    assert first.session_id != second.session_id and second.folder.parent == hub.sessions_dir
    assert hub.get(second.session_id) is second and hub.get("nope") is None


# --- routes ---------------------------------------------------------------------------------------------------------

def test_a_typed_line_streams_its_transcript_then_both_extractions(client):
    sid = new_session(client)
    assert client.post(f"/api/live/sessions/{sid}/text",
                       json={"role": "controller", "t": 0.0, "text": "CSA 123 runway 31 cleared to land"}).json() == {"seq": 0}
    events = read_stream(client, sid, 3)
    assert [e["type"] for e in events] == ["transcript", "extraction", "extraction"]
    assert events[0]["text"] == LAND_31 and {e["extractor"] for e in events[1:]} == {"rules", "claude"}


def test_a_clip_is_posted_as_the_raw_wav_body(client, hub):
    ready(hub)
    sid = new_session(client)
    r = client.post(f"/api/live/sessions/{sid}/audio", params={"role": "controller", "t": 2.5, "preview_text": "csa"},
                    content=wav(1.0), headers={"Content-Type": "audio/wav"})
    assert r.json() == {"seq": 0, "dropped": None}
    transcript = read_stream(client, sid, 1)[0]
    assert (transcript["text"], transcript["transcriber"], transcript["preview_text"]) == (LAND_31, "whisper", "csa")
    assert client.get(f"/api/live/sessions/{sid}/clips/0").headers["content-type"] == "audio/wav"
    short = client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 3.0}, content=wav(0.2))
    assert short.json() == {"seq": None, "dropped": "Too short"}


def test_bad_input_is_422_and_an_unknown_session_is_404(client):
    sid = new_session(client)
    assert client.post(f"/api/live/sessions/{sid}/text", json={"role": "tower", "t": 0, "text": "x"}).status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 0},
                       content=b"not audio").status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 0, "transcriber": "siri"},
                       content=wav(1.0)).status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/retry", json={"extractor": "gpt", "seq": 0}).status_code == 422
    assert client.post("/api/live/sessions/nope/text", json={"role": "pilot", "t": 0, "text": "x"}).status_code == 404
    assert client.get("/api/live/sessions/nope/stream").status_code == 404
    assert client.get(f"/api/live/sessions/{sid}/clips/9").status_code == 404


def test_undo_and_retry_over_http(tmp_path):
    hub = make_hub(tmp_path, claude=Scripted(fail_texts=[LAND_31]))
    client = TestClient(create_app(tmp_path / "t.sqlite", tmp_path, live_hub=hub))
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "controller", "t": 0, "text": LAND_31})
    failed = [e for e in read_stream(client, sid, 3) if e.get("extractor") == "claude"][0]
    assert failed["error"].endswith("no internet connection")
    assert client.post(f"/api/live/sessions/{sid}/retry", json={"extractor": "claude", "seq": 0}).json() == {"ok": True}
    redone = read_stream(client, sid, 1, after=2)[0]
    assert (redone["extractor"], redone["seq"], redone["error"]) == ("claude", 0, None)
    assert client.post(f"/api/live/sessions/{sid}/undo").json() == {"seq": 0}
    assert read_stream(client, sid, 1, after=3)[0] == {"id": 4, "type": "undone", "seq": 0}
    assert client.post(f"/api/live/sessions/{sid}/undo").json() == {"seq": None}


def test_the_stream_resumes_after_the_last_event_id(client):
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "controller", "t": 0, "text": LAND_31})
    first = read_stream(client, sid, 3)
    again = read_stream(client, sid, 1, headers={"Last-Event-ID": str(first[1]["id"])})
    assert again == [first[2]]


def test_a_saved_session_is_labelled_and_replays_its_lines_with_their_clips(client, hub):
    ready(hub)
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/audio", params={"role": "controller", "t": 1.0}, content=wav(1.0))
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "pilot", "t": 4.0, "text": "cleared to land csa one two three"})
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "pilot", "t": 6.0, "text": "say again"})
    read_stream(client, sid, 6)
    client.post(f"/api/live/sessions/{sid}/undo")
    assert client.post(f"/api/live/sessions/{sid}/label", json={"label": "Rehearsal 1"}).json() == {"ok": True}
    assert client.post("/api/live/sessions/nope/label", json={"label": "x"}).status_code == 404
    listed = client.get("/api/live/scenarios").json()
    assert listed[0]["id"] == AUSTIN_ID and listed[1] == {"id": sid, "title": "Rehearsal 1", "lines": 2, "audio": True}
    lines = client.get(f"/api/live/scenarios/{sid}").json()
    assert [(x["role"], x["t"], x["text"]) for x in lines] == [("controller", 1.0, LAND_31),
                                                              ("pilot", 4.0, "cleared to land csa one two three")]
    assert lines[0]["audio"] == f"/api/live/sessions/{sid}/clips/0" and lines[1]["audio"] is None
    assert client.get(lines[0]["audio"]).status_code == 200
    assert client.get("/api/live/scenarios/nope").status_code == 404


def test_capabilities_say_the_live_routes_exist(client):
    assert client.get("/api/capabilities").status_code in (200, 503)   # 503: no corpus DB in this test's tmp_path
    assert client.get("/api/live/scenarios").status_code == 200


# --- Austin through the live path ----------------------------------------------------------------------------------------

def test_the_austin_replay_matches_the_reference_fold_and_rules_warn_only_late(client):
    lines = client.get(f"/api/live/scenarios/{AUSTIN_ID}").json()
    assert len(lines) == len([1 for _, tx in austin_lines() if tx.role in ("controller", "pilot")])
    sid = new_session(client)
    for x in lines:
        client.post(f"/api/live/sessions/{sid}/text", json={"role": x["role"], "t": x["t"], "text": x["text"],
                                                            "source": "replay"})
    events = read_stream(client, sid, 3 * len(lines))
    reference = [Line(k, x["role"], x["t"], normalize_asr_text(x["text"]), "replay", "none").transmission()
                 for k, x in enumerate(lines)]
    for name, parse in (("rules", parse_rules.parse), ("claude", Scripted())):
        live = sorted((e for e in events if e.get("extractor") == name), key=lambda e: e["seq"])
        folded = fold_window(reference, parse)
        assert [e["events"] for e in live] == [[event_dict(ev) for ev in evs if type(ev).__name__ != "NoOp"]
                                               for _, evs, _ in folded]
        assert [e["conflicts"] for e in live] == [[conflict_dict(c) for c in cs] for _, _, cs in folded]
    rules_conflicts = [(lines[e["seq"]]["t"], c["severity"]) for e in events if e.get("extractor") == "rules"
                       for c in e["conflicts"] if c["type"] == "RUNWAY"]
    at = {tx.start_s: hhmm for hhmm, tx in austin_lines()}
    assert [(at[t], sev) for t, sev in rules_conflicts] == [("0639:34", "warning")]
```

In `tests/test_api.py`, replace:

```python
        "transcripts": {"gold": ["atco2-xml", "human"], "asr": ["whisper-test"]},
        "live": False,
    }
```

with:

```python
        "transcripts": {"gold": ["atco2-xml", "human"], "asr": ["whisper-test"]},
        "live": True,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live_api.py tests/test_api.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'atcdb.live_hub'`.

- [ ] **Step 3: Implement**

Create `atcdb/live_hub.py`:

```python
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
```

Create `atcdb/live_api.py`:

```python
"""The live demo app's routes, under /api/live/ (spec 2026-10-20-live-demo-app-design.md, Section 6).

Routing only: sessions live in atcdb/live.py, what they share in atcdb/live_hub.py. A clip is posted as the raw WAV
body with its fields in the query string, so no multipart parser is needed. Results come back on one server-sent
event stream per session; `after` (or the Last-Event-ID header) resumes it after a dropped connection.
"""
import json
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from atcdb.live import LiveSession
from atcdb.live_hub import LiveHub

HEARTBEAT_S = 15.0   # a comment line this often keeps the connection from idling out


class TextLine(BaseModel):
    role: str
    t: float
    text: str
    source: str = "typed"


class RetryRequest(BaseModel):
    extractor: str
    seq: int


class LabelRequest(BaseModel):
    label: str


def sse(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"


def make_router(hub: LiveHub) -> APIRouter:
    r = APIRouter(prefix="/api/live")

    def session(sid: str) -> LiveSession:
        s = hub.get(sid)
        if s is None:
            raise HTTPException(404, f"no live session {sid}")
        return s

    def unprocessable(call):
        try:
            return call()
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @r.get("/health")
    def health():
        hub.whisper.start()   # the app polls this at launch, so Whisper starts loading then
        return hub.health()

    @r.post("/sessions")
    def new_session():
        hub.whisper.start()
        return {"session_id": hub.new_session().session_id}

    @r.post("/sessions/{sid}/text")
    def text(sid: str, line: TextLine):
        s = session(sid)
        return {"seq": unprocessable(lambda: s.submit_text(line.role, line.t, line.text, line.source))}

    @r.post("/sessions/{sid}/audio")
    async def audio(sid: str, request: Request, role: str, t: float, source: str = "speech",
                    transcriber: str = "whisper", preview_text: str = ""):
        s = session(sid)
        wav = await request.body()
        seq = unprocessable(lambda: s.submit_audio(role, t, wav, preview_text, transcriber, source))
        return {"seq": seq, "dropped": None if seq is not None else "Too short"}

    @r.post("/sessions/{sid}/undo")
    def undo(sid: str):
        return {"seq": session(sid).undo()}

    @r.post("/sessions/{sid}/retry")
    def retry(sid: str, req: RetryRequest):
        s = session(sid)
        unprocessable(lambda: s.retry(req.extractor, req.seq))
        return {"ok": True}

    @r.post("/sessions/{sid}/label")
    def label(sid: str, req: LabelRequest):
        try:
            hub.label(sid, req.label)
        except KeyError:
            raise HTTPException(404, f"no saved session {sid}") from None
        return {"ok": True}

    @r.get("/sessions/{sid}/stream")
    def stream(sid: str, request: Request, after: int = -1, max_events: int | None = None):
        s = session(sid)
        if request.headers.get("last-event-id", "").isdigit():
            after = int(request.headers["last-event-id"])

        def events() -> Iterator[str]:
            cursor, sent = after, 0
            while max_events is None or sent < max_events:
                batch = s.events_after(cursor, timeout=HEARTBEAT_S)
                if not batch:
                    yield ": keep-alive\n\n"
                    continue
                for event in batch[: None if max_events is None else max_events - sent]:
                    yield sse(event)
                    cursor, sent = event["id"], sent + 1

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @r.get("/sessions/{sid}/clips/{seq}")
    def clip(sid: str, seq: int):
        path = hub.clip_path(sid, seq)
        if path is None:
            raise HTTPException(404, f"no clip {seq} in session {sid}")
        return FileResponse(path, media_type="audio/wav")

    @r.get("/scenarios")
    def scenarios():
        return hub.scenarios()

    @r.get("/scenarios/{sid}")
    def scenario(sid: str):
        try:
            return hub.scenario_lines(sid)
        except KeyError:
            raise HTTPException(404, f"no scenario {sid}") from None

    return r
```

In `atcdb/api.py`, replace:

```python

from atcdb.parsing import CONTEXT_MODES
```

with:

```python

from atcdb.live_api import make_router
from atcdb.live_hub import LiveHub
from atcdb.parsing import CONTEXT_MODES
```

In `atcdb/api.py`, replace:

```python

def create_app(db_path: Path | str = ROOT / "data/atc.sqlite", project_root: Path | str = ROOT) -> FastAPI:
    root = Path(project_root).absolute()
```

with:

```python

def create_app(db_path: Path | str = ROOT / "data/atc.sqlite", project_root: Path | str = ROOT,
               live_hub: LiveHub | None = None) -> FastAPI:
    """`live_hub` serves /api/live/ (the demo app); by default one over `project_root`, which loads nothing until the
    app first asks for /api/live/health."""
    root = Path(project_root).absolute()
```

In `atcdb/api.py`, replace:

```python
                "transcripts": {k: models[k] for k in TRANSCRIPT_KINDS if k in models},
                "live": False}

```

with:

```python
                "transcripts": {k: models[k] for k in TRANSCRIPT_KINDS if k in models},
                "live": True}

```

In `atcdb/api.py`, replace:

```python

    # Mounted last: a mount at "/" swallows every route registered after it, so add new routes (such as the phase-4
    # live endpoint) above this line.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

with:

```python

    app.include_router(make_router(live_hub or LiveHub.default(root)))

    # Mounted last: a mount at "/" swallows every route registered after it, so add new routes above this line.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

In `README.md`, replace:

````text

pytest   # 293 tests; the live smoke tests skip without ANTHROPIC_API_KEY
```
````

with:

````text

# 8. live demo helper (Runway Watch): the Mac app starts it; see docs/superpowers/specs/2026-10-20-live-demo-app-design.md.
python scripts/bench_whisper.py                     # once: fetch the GPU Whisper weights (1.5 GB) and check the gate
uvicorn atcdb.api:app --host 127.0.0.1 --port 8020  # /api/live/health, /api/live/sessions, ... (Claude needs a key)

pytest   # the live smoke tests skip without ANTHROPIC_API_KEY; run `env -u ANTHROPIC_API_KEY pytest` to spend nothing
```
````

- [ ] **Step 4: Run the tests, then the helper itself**

Run: `env -u ANTHROPIC_API_KEY python -m pytest -q tests/test_live_api.py` three times; 12 passed each time. Then `env -u ANTHROPIC_API_KEY python -m pytest -q`: no failures.

Then a smoke run over real HTTP, typed lines only and no key, so nothing is spent:

```bash
env -u ANTHROPIC_API_KEY uvicorn atcdb.api:app --host 127.0.0.1 --port 8020 &
curl -s 127.0.0.1:8020/api/live/health
SID=$(curl -s -X POST 127.0.0.1:8020/api/live/sessions | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
curl -s -X POST 127.0.0.1:8020/api/live/sessions/$SID/text -H 'content-type: application/json' \
  -d '{"role": "controller", "t": 0, "text": "fedex 1432 heavy one eight left cleared to land"}'
curl -s -N --max-time 5 "127.0.0.1:8020/api/live/sessions/$SID/stream?max_events=3"
kill %1
```

Expected: health shows `"claude": {"model": "claude-haiku-5-5", "available": false, "reason": "ANTHROPIC_API_KEY not set"}`; the stream shows a `transcript` event (`"text": "fedex one four three two heavy one eight left cleared to land"`), a `rules` extraction with no events, and a `claude` extraction with `"error": "RuntimeError: ANTHROPIC_API_KEY not set"`. Delete the smoke session afterwards: `rm -rf data/live/sessions/$SID`.

- [ ] **Step 5: Commit**

```bash
git add atcdb/live_hub.py atcdb/live_api.py atcdb/api.py README.md tests/test_live_api.py tests/test_api.py
git commit -m "feat: /api/live/ routes for the demo app: sessions, audio and text lines, event stream, replays

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Operational steps (the controlling session, after Task 6)

**O1. Whisper gate (free).** `python scripts/bench_whisper.py`. Already run while planning (2026-10-20, 20 test-split clips): median 1.03 s, word error rate 9.3% on the GPU vs 11.0% for CTranslate2, gate passed. The weights are in `data/models/whisper-medium.en-atc-hf`. Re-run only if the model or the device changes.

**O2. Haiku 5.5 check (paid, about 6 cents; ask the user before running).**
1. `python scripts/record_llm_fixtures.py --model claude-haiku-5-5` (6 calls, a fraction of a cent). In `tests/test_parse_llm.py`, add `"claude-haiku-5-5"` to `RECORDED_MODELS`. For each case where Haiku 5.5's reply maps to something other than the shared expectation, add an explicit `(case, "claude-haiku-5-5")` entry to `RECORDED` under a comment saying it is a finding, not an expectation to fix (as for Haiku 4.5's readback). Run the tests; commit the fixture and the test change.
2. `python scripts/score_pair_events.py --labels ~/Downloads/readback_sheet_A.csv --model claude-haiku-5-5` (dry-run first: about 4.5 cents).
3. `python scripts/pilot_cases.py --model claude-haiku-5-5` (dry-run first: about 1 cent).
4. Apply the spec's Section 8 gate against Sonnet 5's saved results in `docs/results/extraction-pair-events.md`: Haiku 5.5 stays the app's model if it misses at most 2 more of the 32 labelled runway events than Sonnet (Sonnet missed 0) and invents at most twice as many (Sonnet invented 9). Otherwise the app runs with `RUNWAY_WATCH_CLAUDE_MODEL=claude-sonnet-5`.
5. Add the Haiku 5.5 rows to `docs/results/extraction-pair-events.md` and `docs/results/pilot-cases.md`, and a decision-log entry for the outcome; commit.

**O3. Plan B.** Write the SwiftUI app's plan from the spec, the HIG brief and O1 and O2's results.
