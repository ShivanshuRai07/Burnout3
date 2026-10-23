# BurnoutIQ: A Measurement-Based Monitoring Loop for Workplace Burnout

**Project documentation.** It describes what the code does and the numbers it produces. Every figure here can be reproduced with the commands in [Section 11](#11-reproducing-the-results).

---

## Contents

1. [Summary](#1-summary)
2. [Research questions](#2-research-questions)
3. [The framework: one monitoring loop](#3-the-framework-one-monitoring-loop)
4. [Measurement: what "burnout" means here](#4-measurement-what-burnout-means-here)
5. [Datasets and provenance](#5-datasets-and-provenance)
6. [The loop model (`burnoutiq/`)](#6-the-loop-model-burnoutiq)
7. [Snapshot models (0–10 score and risk)](#7-snapshot-models-010-score-and-risk)
8. [Key findings](#8-key-findings)
9. [Dashboard and API](#9-dashboard-and-api)
10. [Responsible use](#10-responsible-use)
11. [Reproducing the results](#11-reproducing-the-results)
12. [Limitations and future work](#12-limitations-and-future-work)

---

## 1. Summary

BurnoutIQ is a decision-support prototype for tracking work-related burnout in an organisation over time. Its core is a **closed monitoring loop**, implemented as the Python package `burnoutiq`. Each month it scores a validated burnout survey for every employee, forecasts next month, simulates scenarios, records the support given, and classifies the follow-up result as improved, no change or worsened. Each quarter, a learning step checks which kinds of support are followed by improvement.

The design follows **measurement-based care** (routine outcome monitoring) from psychotherapy research: measure routinely, flag people who are not on track, act, and classify change with the reliable change index (Jacobson & Truax, 1991). BurnoutIQ applies this to workplace burnout.

The dashboard is a demonstration of the loop. The loop itself is the deliverable, and it runs without the dashboard.

## 2. Research questions

1. Which algorithms perform best for each burnout-related prediction task?
2. How do performance, calibration and errors differ, and how much of the accuracy depends on self-reported wellbeing?
3. How can repeated measurements and intervention records be used to monitor progress, and what evidence is needed before calling a change an *effect*?

(The occupational NLP branch was dropped from the project scope.)

## 3. The framework: one monitoring loop

```text
                       OUTER LOOP: organisation learns (quarterly)
   ┌──────────────────────────────────────────────────────────────────────┐
   │  which support is followed by improvement? → effect table → recalibrate│
   │                                                                        │
   │           INNER LOOP: each employee (monthly)                          │
   │   ┌────────┐  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐     │
   └──►│ ASSESS │─►│ PREDICT │─►│ SIMULATE │─►│ INTERVENE │─►│ VERIFY │─────┘
       └────────┘  └─────────┘  └──────────┘  └───────────┘  └────────┘
           ▲                                                      │
           └──────────────── next month's survey ─────────────────┘
   FOUNDATION: data validation · one measurement scale (CBI) · groups < 5 hidden · a person decides
```

| Stage | Input | Rule | Output |
|---|---|---|---|
| Assess | 7 CBI answers | Mean of answered items (item 7 reversed), needs ≥ 4 | Score 0–100; normal < 50, high 50–64, very high ≥ 65 |
| Predict | This month's record | Ridge forecast, employee-level split | Next-month score with 95% range |
| Simulate | Forecast + effect table | 500 paths, 3 months; intervention effects only if the evidence is strong | Median and 10th–90th percentile per scenario |
| Intervene | Flag + human review | A named person records the support | Type, dates, status |
| Verify | Baseline and follow-up score | ≤ −5 improved, ≥ +5 worsened, otherwise no change; *reliable* beyond the RCI | Outcome per intervention |
| Learn | All verified interventions | Matched comparison group; randomised pilot preferred | Effect table with evidence level; calibration check |

**Employee status.** Each employee is always in exactly one state: `monitoring → flagged → support_planned → in_support → follow_up_due / follow_up_overdue → outcome_improved / outcome_no_change / outcome_worsened` (or `left`). Statuses use only information available by that month.

**Who is flagged: the trajectory rule.** Burnout is chronic, so one month over 50 is a *watch*, not a flag. The rule lives in `burnoutiq/trajectory.py`; a person is flagged when any of these holds:
- **Sustained high:** this survey and the previous one (within 3 months) are both ≥ 50.
- **Reliable rise:** this survey is above the person's own 3-month baseline by more than the reliable change index (17.8 points) and is ≥ 40.
- **Quiet after high:** no survey this month, and the last survey within 3 months was ≥ 50. A missed survey after a high score is treated as a signal, not as "no data".

This replaced the earlier "any reference point" rule after a held-out comparison (section 6.4). The three reference points below are still computed and shown as context for why someone stands out.

**Three reference points (context).** The rules live in `burnoutiq/reference.py`:
- **Absolute:** CBI ≥ 50, or working hours ≥ 48 a week (EU Working Time Directive average; set to the local limit).
- **Division:** far above colleagues in the same department and month (robust z ≥ 2); needs at least 5 people.
- **Personal:** a rise of 10 or more points against the person's own last 3 scored months.

A department is **systemic** when it has significantly more high scorers than the reference population (binomial test against PUMA's 19.8%, p < 0.05) or its median week is 48 hours or more. Flagged people in systemic departments need organisational action, not only individual support. This stops "everyone is overworked" from hiding behind a relative baseline.

## 4. Measurement: what "burnout" means here

- **Instrument:** the Copenhagen Burnout Inventory (CBI) work-related subscale (Borritz & Kristensen, 2004). It is free to use, has 7 items, and is scored 0–100.
- **What it measures:** mainly **work-related exhaustion**. The WHO's ICD-11 (QD85) describes burnout as a work-related phenomenon, not a medical condition, with three dimensions: exhaustion, mental distance and reduced professional efficacy. CBI covers exhaustion well, mental distance only partly, and efficacy not at all.
- **The ≥ 50 threshold** is the convention used in CBI/PUMA reporting. It is **not a clinically validated cut-off**. Outputs are worded as "high work-related burnout score", never as a diagnosis.
- **Reliable change:** RCI threshold = 1.96·√2·SD·√(1−α). It is computed from the data: 17.8 points with α = 0.866 on the synthetic panel.

## 5. Datasets and provenance

| Dataset | Nature | Used for |
|---|---|---|
| BurnoutIQ synthetic panel (`Datasets/burnoutiq_dataset/`) | Synthetic, monthly, 2,289 employees × 12 months; CBI scores calibrated to PUMA norms (mean 33, SD 17.7, 19.8% ≥ 50); interventions with known true effects and a randomised pilot | The loop: all stages |
| Academic Librarian Burnout Dataset (Wood et al., Kennesaw State University DigitalCommons) | **Real** 2018 survey; 1,598 respondents with all 7 CBI items | Validating the scoring (α = 0.90; mean 49.7, 52.1% ≥ 50) and showing population shift |
| Tech workforce (`artifacts/master_workforce_dataset.pkl.gz`, source `tech_mental_health_burnout`) | Synthetic, 150,000 rows, one snapshot | 0–10 snapshot models only |
| Other sources in the master file (e.g. HackerEarth) | Different columns; values for missing columns were filled with constants | **Excluded** from training and from the dashboard |

No open dataset links real employees' workplace interventions to their follow-up burnout scores, which is why the loop is demonstrated on a calibrated synthetic panel. The synthetic data's effect sizes are assumptions informed by Job Demands–Resources research; only its score distribution is matched to real data.

## 6. The loop model (`burnoutiq/`)

### 6.1 Input contract

There are three CSV files, and templates are in `templates/` (`python -m burnoutiq --templates templates`):

```text
employees.csv     employee_id, department, [team_id, role_type, contracted_hours_per_week, hire_date, termination_date]
monthly.csv       employee_id, period (YYYY-MM), cbi_w1…cbi_w7, [work hours, overtime, meetings, after-hours messages,
                  leave, perceived workload, manager support, job control, work-life balance, satisfaction, stress, sleep]
interventions.csv [intervention_id], employee_id, intervention_type, referral_period, start_date, planned_end_date,
                  completion_status (planned | in_progress | completed | not_completed | not_applicable), [trial_arm]
```

Only the CBI items are required to run Assess and Verify (adoption level 1). Work data enables Predict and Simulate (level 2). Validation (`schema.py`) reports every row it fixes or drops. In deployment, connectors to the HR, timesheet, calendar and survey systems would produce these files; that is future work.

### 6.2 Results on the synthetic panel (month assessed: 2025-12)

| Measure | Value |
|---|---|
| Employees with a record / scored | 1,681 / 1,180 (response 70%) |
| Mean CBI / % ≥ 50 | 30.5 / 17.6% |
| Flagged (trajectory rule) / watch (one high month) | 279 / 50, of whom 112 flagged for a missed survey after a high score |
| Systemic department | Customer Support: 28.8% ≥ 50 vs 19.8% reference; median 45.5 h |
| Forecast MAE vs same-as-last-month | **7.99 vs 8.69**; RMSE 10.03 vs 11.09; R² 0.659 vs 0.583 |
| 95% forecast range | ±19.65 points, covering **95.4%** of held-out cases (1,652 train / 413 test employees) |
| Support logged / completed | 927 / 451 (plus 119 waitlist controls) |
| Follow-ups due / collected | 770 / 617 |
| Observed outcomes | 358 improved · 149 no change · 110 worsened |

A follow-up survey counts if it is taken in the month the support ends or the month after.

### 6.4 Detection: trajectory and missed surveys vs the earlier rule

`evaluate_detection.py` compares rules on the 393 held-out employees (2,415 employee-months, Apr–Oct 2025). The outcome is **sustained burnout ahead**: the next two answered surveys are both ≥ 50. Full tables: `reports/DETECTION_REPORT.md`.

| Rule | Flags (% of people-months) | Precision | Recall | F1 |
|---|---|---|---|---|
| Earlier rule (any reference point or forecast) | 20.4% | 22.2% | 50.9% | 30.9 |
| One month ≥ 50 | 11.1% | 43.2% | 48.0% | 45.4 |
| Trajectory (sustained or reliable rise) | 8.1% | 43.7% | 34.5% | 38.6 |
| **Trajectory + missed surveys (adopted)** | 13.1% | **45.5%** | **56.1%** | **50.3** |

- The earlier rule flagged one in five people each month and was wrong four times out of five.
- Requiring two high surveys alone is more cautious but misses people; adding the missed-survey signal recovers them. Of 57 people who skipped a month's survey and were burned out afterwards, the adopted rule caught 37; the earlier rule caught 4.
- A logistic regression on the same information confirms it: average precision 0.38 with this month's score only, 0.51 with trajectory features, 0.56 adding missed-survey features (ROC AUC 0.82 → 0.92 → 0.93).
- **Caveat:** the synthetic generator makes people with higher latent burnout less likely to answer, following survey research. The missed-survey signal must be confirmed on real pilot data before it is trusted.

### 6.3 What the learning stage found

| Support type | Mean observed change | Matched comparison change | Adjusted difference (95% CI) | True effect (known in synthetic data) |
|---|---|---|---|---|
| Workload review | −11.1 | −8.4 | −1.5 (−3.8 to 0.8) | −5.7 |
| Schedule adjustment | −7.7 | −8.4 | +1.8 (−0.2 to 3.8) | −3.4 |
| EAP counselling | −8.5 | −8.2 | +0.9 (−1.8 to 3.6) | −2.3 |
| Wellbeing workshop | −3.6 | −5.7 | +2.5 (0.4 to 4.6) | −0.4 |
| **Randomised pilot** (schedule adjustment vs waitlist) | | | **−4.9 (−9.0 to −0.9)** | −3.1 |

Two findings follow:
1. **Raw before/after changes overstate effects** (−8 to −11 points). Most of the drop also happens without support: people are referred when their score is unusually high, and high scores tend to fall anyway (regression to the mean).
2. **Even a matched comparison stays biased**: every type comes out 3–4 points too close to "no effect". People are referred for reasons the data does not record, which keeps their burnout high (confounding by indication). **Only the randomised pilot recovered the true effect.**

The simulation therefore uses the randomised estimate where one exists. It uses an observational estimate only when its whole 95% CI is below zero; otherwise the type is labelled "no reliable effect (not simulated)".

## 7. Snapshot models (0–10 score and risk)

These are trained on the 150,000-row synthetic tech dataset (80/20 train/test, with an internal validation split) using **14 measured numeric columns + 3 categorical**. Earlier versions also used four hand-weighted composite indexes (workload index, wellness score, support index, meeting load). Their weights had no source, they double-counted overtime and they used a wrong scale. They were removed, with no loss in accuracy (R² 0.7442 → 0.7447).

**Task A: burnout score (0–10)**

| Model | Test RMSE | Test MAE | Test R² |
|---|---|---|---|
| Mean baseline | 1.1140 | 0.9253 | 0.000 |
| Ridge | 0.6227 | 0.4953 | 0.688 |
| Random forest | 0.5778 | 0.4330 | 0.731 |
| **Gradient boosting (live model)** | **0.5629** | **0.4221** | **0.745** |

**Task B: elevated risk** (score ≥ 3.70, the training 90th percentile; 10% prevalence)

| Model | ROC-AUC | PR-AUC | Brier | F1 at validation-tuned threshold |
|---|---|---|---|---|
| Logistic regression | 0.9524 | 0.7391 | 0.0505 | 0.669 |
| Random forest | 0.9446 | 0.7094 | 0.0550 | 0.645 |
| Gradient boosting, sigmoid-calibrated (live model) | 0.9501 | 0.7309 | 0.0512 | 0.663 |

Logistic regression is marginally better; the difference is negligible and the gradient-boosting model is kept for consistency with Task A.

**Self-report ablation** (`reports/research/tables/self_report_ablation.md`)

| Features | Test R² | ROC-AUC (elevated) |
|---|---|---|
| All 14 numeric + categorical | 0.744 | 0.950 |
| Without `stress_level` | 0.666 | 0.929 |
| Workplace only (no self-reported wellbeing) | **0.351** | **0.828** |

**Permutation importance** (drop in test R² when a column is shuffled): stress level 0.49, working hours 0.20, work-life balance 0.12, manager support 0.08, overtime 0.03. **Meetings per day: 0.00.** Most of the snapshot model's accuracy comes from self-reports measured at the same time as the target, so the headline R² of 0.745 should not be read as an early-warning result. Meeting-related advice is not supported by this model.

## 8. Key findings

1. **The framework works as a loop on calibrated data.** The forecast beats persistence with an honest 95% range, every employee has a traceable status, and outcomes are classified with stated thresholds.
2. **Calibration is population-specific.** Real librarians average 49.7 against PUMA's 33.0. A model trained on PUMA-like data keeps its ranking (AUC 0.90 → 0.89) but under-predicts levels (36% predicted ≥ 50 vs 53% observed). About 200 local responses are enough to recalibrate it (experiment in `Datasets/burnoutiq_dataset/README.md`; regenerate the shifted data with `generate_burnoutiq.py --calibrate-to librarian`).
3. **Before/after numbers are not effects.** Use a randomised comparison where possible; label everything else "observed change".
4. **Self-reported stress drives the snapshot model.** Workplace data alone gives R² ≈ 0.35, consistent with burnout research, where workload explains part of exhaustion but is far from the whole story.

## 9. Dashboard and API

- **Local:** `python dashboard_server.py --port 8501`; **serverless:** `api/index.py` (Flask, Vercel). Both use the same `LongitudinalTracker`, which builds the loop on startup.
- **Frontend (`frontend/`, the demo):** three pages plus one page per person. **This month** (Assess: departments ranked, survey response, and whether support helped), **People** (quick tabs: needs a decision, in support, follow-up due, has a result; filters; 6-month sparklines; last support → result) and **Data & model** (start, upload, can we trust the forecast). Each person's **Burnout journey** page shows all five stages: where they stand and what drives the score (Assess), the forecast and what-if paths (Predict, Simulate), a form to log support with its evidence, owner and dates and buttons to mark it started, completed or stopped (Intervene), and each support's before → after → result (Verify). Logged support is fed into the loop, so adding the next month verifies it automatically. A month band is always visible with **Add next month**. Details in `frontend/README.md`.
- **Month by month:** the demo can start one month before its end (`POST /api/loop/demo-start`) and add the next month (`POST /api/loop/demo-next`); companies add a later `monthly.csv` with `POST /api/loop/add-month`. Before a month is added, the current model forecasts it for everyone, and the Data & model page compares those forecasts with what came in. In the demo, adding December gave an average error of 8.1 points with 94.5% of scores inside the predicted 95% range: a genuine out-of-sample check.
- **Workload level** (per employee, `burnoutiq/reference.py`): high = hours ≥ 48 or far above colleagues in the same department; elevated = more than 5 hours above contract or perceived workload 4–5/5; otherwise normal. Kept separate from the burnout level, because the cases where they disagree point to different causes.
- **Key endpoints:** `GET /api/loop[?period=YYYY-MM]` (every loop stage, plus `periods`, `source`, `check`), `GET /api/loop/employees` (ranked, filtered list), `POST /api/loop/upload`, `POST /api/loop/add-month`, `POST /api/loop/demo-start`, `POST /api/loop/demo-next`, `POST /api/loop/support`, `POST /api/loop/support/status`, `POST /api/loop/reset`, `GET /api/forecast`, `GET /api/search-employee?id=`, `GET /api/interventions/records`, `POST /api/interventions/record`, `POST /api/interventions/record-followup`, `POST /api/predict`.
- **Uploaded data** is kept in memory only and never written to disk; the demo's saved intervention records are never overwritten.

## 10. Responsible use

- The tool is decision support, not diagnosis. The model flags and suggests; a named person decides.
- Results must never be used for hiring, firing, discipline, pay or promotion.
- Groups under 5 people are suppressed; individual results go only to the person and the HR staff providing support.
- Uploaded files have direct identifiers stripped before processing.
- Before/after comparisons are reported as observed changes.

## 11. Reproducing the results

```powershell
pip install -r requirements.txt
python -m burnoutiq --employees Datasets/burnoutiq_dataset/data/employees.csv --monthly Datasets/burnoutiq_dataset/data/assessments.csv --interventions Datasets/burnoutiq_dataset/data/interventions.csv --out reports/loop
python train.py                      # retrain snapshot models, feature importance, self-report ablation
python build_research_pipeline.py    # research figures and comparison tables
python load_real_cbi.py              # real librarian CBI data -> data/processed/real_librarian_cbi.csv
python -m pytest                     # 94 tests
python dashboard_server.py --port 8501
python frontend/serve.py --port 8600   # then open http://127.0.0.1:8600
```

Material that the current design replaces is kept in `docs/archive/`: the five framework posters and their code, the earlier training scripts and their plots, and the previous `context.md`.

## 12. Limitations and future work

- **Synthetic loop data:** the loop is demonstrated on synthetic data. A small real pilot (30–50 people answering the 7 CBI items monthly for 3 months) is the next step.
- **CBI coverage:** CBI measures exhaustion, not all burnout dimensions. The BAT-12 (Schaufeli, De Witte et al.) has clinically validated cut-offs and would allow "at risk / severe" labels.
- **Workload measurement:** workload is measured as time; work pace, cognitive and emotional demands (e.g. COPSOQ scales) are not captured, and hours are not comparable across job types.
- **Observational effects:** intervention effects outside the randomised pilot are observational and, as shown in 6.3, biased.
- **Connectors:** connectors to HR, timesheet, calendar and survey systems are future work.

### References

- Borritz, M., & Kristensen, T. S. (2004). *Copenhagen Burnout Inventory: normative data and PUMA results.* National Institute of Occupational Health, Denmark.
- Jacobson, N. S., & Truax, P. (1991). Clinical significance: a statistical approach to defining meaningful change in psychotherapy research. *Journal of Consulting and Clinical Psychology, 59*(1), 12–19.
- Wood, B., Guimaraes, A., Holm, C., Hayes, S., & Brooks, K. *Academic Librarian Burnout Dataset.* Kennesaw State University DigitalCommons.
- World Health Organization. ICD-11, QD85 Burn-out.
