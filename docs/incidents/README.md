# Incident reports

Real-world evidence that grounds the runway-only scope and provides case studies for the report.
Source PDFs live in `data/incidents/`, which is git-ignored because the reports are not ours to redistribute. Every case study below carries its own NTSB or DOT OIG URL inline, so each one can be re-fetched without them; the two currently held locally are `dot-oig-AV2025026-runway-incursions-2025-03-12.pdf` and `ntsb-AIR-24-02-austin-2023-02-04.pdf`.

## Files

| File | What it is |
|---|---|
| `ab-incursions-fy2022-2024.csv` | All 47 Category A and B US runway incursions, Oct 2021 - Aug 2024, transcribed from DOT OIG report AV2025026 Exhibit D. Columns: date, airport, state, primary_commercial, category, type (OI = operational incident / controller; PD = pilot deviation; VPD = vehicle/pedestrian; OTH). |
| `2026-03-22-lga-aca8646-rescue35.md` | Primary positive case (fatal): landing clearance then crossing clearance for the same runway, two minutes apart. ASDE-X present but did not alert (vehicles had no transponders). Engine flags it. |
| `2023-02-04-austin-swa708-fdx1432.md` | Positive case: takeoff clearance issued with landing traffic on the same runway. Engine flags it; no ASDE-X at AUS. |
| `2023-01-13-jfk-aal106-dal1943.md` | Counterexample: consistent clearances, correct readback, crew crossed the wrong runway. Engine correctly raises nothing; caught by ASDE-X. |

## Headline numbers (for the proposal)

From `ab-incursions-fy2022-2024.csv` (verified by script, 2026-09-18):

| Severity | n | Controller (OI) | Pilot (PD) | Vehicle (VPD) | Other |
|---|---|---|---|---|---|
| Category A | 17 | 10 (59%) | 5 | 1 | 1 |
| Category B | 30 | 15 (50%) | 10 | 4 | 1 |
| A + B | 47 | 25 (53%) | 15 | 5 | 2 |

Compare all FY2024 incursions (1,758): 62% PD, 17.9% OI, 17.4% VPD (OIG AV2025026 p.4). Controller
errors are ~18% of all incursions but half or more of the serious ones.

Surface surveillance: ASDE-X/ASSC at 44 airports, Runway Status Lights at 20; FAA has no plans to
expand (OIG AV2025026 p.16). Austin had none at the time of the incident (NTSB AIR-24-02).

## Candidate second positive case (to verify before use)

Operational incidents at primary commercial airports in the Category A list, other than Austin:
Chicago Midway 2021-10-13, Orlando Sanford 2021-11-29, Gulfport 2022-03-04, John Wayne
2022-06-23, San Luis Obispo 2022-11-02, **San Diego International 2023-08-11**. San Diego is the most
recent and best documented; check the NTSB docket for whether the clearances themselves were
conflicting before adopting it.

## ASRS triage pass (human task, see `docs/labelling-protocol.md`)

Purpose: estimate, from voluntary reports, (a) what share of communication-attributed incidents
manifest on the runway vs taxiway vs airborne, and (b) what share of pilot deviations leave a trace
on frequency (wrong readback, query, correction). Both numbers are needed to bound the tool's
reachable share of incidents honestly.

Procedure:
1. On https://asrs.arc.nasa.gov/search/database.html search: Event type "Ground Incursion - Runway"
   OR "Ground Incursion - Taxiway", plus Contributing factor "Communication Breakdown" (adjust to
   the form's actual field names). Export CSV; save as `data/incidents/asrs-export-YYYY-MM-DD.csv`.
2. Run `python scripts/make_asrs_triage_sheet.py data/incidents/asrs-export-*.csv` to produce a
   labelling sheet with blank human columns (see script for column definitions).
3. Both labellers fill the sheet independently; `python scripts/score_agreement.py` reports Cohen's
   kappa per column.
