# Labelling guide

The injection check is done (98 valid, 2 rejected) and the evaluation has run; the adjudication sheets are waiting now.
Each takes one column of answers. The event sheets are skipped for Milestone 2 (decision log, 2026-10-22): the extraction results use the
readback sheet's 200 labelled instructions instead. Section 1 stays for whenever there is time.

| Sheet | Who | Rows | Fill in | When |
|---|---|---:|---|---|
| `injection_check.csv` | Jennifer | 100 | `valid` | done 2026-10-25 |
| `event_sheet_A.csv` | Don | 200 | `events` | skipped for now |
| `event_sheet_B.csv` | Jennifer | 50 (the same lines as A's first 50) | `events` | skipped for now |
| `adjudication_A.csv` / `_B.csv` | Don / Jennifer | 94 / 31 (one row per RUNWAY alarm) | `verdict` | now |

**Rules for every sheet**
- Work blind. Don't look at the other person's answers until both of you are done, and don't look at what the rules
  parser or Claude said about a line. The point is to measure them against you.
- Unsure? Give your best answer and write why in `notes`. A note is always better than leaving a cell blank.
- Open the CSV in Numbers, Excel or Google Sheets. To put two answers in one cell, start a new line inside the cell
  (Option+Return). Save it back as CSV with the same file name and columns, in this folder.

Time: about an hour for the 100 injection checks (and, if the event sheets are done later, an hour for Don's 200
lines and 20 minutes for Jennifer's 50).

---

## 1. Event sheets: what does each line actually say?

Each row is one radio transmission from a real tower recording. You write the runway events in it; later each extractor
is scored against your answer.

- `text` is the line to label. Label only this line.
- `context` shows the 4 lines before it, with who said each. Use it only to understand who is who and which runway is
  in use.
- `role` says whether a controller or a pilot spoke. `clip_path` is the audio, if you want to listen; the text is enough.

**Write one event per line in the `events` cell, or `noop` if there is none.**

| Write | When the line... | Example line | Cell |
|---|---|---|---|
| `land <runway> <callsign>` | clears an aircraft to land | csa one two three runway three one cleared to land | `land 31 csa one two three` |
| `takeoff <runway> <callsign>` | clears it for takeoff | lufthansa four five six runway two four cleared for takeoff | `takeoff 24 lufthansa four five six` |
| `luaw <runway> <callsign>` | tells it to line up (and wait) | speedbird one runway three one line up and wait | `luaw 31 speedbird one` |
| `cross <runway> <callsign>` | clears it to cross a runway | csa one two three cross runway two four | `cross 24 csa one two three` |
| `hold_short <runway> <callsign>` | tells it to hold short, or to taxi to a holding point | lufthansa four five six taxi to holding point runway zero six | `hold_short 06 lufthansa four five six` |
| `handoff <unit> <callsign>` | tells it to contact another unit | csa one two three contact ground one two one decimal nine | `handoff ground csa one two three` |
| `vacated <callsign>` | reports the runway vacated | runway vacated csa one two three | `vacated csa one two three` |
| `go_around <callsign>` | tells it to go around, or the pilot says they are going around | csa one two three go around | `go_around csa one two three` |
| `readback <callsign>` | is a pilot repeating a clearance back | (pilot) runway three one cleared to land csa one two three | `readback csa one two three` |
| `noop` | has none of the above | csa one two three good morning | `noop` |

**How to write the parts**
- **Callsign:** the words exactly as in `text`, in lower case. If no callsign is said, leave it out: `land 31`.
- **Runway:** in digits, as said: three one is `31`, zero six is `06`, one eight left is `18L`.
- **Unit for a handoff:** `ground` (ground or apron), `tower`, `departure`, or `approach` (approach, radar or director).
  Area control ("Prague Control", "centre") counts as `departure`. A frequency with no unit named is `noop`, with
  `handoff, unit not named` in notes.
- **Several events in one line:** one per line in the cell, in the order spoken. "csa one two three cross runway two four
  hold short of runway three one" becomes `cross 24 csa one two three` and, on the next line, `hold_short 31 csa one two three`.

**Tricky cases**
1. **Readbacks.** A pilot repeating a clearance is `readback`, never the clearance itself. Only controllers clear.
2. **Approach clearances are not landing clearances.** "Cleared ILS approach runway one three" and "continue approach"
   are `noop`. (Both Claude models got this wrong in the earlier check, so it matters.)
3. **"Vacate left via alpha" is an instruction, not a report**: `noop`. If the same line also says "contact ground",
   write the handoff. Only "runway vacated" or "vacated" said as done is `vacated`.
4. **Runway not said.** If the context makes the runway obvious (one runway in use), write it and add
   `runway from context` in notes. If you can't tell, write `noop` and explain in notes ("landing clearance, runway unknown").
5. **Conditional clearances** ("behind the landing airbus, line up runway three one behind"): label the clearance
   (`luaw 31 ...`) and write `conditional` in notes.
6. **Corrections** ("cleared to land, correction, continue approach"): label only what stands at the end.
7. **Garbled or half-heard lines:** your best reading, with `unsure` in notes.
8. **`role` = mixed** means the clip caught both speakers. Label everything in it, in order: the controller's part as
   the clearance, the pilot's repeat as `readback`.

**Check your sheet** when you finish (Don runs this for Jennifer's too):

```
python scripts/make_event_sheet.py --check data/labels/event_sheet_A.csv
```

It lists every cell it cannot read (a typo in a kind, a runway not in digits) and how many rows are still empty. Aim for
`0 unparseable cells, 0 rows not yet labelled`.

---

## 2. Injection check: are our fake conflicts believable? (Jennifer)

To test conflict detection we need conflicts, and real recordings almost never contain one. So Don's generator made 100
by changing one line of a real recording (8 rows), or by joining two real recordings from the same airport so that a
clearance in the second clashes with one still open from the first (92 rows, `edit_kind` = `splice`). Your job is to
say whether each one is believable. Don made them, so he must not check them; that is why it is your sheet.

**What a row shows**
- `context`: the lines around the conflict. `A>` marks the first clearance (it holds the runway), `B>` marks the line
  that clashes with it. In a splice, `--- recording N ---` marks where the second recording was joined on.
- `before` and `after`: line B before and after the change. For a splice they are the same, since nothing was edited.
- `runway`: the runway the two clash on.

**Write `yes` in `valid` only if all three are true; otherwise write `no` and say why in `notes`.**
1. B is for a different aircraft than A.
2. Nothing between A and B lets A's aircraft off the runway: no "vacated", no handoff to ground or departure after it
   landed or took off, no cancelled clearance. For a splice, check the end of the first recording too. For
   `release_delete`, the deleted line must have been A's own release.
3. Line B reads like something a controller would really say.

Example notes for a `no`: `same aircraft`, `A vacated before B`, `A handed to departure before B`, `B phrasing odd`.

When you're done, Don records the answers with
`python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv`. Only `yes` rows are used.

---

## 3. Adjudication: why did each alarm happen? (after the evaluation run)

`python scripts/eval_conflicts.py adjudicate` writes one row per RUNWAY alarm the extractors raised on real recordings
(which contain no real conflicts): 94 rows after the 2026-10-25 run. Don takes every row (sheet A), Jennifer a fixed
30% of them (sheet B, 31 rows). READBACK alarms are not on the sheets: the report gives their raw count instead
(decision log, 2026-10-25). For each row, write one `verdict`:

| Verdict | Means |
|---|---|
| `genuine` | it really is two clashing clearances |
| `parse_error` | the extractor misread a line |
| `missing_release` | the reading was right, but the line that would have freed the runway was never said |
| `other_frequency` | the reading was right, but the freeing line or the other aircraft was on a frequency we don't have (ground, apron) |
| `engine_rule` | the reading was right, but the conflict rules are too strict (for example a conditional clearance) |

This is the professor's point 4: every false alarm gets a cause.

**How to decide (agreed 2026-11-02; neither of us is a controller, so follow these steps rather than judging).**
`context` shows the whole recording up to the alarm. Read the lines above the `>>` line and stop at the first answer:

1. Above it, is a *different* plane cleared onto the *same* runway (`cleared to land`, `cleared for takeoff`, `line up`,
   `cross`)? **No:** `parse_error` (the system made up the second plane). If the `>>` line names no plane, it is for
   the plane the controller spoke to just before.
2. After that clearance, is that plane told or does it say `vacated`, `contact ground`, `contact departure`,
   `go around` or `hold short`? **Yes:** `parse_error` (the system missed the release).
3. Is the `>>` line a line-up (`line up`, `line up and wait`, `behind ... line up`)? **Yes:** `engine_rule` (the
   controller is queueing it on purpose; the rules count that as a conflict).
4. Otherwise `missing_release`, or `other_frequency` if the release was probably said on ground's frequency.

`genuine` is for two planes really cleared onto the runway at once with nothing between; expect none. If no step fits,
take the closest and start `notes` with `none fits:`.
