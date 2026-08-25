import csv
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

COLUMNS = ["split", "clip_id", "path", "sample_rate", "duration_s", "text", "match_method", "source_corpus",
           "source_id", "speaker_role", "speaker_label", "pilot_callsign", "speaker_index", "airport_icao",
           "airport_name", "facility", "frequency_mhz", "recorded_at_utc", "recording_id", "seg_start_s",
           "seg_end_s", "orig_text", "ner_text", "correct_transcript"]

ROWS = [
    dict(split="train", clip_id="train_00000", text="swiss one two four descend flight level one hundred",
         source_corpus="atco2-1h", source_id="atco2_test-set-1h_LSZH_ZURICH_Tower_118_1MHz_20210414_085908-A__000000-000200",
         speaker_role="controller", speaker_label="ATCO tower", speaker_index="A", airport_icao="LSZH",
         airport_name="Zurich", facility="Tower", frequency_mhz="118.1", recorded_at_utc="2021-04-14T08:59:08",
         recording_id="LSZH_ZURICH_Tower_118_1MHz_20210414_085908", seg_start_s="0.00", seg_end_s="2.00",
         ner_text="[#callsign]Swiss[/#callsign] [#callsign]One[/#callsign] [#callsign]Two[/#callsign] [#callsign]Four[/#callsign] "
                  "[#command]descend[/#command] [#value]flight[/#value] [#value]level[/#value] [#value]one[/#value] [#value]hundred[/#value]",
         correct_transcript="1"),
    dict(split="train", clip_id="train_00001", text="descending flight level one hundred swiss one two four",
         source_corpus="atco2-1h", source_id="atco2_test-set-1h_LSZH_ZURICH_Tower_118_1MHz_20210414_085908-B__000200-000400",
         speaker_role="pilot", speaker_label="SWR124", pilot_callsign="SWR124", speaker_index="B", airport_icao="LSZH",
         airport_name="Zurich", facility="Tower", frequency_mhz="118.1", recorded_at_utc="2021-04-14T08:59:08",
         recording_id="LSZH_ZURICH_Tower_118_1MHz_20210414_085908", seg_start_s="2.00", seg_end_s="4.00",
         ner_text="[hes] descending flight level one hundred [#callsign]Swiss[/#callsign] [#callsign]One[/#callsign] [#callsign]Two[/#callsign] [#callsign]Four[/#callsign]",
         correct_transcript="1"),
    dict(split="test", clip_id="test_00000", text="we are not ready now foxtrot lima delta",
         source_corpus="atco2-1h", source_id="atco2_test-set-1h_LSGS_SION_Tower_118_3MHz_20210502_065945-D__000000-000300",
         speaker_role="unknown", speaker_label="UNK-1", speaker_index="D", airport_icao="LSGS", airport_name="Sion",
         facility="Tower", frequency_mhz="118.3", recorded_at_utc="2021-05-02T06:59:45",
         recording_id="LSGS_SION_Tower_118_3MHz_20210502_065945", seg_start_s="0.00", seg_end_s="3.00", correct_transcript="1"),
    dict(split="train", clip_id="train_00002", text="lufthansa five mike echo contact ground one two one nine bye",
         source_corpus="uwb-atcc", source_id="uwb-atcc_TWR-Cs5J1G_000640_000900_AT", speaker_role="controller",
         airport_name="Czech airspace (undisclosed)", facility="Tower", recording_id="uwb-atcc_TWR-Cs5J1G",
         seg_start_s="6.40", seg_end_s="9.00"),
    dict(split="train", clip_id="train_00003", text="one two one nine bye bye lufthansa five mike echo",
         source_corpus="uwb-atcc", source_id="uwb-atcc_TWR-Cs5J1G_000900_001150_PI", speaker_role="pilot",
         airport_name="Czech airspace (undisclosed)", facility="Tower", recording_id="uwb-atcc_TWR-Cs5J1G",
         seg_start_s="9.00", seg_end_s="11.50"),
    dict(split="test", clip_id="test_00001", text="csa one two three descend flight level two hundred descending two hundred csa one two three",
         source_corpus="uwb-atcc", source_id="uwb-atcc_ACCU-99d9Oj_001614_001992_PIAT", speaker_role="mixed",
         airport_name="Czech airspace (undisclosed)", facility="Area Control (ACC)", recording_id="uwb-atcc_ACCU-99d9Oj",
         seg_start_s="16.14", seg_end_s="19.92"),
]


@pytest.fixture
def fixture_csv(tmp_path: Path) -> Path:
    """A miniature data/jacktol-atc layout: clips/<split>/<clip>.wav + transcripts_enriched.csv."""
    root = tmp_path / "jacktol-atc"
    rows = []
    for i, r in enumerate(ROWS):
        row = {c: "" for c in COLUMNS}
        row.update(r)
        row["match_method"] = "pcm_hash"
        row["orig_text"] = row["text"]
        row["sample_rate"] = "8000"
        row["duration_s"] = f"{float(row['seg_end_s']) - float(row['seg_start_s']):.3f}"
        row["path"] = f"clips/{row['split']}/{row['clip_id']}.wav"
        wav = root / row["path"]
        wav.parent.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(i)
        sf.write(wav, (rng.standard_normal(8000) * 0.1).astype("float32"), 8000, subtype="PCM_16")
        rows.append(row)
    out = root / "transcripts_enriched.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return out
