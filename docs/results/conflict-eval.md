# Conflict detection, Level 2 (02 Nov 2026)

Positives are synthetic conflicts injected into real tower recordings and accepted by a human check; negatives are the unperturbed real recordings. Recall is lenient (an alert on the injected runway at or after the trigger transmission) unless marked strict (at the trigger). A false alarm is an alert on a negative that adjudication did not find genuine; rates are per hour of recording span. Intervals are 95% percentile bootstrap intervals over recordings (2,000 resamples, seed 0).

## Primary comparison (pre-registered)

| | rule-rules-window-gold | llm-claude-sonnet-5-window-gold | Difference, first minus second (95% CI) |
|---|---|---|---|
| Lenient recall | 87% (80% to 93%) | 90% (84% to 95%) | -3 pts (-9 pts to +2 pts) over 98 positives |
| RUNWAY false alarms / h | 4.1 (1.9 to 6.6) | 4.9 (2.3 to 7.8) | -0.8 (-2.3 to +0.7) over 309 negatives |

## All arms, human and ASR transcripts

| Arm | Positives | Strict | Lenient recall (95% CI) | Warning only | RUNWAY false alarms / h (95% CI) | READBACK alerts / h, not adjudicated (95% CI) | Hours | Incomplete | Not scored |
|---|---:|---:|---|---:|---|---|---:|---:|---:|
| judge-claude-haiku-5-5-sequence-asr | 98 | 71 | 74% (65% to 83%) | 0 | 20.7 (15.7 to 26.0) | 21.9 (16.8 to 27.2) | 2.65 | 0 | 0 |
| judge-claude-haiku-5-5-sequence-gold | 98 | 74 | 78% (69% to 86%) | 0 | 14.7 (10.5 to 19.0) | 18.8 (13.9 to 23.8) | 2.65 | 0 | 0 |
| judge-claude-sonnet-5-sequence-asr | 98 | 67 | 72% (64% to 81%) | 0 | 13.2 (9.2 to 17.2) | 41.5 (34.2 to 48.8) | 2.65 | 0 | 0 |
| judge-claude-sonnet-5-sequence-gold | 98 | 68 | 72% (63% to 82%) | 0 | 14.3 (10.3 to 18.1) | 33.6 (27.1 to 40.2) | 2.65 | 0 | 0 |
| llm-claude-haiku-5-5-window-asr | 98 | 88 | 90% (84% to 95%) | 8 | 5.7 (2.9 to 8.8) | 16.2 (11.8 to 20.9) | 2.65 | 0 | 0 |
| llm-claude-haiku-5-5-window-gold | 98 | 85 | 88% (81% to 94%) | 11 | 5.7 (2.7 to 8.8) | 18.8 (14.0 to 24.0) | 2.65 | 0 | 0 |
| llm-claude-sonnet-5-window-asr | 98 | 89 | 91% (85% to 96%) | 6 | 6.0 (3.0 to 9.3) | 19.6 (14.8 to 25.0) | 2.65 | 0 | 0 |
| llm-claude-sonnet-5-window-gold | 98 | 88 | 90% (84% to 95%) | 6 | 4.9 (2.3 to 7.8) | 21.1 (16.1 to 26.4) | 2.65 | 0 | 0 |
| rule-rules-none-asr | 98 | 86 | 88% (82% to 94%) | 12 | 6.4 (3.1 to 10.0) | 0.0 (0.0 to 0.0) | 2.65 | 0 | 0 |
| rule-rules-none-gold | 98 | 87 | 91% (85% to 96%) | 9 | 5.7 (2.7 to 8.9) | 0.0 (0.0 to 0.0) | 2.65 | 0 | 0 |
| rule-rules-role-asr | 98 | 85 | 87% (80% to 93%) | 13 | 4.5 (2.0 to 7.3) | 5.3 (2.7 to 8.1) | 2.65 | 0 | 0 |
| rule-rules-role-gold | 98 | 85 | 87% (80% to 93%) | 13 | 4.1 (1.9 to 6.6) | 4.5 (2.2 to 7.2) | 2.65 | 0 | 0 |
| rule-rules-window-asr | 98 | 85 | 87% (80% to 93%) | 13 | 4.5 (2.0 to 7.3) | 8.7 (5.5 to 12.3) | 2.65 | 0 | 0 |
| rule-rules-window-gold | 98 | 85 | 87% (80% to 93%) | 13 | 4.1 (1.9 to 6.6) | 10.2 (6.6 to 14.0) | 2.65 | 0 | 0 |

