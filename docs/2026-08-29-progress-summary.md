# NST2046 project — progress summary (25–29 Aug 2026)

## The goal
Air traffic controllers and pilots sometimes use vague or non-standard language. When a pilot
misunderstands an instruction, it can lead to an incident — but problematic phrasing is usually
only identified after something goes wrong. We want to use ML to spot shaky communication
automatically and find the phrasings that keep causing it, so authorities could check them
proactively.

## What has been done

### 1. Research: where to get ATC audio (25 Aug)
- Listening to ATC with your own radio is illegal in Singapore, so we can't record Changi ourselves.
- LiveATC.net streams many airports (including some Singapore frequencies and hundreds of US
  ones), but automated recording needs their permission — we plan to email them.
- Meanwhile, free research datasets exist with real ATC audio *and* human transcripts. We chose
  the largest free one (14,795 clips, ~14 hours, European airports) to build on.

### 2. Data pipeline and database (25 Aug)
- Downloaded the dataset and unpacked it into individual audio clips plus a spreadsheet of transcripts.
- Recovered information the dataset had lost by matching each clip back to its original source:
  who is speaking (pilot / controller), which airport and facility (tower, approach, area
  control), frequency and time, and expert-annotated labels for callsigns, commands and values.
- Built a database (SQLite) that stores every transmission, its transcripts and its annotations,
  and can reconstruct whole exchanges in order — instruction, readback, next instruction.
- Everything is tested (automated tests) and re-runnable from scratch.

### 3. Speech-to-text baseline (27 Aug) — first ML model
- Ran an ATC-specialised speech recognition model (fine-tuned Whisper, a deep learning model)
  over 2,927 test clips and compared its output to the human transcripts.
- Result: **13.0% word error rate** overall (controllers 7.2%, pilots 18.4%). 42% of
  transmissions were transcribed perfectly.
- Key findings: the model's main mistakes are digits (e.g. "two" vs "three") — exactly the
  safety-critical content; informal words like "ok", "bye", "say again", "confirm" survive
  transcription well; hesitations ("uh") are dropped entirely.

### 4. Readback dataset (29 Aug)
- From the database we paired every controller instruction with the pilot's reply that followed:
  4,275 pairs.
- Rules extract the items a pilot must read back (frequency, level/altitude, heading, squawk,
  runway) and check whether they appear in the reply.
- Built a labelled training set of 3,723 examples: correct readbacks, plus "wrong" readbacks
  made by changing one digit — a standard trick to create training data.
- Explicit confusion ("say again", "confirm") appears in only ~2% of replies — too rare to train
  on alone, which is why readback checking is the main task.

### 5. Readback-checking models (29 Aug) — second ML model
- Rule-based checker (baseline), a simple statistical model (logistic regression), and a
  fine-tuned BERT neural network that reads instruction + reply and judges consistency.
- On the automatically labelled test set: rules ~99% (expected — the labels came from the rules);
  BERT 70% after a short first training run, **93% after a longer one** (10 epochs, ~11 minutes on
  the laptop GPU). The real test is the human-labelled set.
- Prepared labelling sheets (200 pairs, plus 50 for a second person to measure agreement) for
  the team to judge by hand. This is the ground truth the models will be compared on.

## Where ML / AI is used
- **Speech recognition:** fine-tuned Whisper (deep learning) — done, measured.
- **Readback consistency:** logistic regression and BERT (trained by us) vs rules — training done,
  final comparison waits for the human labels.
- **Planned:** a model that tags non-standard / ambiguous phrasing (LLM-assisted labelling,
  then a fine-tuned tagger), and an LLM used as a zero-shot comparison for both tasks.

## What's next
1. Team labels the 200-pair sheet (~2 hours) → compare rules vs models on human judgments.
2. Agree the categories of "risky phrasing"; label 300–500 utterances with LLM help; train the tagger.
3. Analyse what controllers said right before communication broke down → ranked list of
   potentially problematic phrasings.
4. If LiveATC grants permission: capture US airport audio and run the same pipeline at scale.
