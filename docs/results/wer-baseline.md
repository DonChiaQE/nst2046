# WER: whisper-medium.en-atc / jacktol-ct2

Scored transmissions: **2927** — overall WER **13.0%**

## by speaker_role

| value | n | WER |
|---|---:|---:|
| pilot | 1517 | 18.4% |
| controller | 1213 | 7.2% |
| mixed | 174 | 16.4% |
| unknown | 23 | 34.4% |

## by source_corpus

| value | n | WER |
|---|---:|---:|
| uwb-atcc | 2752 | 12.8% |
| atco2-1h | 175 | 15.5% |

## by facility

| value | n | WER |
|---|---:|---:|
| Area Control (ACC) | 1105 | 11.0% |
| Approach | 1005 | 13.5% |
| Tower | 753 | 15.1% |
| Ground_Control | 42 | 18.4% |
| Radar | 15 | 11.4% |
| ApronS | 3 | 11.1% |
| Approach / Radar | 2 | 11.1% |
| ApronN | 2 | 4.0% |

## by sample_rate

| value | n | WER |
|---|---:|---:|
| 8000 | 2752 | 12.8% |
| 16000 | 175 | 15.5% |

## marker survival (gold occurrences reproduced by ASR in the same transmission)

| word | gold | asr | survival |
|---|---:|---:|---:|
| `ok` | 30 | 37 | 100.0% |
| `okay` | 0 | 0 | - |
| `yeah` | 4 | 9 | 75.0% |
| `bye` | 275 | 292 | 96.7% |
| `hello` | 127 | 131 | 92.9% |
| `thank` | 65 | 75 | 92.3% |
| `thanks` | 2 | 3 | 0.0% |
| `good` | 345 | 360 | 97.1% |
| `please` | 11 | 9 | 81.8% |
| `sorry` | 10 | 6 | 50.0% |
| `say` | 16 | 16 | 87.5% |
| `again` | 23 | 24 | 100.0% |
| `confirm` | 19 | 19 | 89.5% |
| `correction` | 16 | 14 | 75.0% |
| `[hes]` | 0 | 0 | - |

## Additional analysis

**Setup.** `jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper` (CTranslate2, int8, beam 5,
CPU, Apple M3 Pro, ~4.5 s/clip) over the full jacktol/atc-dataset test split (2,927 clips,
29,866 reference words). Gold = jacktol's normalised human transcripts.

**Error profile.** 1,961 substitutions, 412 deletions, 1,500 insertions. 41.9% of transmissions
(1,226) are transcribed perfectly.
- Most frequent substitutions are near-homophones / inflections that are not ATC-critical:
  `cleared`↔`clear` (48), `establish`→`established`, `climb`→`climbing`, `prague`→`praha`, `munchen`→`munich`.
- The *safety-relevant* class is digit confusion: `two`→`three` (12), `three`→`two` (9), `six`→`three` (7),
  `two`→`to` (7), `on`→`one` (7). Digits also dominate deletions and insertions (`two` inserted 72×,
  `eight` 62×, `three` 56×) — the model tends to hallucinate extra callsign/number tokens.
- Some "errors" are gold-side typos (`bline`/`beline`, `fi`/`five`, `singapoore`, `actualy`), so the true WER
  is somewhat lower than 13.0%.

**Role gap.** Pilots 18.4% vs controllers 7.2%. Pilot audio is the far end of the radio link (lower
SNR, more accents, more callsign variety); controller speech is near-field and formulaic. Any
downstream phraseology analysis will therefore be noisier on the pilot side.

**Hesitations.** Against the `atco2-xml` gold (175 ATCO2 clips, which keep `[hes]` markers): the
gold contains 15 hesitation markers, the ASR reproduced **0**. Whisper-style models drop
disfluencies entirely; hesitation-level analysis needs either the original annotations or a
disfluency-aware model. (WER vs the XML gold is 18.5% because it also keeps hyphenated forms and
language markers.)

**Marker survival (lexical).** Informal and confusion cues survive transcription well:
`bye` 96.7%, `good` 97.1%, `ok` 100%, `hello` 92.9%, `again` 100%, `confirm` 89.5%, `say` 87.5%,
`correction` 75%, `sorry` 50% (n=10). Counts are small for several markers; treat sub-100 rows
with n<20 as indicative only.

**Implications for the project.**
1. Lexical signals of informality/confusion are recoverable from ASR output → the
   "mine what preceded `say again`/`confirm`" approach is viable on transcribed audio.
2. Digit/number confusion is the main ASR failure mode and coincides with the most safety-critical
   content — number-related ambiguity findings must be validated against audio or gold text.
3. Disfluencies are invisible to this ASR; do not build hesitation features on model output.
4. Baseline to beat: 13.0% overall / 18.4% pilot. Large-v3 fine-tune and/or light domain
   fine-tuning on target feeds are the obvious next levers.