Positives whose injection the check no longer accepts, not scored: none.

## ASR headline: recordings in the ASR model's test split

The Whisper model was fine-tuned on the corpus's train split, so ASR over train-split clips is optimistic. In the real recordings, 405 of the 2016 transmissions (20%) are test split; the other 80% were in its training data. No real recording is entirely in the test split, so the headline reports recall only: it keeps the positives whose trigger transmission is test split (the anchor may still be train split, so a splice's earlier clearance can still be leaked audio), for the human-transcript arms and the ASR arms alike. ASR false alarms appear only in the all-recordings table above, where the leakage makes the reported degradation a lower bound.

| Arm | Positives | Strict | Lenient recall (95% CI) | Warning only | RUNWAY false alarms / h (95% CI) | READBACK alerts / h, not adjudicated (95% CI) | Hours | Incomplete | Not scored |
|---|---:|---:|---|---:|---|---|---:|---:|---:|
| judge-claude-haiku-5-5-sequence-asr | 24 | 17 | 75% (58% to 92%) | 0 | n/a | n/a | 0.00 | 0 | 0 |
| judge-claude-haiku-5-5-sequence-gold | 24 | 15 | 67% (50% to 83%) | 0 | n/a | n/a | 0.00 | 0 | 0 |
| judge-claude-sonnet-5-sequence-asr | 24 | 14 | 62% (42% to 79%) | 0 | n/a | n/a | 0.00 | 0 | 0 |
| judge-claude-sonnet-5-sequence-gold | 24 | 12 | 58% (38% to 79%) | 0 | n/a | n/a | 0.00 | 0 | 0 |
| llm-claude-haiku-5-5-window-asr | 24 | 18 | 75% (58% to 92%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| llm-claude-haiku-5-5-window-gold | 24 | 17 | 75% (58% to 92%) | 6 | n/a | n/a | 0.00 | 0 | 0 |
| llm-claude-sonnet-5-window-asr | 24 | 19 | 79% (62% to 96%) | 4 | n/a | n/a | 0.00 | 0 | 0 |
| llm-claude-sonnet-5-window-gold | 24 | 18 | 75% (58% to 92%) | 4 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-none-asr | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-none-gold | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-role-asr | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-role-gold | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-window-asr | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |
| rule-rules-window-gold | 24 | 19 | 79% (62% to 96%) | 5 | n/a | n/a | 0.00 | 0 | 0 |

## Recall by injection kind (lenient hits / scored)

| Arm | runway_swap | holdshort_to_cross | verb_upgrade | release_delete | splice |
|---|---:|---:|---:|---:|---:|
| judge-claude-haiku-5-5-sequence-asr | 0/0 | 2/4 | 1/1 | 1/1 | 69/92 |
| judge-claude-haiku-5-5-sequence-gold | 0/0 | 2/4 | 1/1 | 1/1 | 72/92 |
| judge-claude-sonnet-5-sequence-asr | 0/0 | 2/4 | 1/1 | 1/1 | 67/92 |
| judge-claude-sonnet-5-sequence-gold | 0/0 | 2/4 | 1/1 | 1/1 | 67/92 |
| llm-claude-haiku-5-5-window-asr | 0/0 | 4/4 | 1/1 | 1/1 | 82/92 |
| llm-claude-haiku-5-5-window-gold | 0/0 | 4/4 | 1/1 | 1/1 | 80/92 |
| llm-claude-sonnet-5-window-asr | 0/0 | 4/4 | 1/1 | 1/1 | 83/92 |
| llm-claude-sonnet-5-window-gold | 0/0 | 4/4 | 1/1 | 1/1 | 82/92 |
| rule-rules-none-asr | 0/0 | 4/4 | 1/1 | 1/1 | 80/92 |
| rule-rules-none-gold | 0/0 | 4/4 | 1/1 | 1/1 | 83/92 |
| rule-rules-role-asr | 0/0 | 4/4 | 1/1 | 1/1 | 79/92 |
| rule-rules-role-gold | 0/0 | 4/4 | 1/1 | 1/1 | 79/92 |
| rule-rules-window-asr | 0/0 | 4/4 | 1/1 | 1/1 | 79/92 |
| rule-rules-window-gold | 0/0 | 4/4 | 1/1 | 1/1 | 79/92 |

## Failure taxonomy of RUNWAY alerts on real recordings

| Arm | genuine | parse_error | missing_release | other_frequency | engine_rule | unadjudicated |
|---|---:|---:|---:|---:|---:|---:|
| judge-claude-haiku-5-5-sequence-asr | 0 | 24 | 11 | 0 | 20 | 0 |
| judge-claude-haiku-5-5-sequence-gold | 0 | 9 | 9 | 0 | 21 | 0 |
| judge-claude-sonnet-5-sequence-asr | 0 | 7 | 5 | 0 | 23 | 0 |
| judge-claude-sonnet-5-sequence-gold | 0 | 7 | 6 | 0 | 25 | 0 |
| llm-claude-haiku-5-5-window-asr | 0 | 4 | 8 | 0 | 3 | 0 |
| llm-claude-haiku-5-5-window-gold | 0 | 2 | 9 | 0 | 4 | 0 |
| llm-claude-sonnet-5-window-asr | 0 | 2 | 11 | 0 | 3 | 0 |
| llm-claude-sonnet-5-window-gold | 0 | 1 | 8 | 0 | 4 | 0 |
| rule-rules-none-asr | 0 | 1 | 10 | 0 | 6 | 0 |
| rule-rules-none-gold | 0 | 0 | 10 | 0 | 5 | 0 |
| rule-rules-role-asr | 0 | 0 | 9 | 0 | 3 | 0 |
| rule-rules-role-gold | 0 | 0 | 8 | 0 | 3 | 0 |
| rule-rules-window-asr | 0 | 0 | 9 | 0 | 3 | 0 |
| rule-rules-window-gold | 0 | 0 | 8 | 0 | 3 | 0 |

## Agreement and generator precision

Adjudication agreement: no alert has been labelled by both adjudicators yet.

| Injection kind | Accepted | Rejected | Not checked |
|---|---:|---:|---:|
| runway_swap | 0 | 1 | 0 |
| holdshort_to_cross | 4 | 1 | 0 |
| verb_upgrade | 1 | 0 | 0 |
| release_delete | 1 | 0 | 0 |
| splice | 92 | 0 | 0 |

## CROSS and LUAW staleness sensitivity (a finding, not a tuning)

The longest real recording spans 139 s, so on the real recordings no timeout of 139 s or more can change anything; spliced positives can span up to about 280 s, so longer values can still change recall. Values are shown for sensitivity only, re-folding the stored events without new parses, so window arms keep the context they were parsed with at 300 s. `engine.STALE_S` stays at 300 s.

rule-rules-window-gold:

| CROSS and LUAW timeout | Lenient recall | RUNWAY alerts on negatives (raw) |
|---:|---|---:|
| 30 s | 75/98 | 11 |
| 60 s | 85/98 | 11 |
| 90 s | 85/98 | 11 |
| 120 s | 85/98 | 11 |
| 300 s | 85/98 | 11 |

llm-claude-sonnet-5-window-gold:

| CROSS and LUAW timeout | Lenient recall | RUNWAY alerts on negatives (raw) |
|---:|---|---:|
| 30 s | 79/98 | 12 |
| 60 s | 88/98 | 13 |
| 90 s | 88/98 | 13 |
| 120 s | 88/98 | 13 |
| 300 s | 88/98 | 13 |

## Caveats

- The positives are synthetic. Most are splices: one real recording ending with a runway reservation, followed by another real recording from the same airport with a conflicting clearance. The rest are single edits of real text. Only the incident case studies (phase 4) are real conflicts.
- Injection sites come from a keyword scan of clearance phrases with a runway. Conflicts phrased in ways the scan misses are not represented, which favours parsers that handle the same phrasing.
- For text edits, the edited transmission's audio still says the original words, so its ASR transcript is the edited gold text; the ASR arms test noise on the rest of the sequence only.
- The engine treats runway designators as separate runways, so a clearance for 13 and one for 31 (the two ends of one strip) never conflict.
- The judge reports no severity; every conflict it reports is scored as an alert.
- Adjudicators see the human transcript, not what an ASR arm heard, so an ASR arm's alert is judged against what was said.
- One verdict is applied to every arm that raised the same alert (same recording, type, runway and trigger transmission), whatever callsigns each arm extracted.
- A judge READBACK report without a normalisable runway is dropped, which shapes the judge's READBACK numbers.
- READBACK alerts were not adjudicated (decision log, 2026-10-25). Their column counts every READBACK alert on the real recordings, so it bounds READBACK false alarms from above, and the failure taxonomy covers RUNWAY alerts only.
- Lenient recall credits any later alert on the injected runway, which favours noisier arms; compare it with strict recall.
