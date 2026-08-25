# ATC capture → transcription → database: research notes (2026-08-25)

Status: spike / recommendation. Nothing built yet.

## 1. Sourcing audio from Singapore — what is actually possible

### Own receiver (RTL-SDR / scanner) — NOT viable in SG without a licence
- Scanning receivers are listed as prohibited equipment under the Third Schedule of the
  Telecommunications (Dealers) Regulations; import needs IMDA prior approval.
  https://customs.gov.sg/businesses/national-single-window/tradenet/competent-authorities-requirements/imda-radiocomm-and-dealer-licensing/
- Hobbyist consensus: listening to Changi ATC on an airband radio is illegal in SG
  unless licensed. http://www.sqtalk.com/forum/forum/general/singapore-changi-airport/9614-
- Possible institutional route: IMDA "Temporary Use of Radio Frequency Permit" /
  experimental licence applied for through NUS. https://iris.imda.gov.sg/application/temporary-use-of-radio-frequency-permit
- If a licence is ever obtained: RTLSDR-Airband (multi-channel AM demod, auto-squelch,
  one timestamped file per transmission) is the tool. https://github.com/rtl-airband/RTLSDR-Airband
  Changi freqs: Tower 118.6 / 121.85, Ground 124.3, Delivery 121.65, ATIS 128.6.
  https://www.radioreference.com/db/aid/2731

### LiveATC.net — a Singapore feed DOES exist (verified 25 Aug 2026)
- Feed "WSSS Del/Gnd/App/Radar", status UP, with 30-day archives (archive.php).
  Covers: Clearance 121.65, App/Dep 120.3 & 124.6, Arrival 119.3, Radar sectors
  123.7/124.05/127.3/128.1/133.25/133.35/133.8/134.2/134.4/135.8, Seletar Twr 118.45/130.2,
  Sembawang Twr 129.7. Does NOT include Changi Tower 118.6 or Ground 124.3.
  https://www.liveatc.net/search/?icao=wsss
- Terms of Use constraints (https://www.liveatc.net/legal/):
  - personal, non-commercial use only (§2.1)
  - no robots / automated retrieval without permission (§3.13)
  - consult LiveATC before linking directly to streams; credit LiveATC (§3.15)
  - "Audio streams may not be used in any third-party products."
  → For an academic project: email LiveATC first (contact page) asking permission for
    automated capture of the WSSS feed for non-commercial student research, with
    attribution. Do not scrape before that.

### Existing corpora (use these immediately, no permission needed)
| Corpus | Size | Licence / cost | Notes |
|---|---|---|---|
| ATCO2 test-set-1h | 1 h, manual transcripts + NER | free, MIT | https://github.com/idiap/atco2-corpus |
| ATCO2 test-set (4 h) + PL-set (5,281 h pseudo-labelled) | via ELDA (paid) | https://arxiv.org/abs/2211.04054 |
| UWB-ATCC | ~13 h, manual, speaker roles | free | https://lindat.mff.cuni.cz/repository/xmlui/handle/11858/00-097C-0000-0001-CCA1-0 |
| ATCOSIM | 10 h simulated, close-talk | free | https://www.spsc.tugraz.at/databases-and-tools/atcosim-air-traffic-control-simulation-speech-corpus.html |
| jacktol/atc-dataset | 14,795 clips (ATCO2-1h + UWB), 80/20 split | MIT | https://huggingface.co/datasets/jacktol/atc-dataset |
| aether-raid/astra-atc-models | SG *military* ATC Whisper/Parakeet fine-tunes | "other" | https://huggingface.co/aether-raid/astra-atc-models |

Also worth asking: ATMRI (NTU–CAAS Air Traffic Management Research Institute) for data partnerships.

## 2. ASR models
- jacktol/whisper-large-v3-finetuned-for-ATC — 6.5% WER on ATCO2/UWB test, MIT.
  https://huggingface.co/jacktol/whisper-large-v3-finetuned-for-ATC
- jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper — CTranslate2 build, runs
  on a laptop. https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper
- Jzuluaga/wav2vec2-xls-r-300m-en-atc-uwb-atcc-and-atcosim — CTC alternative.
- Caveat from model cards: accuracy drops on accents not seen in training (European
  data) — expect a Singapore-accent domain gap; that gap is a legitimate ML project.
- Reference pipeline: https://github.com/neemarai04/ATC-Transcription (LiveATC → faster-whisper, no DB, no licence).

## 3. Recommended pipeline
```
source (LiveATC MP3 stream / archive MP3 / SDR file)
  → ffmpeg → 16 kHz mono PCM
  → Silero VAD (push-to-talk ⇒ VAD boundaries ≈ transmissions)
  → clip WAV per transmission (+ UTC start/end, RMS/SNR)
  → faster-whisper (ATC fine-tune), word timestamps, avg_logprob, no_speech_prob
  → callsign/NER extraction (regex + ICAO designators), OpenSky ADS-B context
  → Postgres/SQLite (metadata + text); audio files on disk
```
Tables: feeds, recordings, transmissions, transcripts (model, text, confidence, words JSONB),
annotations (human corrections), aircraft_context.

## 4. Recommendation
1. Now: build & validate the pipeline against ATCO2-1h / jacktol dataset (ground truth
   available → measure WER). Zero legal risk.
2. In parallel: email LiveATC for permission to capture WSSS feed for research.
3. Once granted: point the same pipeline at the live stream + 30-day archives.
4. Do not build an SDR receiver in SG unless NUS obtains an IMDA permit.

## 5. Update (same day): US ATC is acceptable as a source
- Receiving ATC is legal in the US (no licence needed to listen), so LiveATC's hundreds of US
  feeds are the practical source. We're still in SG, so capture is via LiveATC streams/archives,
  and LiveATC's Terms of Use (no automated retrieval without permission, credit, non-commercial)
  remain the governing constraint → still email for permission before automated capture.
- Prefer single-frequency US feeds (e.g. "KXXX Tower", "KXXX Ground", "KXXX Approach") over the
  multiplexed WSSS Del/Gnd/App/Radar feed: each transmission then has a known facility type,
  which is free metadata for ML. Busy majors (KJFK, KBOS, KLAX, KSFO, KORD, KATL, KLAS) have
  high-volume, well-maintained feeds with 30-day archives.
- US-specific corpus for ground truth: LDC ATC0 "Air Traffic Control Complete" (LDC94S14A),
  ~70 h from DFW/BOS/DCA, 8 kHz, continuous single-frequency recordings with per-transmission
  start/end times and full transcripts. Paid via LDC (NUS may already be a member — ask the library).
  https://catalog.ldc.upenn.edu/LDC94S14A
- 2026 paper: fine-tuning Whisper large-v3 on US ATC with only 55 manually transcribed clips
  from 3 US airports → 13.7% WER (54.8% relative reduction vs European-trained baseline).
  Confirms the EU→US accent/phraseology gap is real and cheap to close.
- Recommended plan is unchanged: build against ATCO2-1h / jacktol now; request LiveATC
  permission; then capture 2–3 single-frequency US feeds (mix tower/ground/approach).
