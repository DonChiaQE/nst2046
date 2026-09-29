# References

Full-text reading notes for every paper: `docs/literature-notes.md`.

Consolidated sources for the NST2046 proposal and report. Grouped by the role each plays in the
argument. "Converged" marks sources found independently by three separate literature searches
(2026-09-18); treat those as the core set. Milestone 1 requires at least four reputable sources
including two academic ones.

## 1. Prior art: conflicting clearances and runway incursion detection

| Source | Year | Venue | Role in our argument | Converged |
|---|---|---|---|---|
| Weiß, Centarti, Schmitt, Straub. *Route-Based Detection of Conflicting ATC Clearances on Airports.* https://arxiv.org/abs/1304.6494 | 2013 | ESAVS | Closest prior art: cross-checks clearances for runway conflicts, but from electronic flight strips, not voice. Our gap statement. | yes |
| Helmke et al. *Readback Error Detection by Automatic Speech Recognition and Understanding* (HAAWAII). https://www.sesarju.eu/sites/default/files/documents/sid/2022/paper_3.pdf | 2022 | SESAR Innovation Days | Rules+ML on 7.7 h of **real** Isavia audio: 82% detection at **67% false-alarm rate** (Table V); 82%/13% only on scripted trials. Evaluation ladder gold-annotation/gold-transcript/ASR. The realistic ceiling. | yes |
| Young, Jones (NASA Langley). *Runway Incursion Prevention: A Technology Solution.* https://ntrs.nasa.gov/api/citations/20070030080/downloads/20070030080.pdf | 2001 | NASA NTRS (presented Athens, Nov 2001) | DFW flight test: airborne alerting 43-44/47 detections, ground-based 34/47; every error from bad or late surveillance data. | partial |
| Garib et al. *AIRHILT: A Human-in-the-Loop Testbed for Multimodal Conflict Detection in Aviation.* https://arxiv.org/abs/2511.18718 | 2025 | arXiv | Simulated testbed; conflict detection is a **rule ladder**, the LLM only rewords advisories. Where spatial context (ADS-B, vision) would go; cited as the "next test". | partial |

## 2. LLMs and NLP for ATC communication understanding

| Source | Year | Venue | Role in our argument | Converged |
|---|---|---|---|---|
| Deng, Zhang, Yang, Gao. *SCOPE: A Lightweight-training LLM Framework for ATC Readback Monitoring.* https://arxiv.org/abs/2605.29543 | 2026 | arXiv | LLM beats rules on readback anomalies (91% detection) but on semi-synthetic data. Tension with Chang et al. | yes |
| *Aircraft Anomaly Detection using Large Language Models: An ATC Application.* https://arc.aiaa.org/doi/10.2514/6.2024-0744 | 2024 | AIAA SciTech | GPT-4 prompt-based anomaly detection: misses subtle anomalies, hallucinates. Empirical basis for our LLM-judge arm and for keeping the LLM out of the state loop. | partial |
| Ghazanfari et al. *Air Traffic Control using Large Language Models: Prompt Engineering, Architecture, and Evaluation.* https://arxiv.org/abs/2608.19299 | 2026 | arXiv | LLM *generates* controller replies (not extraction); errors accumulate through the model's own history; "sound like controllers without making correct decisions". Supports deterministic state (Approach A). | no |
| Liu, Y. *Large Language Models for Air Transportation: A Critical Review.* https://www.sciencedirect.com/science/article/pii/S2941198X24000356 | 2024 | J. Air Transport Research Society | 12 LLMs on 18 aviation questions: high precision, low recall. No ATC task. Low relevance. | no |
| Zuluaga-Gomez et al. *ATCO2 corpus.* https://arxiv.org/abs/2211.04054 | 2022 | arXiv | Our data source; NER gold for callsign/command/value. | yes |
| Zuluaga-Gomez et al. *Lessons Learned in ATCO2: 5000 hours of ATC communications.* https://arxiv.org/abs/2305.01155 | 2023 | arXiv | In-domain ASR still 18-25% WER; our 13% WER baseline sits in context. | yes |

## 3. Evaluation methodology for safety-critical language systems

