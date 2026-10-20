from types import SimpleNamespace

import numpy as np
import soundfile as sf

from atcdb.asr import hf_whisper_transcriber, normalize_asr_text, run_asr
from atcdb.loader import load_enriched_csv
from atcdb.schema import init_db


def test_normalize_lowercases_strips_punctuation_and_spells_digits():
    assert normalize_asr_text("Swiss 124, descend Flight Level 100.") == "swiss one two four descend flight level one zero zero"


def test_normalize_decimal_frequency_and_whitespace():
    assert normalize_asr_text("  contact ground 121.9 \n bye ") == "contact ground one two one decimal nine bye"


def test_normalize_keeps_apostrophe_free_words_and_hyphen_splits():
    assert normalize_asr_text("x-ray, we're ready") == "x ray we're ready"


def fake_transcriber(clip_path):
    # deterministic stand-in for the model: echoes the split directory so tests can check routing
    return {"text": f"Hello from {clip_path.parent.name}", "avg_logprob": -0.25, "no_speech_prob": 0.01,
            "words": [{"word": "hello", "start": 0.0, "end": 0.4, "probability": 0.9}]}


def test_run_asr_stores_one_asr_transcript_per_transmission_in_split(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    n = run_asr(conn, model_name="fake", model_version="v1", transcriber=fake_transcriber, project_root=tmp_path, split="test")
    assert n == 2
    rows = conn.execute("SELECT x.external_id, t.raw_text, t.normalized_text, t.confidence, t.words_json FROM transcripts t "
                        "JOIN transmissions x ON x.id = t.transmission_id WHERE t.kind = 'asr' AND t.model = 'fake' ORDER BY x.external_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["raw_text"] == "Hello from test"
    assert rows[0]["normalized_text"] == "hello from test"
    assert rows[0]["confidence"] == -0.25
    assert '"probability": 0.9' in rows[0]["words_json"]


def test_run_asr_skips_transmissions_already_transcribed_by_that_model(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="test") == 2
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="test") == 0
    assert run_asr(conn, "fake", "v2", fake_transcriber, project_root=tmp_path, split="test") == 2  # new version -> new rows
    assert conn.execute("SELECT count(*) FROM transcripts WHERE kind = 'asr'").fetchone()[0] == 4


def test_run_asr_limit(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="train", limit=3) == 3


def test_run_asr_can_be_limited_to_some_recordings(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    [rid] = [r[0] for r in conn.execute("SELECT id FROM recordings WHERE external_id LIKE '%TWR-Cs5J1G%'")]
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="train", recording_ids=[rid]) == 2
    done = {r[0] for r in conn.execute("SELECT DISTINCT x.recording_id FROM transcripts t "
                                       "JOIN transmissions x ON x.id = t.transmission_id WHERE t.kind = 'asr'")}
    assert done == {rid}
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
