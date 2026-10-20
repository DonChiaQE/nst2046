# Pilot cases: rules vs Sonnet vs Haiku 5.5, real output (20 Oct 2026)

Replaces the "LLM parser (predicted output)" column of Milestone 1, Appendix B. Both cases use gold transcripts and
`window` context (the pre-registered primary arm): the parser sees the speaker's role, the last 4 transmissions and
what the engine is tracking. Reproduce with `python scripts/pilot_cases.py` (Austin's Sonnet parses are not cached, so
each run costs about $0.12; Prague's come from the events cache). Haiku 5.5, the live demo app's model, was added the
same day as its week-1 check: `python scripts/pilot_cases.py --model claude-haiku-5-5`, about 1 cent a run.

## Austin (KAUS), 4 Feb 2023, runway 18L (NTSB DCA23FA149)

Transcript from 0628:26 (every earlier 18L departure had already been sent to departure) to 0642:14.

| Time | Transmission (shortened) | Rules | Sonnet | Haiku 5.5 |
|---|---|---|---|---|
| 0634:14 | "fedex fourteen thirty-two heavy ... one eight left cleared to land" | nothing (no "runway" before the designator) | LAND 18L, fedex fourteen thirty-two heavy | LAND 18L, fedex fourteen thirty-two heavy |
| 0638:58 | "southwest seven zero eight ... runway one eight left cleared for takeoff ..." | TAKEOFF 18L. **No alert**: 18L was never reserved | TAKEOFF 18L. **Alert**: runway 18L, Southwest vs FedEx | TAKEOFF 18L. **Alert**: runway 18L, Southwest vs FedEx |
| 0639:34 | "fedex ... that is affirmative one eight left you are cleared to land ..." | LAND 18L, no callsign. **Warning** (36 s after the takeoff clearance) | LAND 18L. Alert | LAND 18L. Alert |
| 0640:34 | "fedex is on the go" (FedEx going around) | nothing | **TAKEOFF 18L** (wrong: a go-around read as a takeoff). Warning | GO_AROUND, fedex fourteen thirty-two heavy (right) |

- Sonnet catches the conflict the moment the takeoff clearance is issued. The rules parser drops the landing
  clearance and only warns at FedEx's re-confirmation, 36 s later. Milestone 1 said the rules parser "raises nothing";
  it does raise a warning, just late and without FedEx's callsign.
- Sonnet also invented an event: it read "on the go" (pilot slang for a go-around) as a takeoff. Here it only added a
  warning to a real conflict, but the same misreading elsewhere would be a false alarm.
- Haiku 5.5 raises the same alert as Sonnet at the takeoff clearance and reads "on the go" correctly as a go-around.
  It misreads other lines instead: FedEx's call "southwest abort" as Southwest going around, Spirit's "holding short
  one eight right, ready to go" as a hold-short, and "you're on local" as a handoff to tower. None of these changed a
  conflict here.

## Prague (LKPR), runway 13 (UWB-ATCC recording 528)

| Time | Transmission | Rules | Sonnet | Haiku 5.5 |
|---|---|---|---|---|
| 53 s | "air france one nine eight romeo now expedite cross runway one three continue via delta to hold short of runway two four" | CROSS 13, HOLD_SHORT 24 | CROSS 13, HOLD_SHORT 24 | CROSS 13, HOLD_SHORT 24 |
| 61 s | (pilot) "thank you expedite and cross delta" | nothing | **READBACK alert**: the readback leaves out runway 13 | Same READBACK alert |
| 65 s | "air france one nine eight romeo cross runway one three cross runway one three" | CROSS 13 | CROSS 13 | CROSS 13 |
| 90 s | "csa three eight whiskey runway one three cleared to land ..." | LAND 13. **Alert**: CSA vs Air France | LAND 13. **Same alert** | LAND 13. **Same alert** |

- As predicted, both raise the same RUNWAY alert. Air France had crossed, but nobody said so on the tower frequency,
  so the engine still holds its crossing. Under the new false-alarm categories this is `missing_release`: no choice of
  extractor can remove it.
- Sonnet also raised a READBACK alert the rules parser did not. It may be genuine: the pilot read back "cross delta",
  not runway 13, and the controller repeated "cross runway one three" straight away. To be adjudicated with the rest.

## What this shows (two cases, so no rates)

- Prediction confirmed on the extraction the pilot was about: the LLM handles a landing clearance without the word
  "runway"; the regex does not.
- Not predicted: Sonnet invented a takeoff from pilot slang. This is the hallucination risk from Milestone 1 seen on
  real data, and it belongs in the mechanism section.
- The Prague false alarm is not an extraction problem. It needs a release that was never spoken.
- Haiku 5.5, at about a tenth of Sonnet's price, raises the same conflicts as Sonnet on both cases. It avoids Sonnet's
  invented takeoff but misreads other pilot calls, so the hallucination point stands for both models.