| Source | Year | Venue | Role in our argument | Converged |
|---|---|---|---|---|
| Chang, Guleria, Pham et al. *Safety-Oriented Evaluation of Language Understanding Systems for ATC.* https://arxiv.org/abs/2605.11769 | 2026 | arXiv | Consequence-weighted Risk Score on real Changi recordings: LLMs score well on macro-F1 but errors cluster on runway identifiers; Whisper ASR input collapses Risk Score from 0.45 to ~0.05. **We adopt the consequence-weighted metric.** | yes |

## 4. Human factors of alerting and automation

| Source | Year | Venue | Role in our argument | Converged |
|---|---|---|---|---|
| Wickens, Rice, Keller et al. *False Alerts in ATC Conflict Alerting System: Is There a "Cry Wolf" Effect?* https://doi.org/10.1177/0018720809344720 | 2009 | Human Factors 51(4) | ~47% false alerts in en-route conflict alerts did **not** produce cry-wolf behaviour. One side of the disagreement. | yes |
| Ruskin / Friedman-Berg et al. *Alarms, alerts, and warnings in ATC* (ASRS analysis). https://www.sciencedirect.com/science/article/pii/S2590198221002074 | 2021 | Transp. Res. Interdisc. Persp. | Controllers report cry-wolf behaviour, especially in towers. Other side of the disagreement; our setting is tower. | yes |
| Parasuraman, Manzey. *Complacency and Bias in Human Use of Automation.* https://doi.org/10.1177/0018720810376055 | 2010 | Human Factors 52(3) | Automation bias causes omission and commission errors, persists in experts, not trained away. | yes |
| Rovira, Parasuraman. *Effects of Imperfect Automation on Controller Attention and Performance.* https://doi.org/10.1177/0018720810375692 | 2010 | Human Factors | Both misses and false alarms degrade controller performance. | partial |
| Trapsilawati, Wickens, Qu, Chen. *Benefits of imperfect conflict-resolution aids.* https://doi.org/10.1177/0018720816655941 | 2016 | Human Factors | Imperfect aids still net-improve controller conflict resolution. Alternative explanation to consider. | no |

## 5. Normative frameworks

| Source | Year | Venue | Role in our argument | Converged |
|---|---|---|---|---|
| Santoni de Sio, van den Hoven. *Meaningful Human Control over Autonomous Systems.* https://doi.org/10.3389/frobt.2018.00015 | 2018 | Frontiers Robotics & AI | Tracking and tracing conditions. **Primary framework candidate.** The deterministic engine satisfies tracing (explainable, hand-set rules); the LLM-judge arm does not. | yes |
| Cavalcante Siebert et al. *Meaningful human control: actionable properties for AI system development.* https://link.springer.com/article/10.1007/s43681-022-00167-3 | 2022 | AI and Ethics | Operationalises MHC into design properties. | partial |
| Matthias. *The responsibility gap: Ascribing responsibility for the actions of learning automata.* Ethics and Information Technology 6(3). https://dl.acm.org/doi/10.1007/s10676-004-3422-1 | 2004 | Ethics & Inf. Tech. | Supporting framework: who answers when the LLM parser hallucinates a clearance. | yes |
| Santoni de Sio, Mecacci. *Four Responsibility Gaps with Artificial Intelligence.* https://philpapers.org/rec/SANFRG | 2021 | Philosophy & Technology | Distinguishes culpability, accountability and active-responsibility gaps. | no |

## 6. Official incident and statistics sources

| Source | Year | Role in our argument |
|---|---|---|
| NTSB. *DCA26MA161: Jazz Aviation / Air Canada Express Flight 8646 collides with ARFF vehicle on runway 4, LaGuardia, NY, Mar 22 2026* (preliminary report, Apr 23 2026). https://www.ntsb.gov/investigations/Pages/DCA26MA161.aspx | 2026 | Primary positive case study (fatal): landing clearance 23:35:07, crossing clearance for the same runway 23:37:04 with the aircraft on short final. ASDE-X installed but did not alert (vehicles untracked). Two controllers working four positions. See `docs/incidents/`. |
| NTSB. *Aviation Investigation Report AIR-24-02: Runway Incursion and Overflight, SWA 708 and FDX 1432, Austin, TX, Feb 4 2023.* https://www.ntsb.gov/investigations/AccidentReports/Reports/AIR2402.pdf | 2024 | Positive case study: takeoff clearance issued with landing traffic on the same runway; no surface detection at AUS. See `docs/incidents/`. |
| NTSB. *DCA23LA125, JFK Jan 13 2023, AAL 106 / DAL 1943* (abstract). https://www.ntsb.gov/news/press-releases/Pages/NR20240604a.aspx | 2024 | Counterexample: consistent clearances, correct readback, crew crossed the wrong runway; caught by ASDE-X. See `docs/incidents/`. |
| DOT Office of Inspector General. *FAA Runway Incursions* (AV2025026). https://www.oig.dot.gov/sites/default/files/library-items/FAA%20Runway%20Incursions%20Final%20Report_3.12.25.pdf | 2025 | FY2024: 1,758 incursions; 62% pilot deviation, 17.9% operational incident. ASDE-X/ASSC at only 44 airports, no expansion planned. Exhibit D lists all Category A/B incursions FY2022-24 by type (transcribed in `docs/incidents/ab-incursions-fy2022-2024.csv`). |
| FAA. *Runway Safety Statistics.* https://www.faa.gov/airports/runway_safety/statistics | ongoing | Official incursion counts and categories. |
| FAA. *ASDE-X* https://www.faa.gov/air_traffic/technology/asde-x and *ASSC* https://www.faa.gov/air_traffic/technology/adsb/atc/assc | ongoing | Surface surveillance deployment. |
| NASA. *Aviation Safety Reporting System* database. https://asrs.arc.nasa.gov/search/database.html | ongoing | Voluntary, sanitised incident narratives; source for the human triage pass and reconstructed sequences. Exports capped at 10,000 records per download. |
| FAA. *Runway Incursion Rate FY2011-FY2017* (operational metrics). https://www.faa.gov/sites/faa.gov/files/data_research/aviation_data_statistics/operational_metrics/runway_incursion.pdf | 2018 | Time series, US, rate per million operations. |
| FAA. *Runway Incursion Mitigation FY2024 Annual Summary Report.* https://www.airporttech.tc.faa.gov/Products/Airport-Safety-Papers-Publications/Airport-Safety-Detail/runway-incursion-mitigation-fiscal-year-2024-annual-summary-report | 2025 | Annual totals; FY2024 = 1,757. |
| EU Performance Review Body. *Monitoring Report 2023.* https://eu-single-sky.transport.ec.europa.eu/document/download/154b4e6f-819a-4594-81df-8c43ab7ecff7_en?filename=240926_AMR+2023_published+(1).pdf | 2024 | European runway incursions 2015-2023 by member state. Time series, Europe. |
| EUROCONTROL. *European Action Plan for the Prevention of Runway Incursions (EAPPRI) v3.* https://www.eurocontrol.int/publication/european-action-plan-prevention-runway-incursions-eappri | 2017 | "A minimum of two runway incursions every day" in Europe; communication recommendations. |
| IATA. *Annual Safety Report 2024*, executive summary. https://www.iata.org/contentassets/a8e49941e8824a058fee3f5ae0c005d9/safety-report-executive-summary-and-safety-overview-2024_final.pdf | 2025 | Accident-level only: 10 runway excursion accidents in 2024; incursion accidents rare but catastrophic. Substantiates severity, not frequency. |

## Datasets

- ATCO2 corpus (test set 4 h gold, 1 h free subset): https://github.com/idiap/atco2-corpus
- jacktol/atc-dataset on Hugging Face (the merged corpus we load): see README.
- ATCOSIM: https://huggingface.co/datasets/Jzuluaga/atcosim_corpus

## Notes on coherence

The sources agree that (1) clearance cross-checking works from structured inputs but has not been
done from voice; (2) rules+ML readback detection on real audio reaches ~80% recall at ~11% false
alarms; (3) LLMs look good on aggregate metrics but fail on high-consequence slots and degrade
sharply on real ASR input; (4) automation bias is persistent. They disagree on whether false alarms
produce a cry-wolf effect in ATC (Wickens 2009 no, en-route; Ruskin 2021 yes, tower). Our
false-alarms-per-hour measurement in a tower setting speaks to that disagreement.
