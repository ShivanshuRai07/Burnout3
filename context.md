# BurnoutIQ: Project Context (quick reference)

Short guide for team members and coding assistants. Full write-up: [DOCUMENTATION.md](DOCUMENTATION.md). The previous version of this file is in `docs/archive/context_old.md`.

## What the project is

- **The deliverable is a model.** The `burnoutiq` package runs one monitoring loop per employee per month: **Assess → Predict → Simulate → Intervene → Verify**, plus a quarterly **Learn** step.
- **The dashboard is a demo.** It only displays what the loop computes (`GET /api/loop`). Nothing on it may be typed in by hand.
- **Basis:** measurement-based care (routine outcome monitoring with reliable change), applied to work-related burnout measured with the CBI work subscale.

## Ground rules (keep these when changing anything)

1. **Every number shown is computed** from data or model output. No hard-coded findings, counts or dates.
2. **One scale for the loop:** CBI 0–100; ≥ 50 = "high", a conventional threshold, **not a diagnosis or a "clinical cut-off"**.
3. **Observed change ≠ effect.** Before/after changes are labelled "observed". Only randomised comparisons are treated as effects; the simulation uses observational effects only when their whole 95% CI is below zero.
4. **No merging of incompatible datasets.** Snapshot models and dashboard analytics use only the 150k `tech_mental_health_burnout` source. Never add sources whose missing columns were filled with constants.
5. **Groups under 5 are hidden.** Results are for support only, never for performance, pay or discipline.
6. **No hand-weighted indexes.** Models learn from measured columns (see `burnout_platform/features.py`).

## Where things are

| Path | What |
|---|---|
| `burnoutiq/` | The loop: `schema` (input CSVs), `assess`, `predict`, `simulate`, `intervene` (status, follow-up linking), `verify`, `reference` (absolute/division/personal flags, systemic divisions), `learn` (effect table, randomised pilot, calibration), `loop` (orchestrator) |
| `burnout_platform/loop_view.py` | Turns loop results into dashboard payloads (brief, triage, impact, forecast) |
| `burnout_platform/longitudinal.py` | Tracker used by both servers; builds the loop at startup; intervention action store |
| `dashboard_server.py`, `api/index.py` | Local server and Flask/Vercel server (keep them in sync) |
| `evaluate_models.py`, `train.py` | Snapshot model training (0–10 score, risk), feature importance, self-report ablation |
| `build_research_pipeline.py` | Research figures and comparison tables in `reports/research/` |
| `load_real_cbi.py` | Real librarian CBI data loader (1,598 respondents) |
| `Datasets/burnoutiq_dataset/` | Synthetic panel + its generator (calibrated to PUMA norms; `--calibrate-to librarian`) |
| `frontend/` | The demo: This month, People, Data & model, and a Burnout journey page per person with all five stages, including logging support (see `frontend/README.md`) |
| `templates/` | Empty input CSV templates for a company |
| `docs/archive/` | Replaced material: five framework posters and code, old training scripts and plots, old context |

## Current numbers (synthetic panel, month 2025-12)

- **Forecast:** MAE 7.99 vs 8.69 same-as-last-month; 95% range ±19.65 covering 95.4% of held-out cases.
- **Interventions:** 927 support actions logged; 617 of 770 due follow-ups collected: 358 improved, 149 no change, 110 worsened (observed).
- **Learning:** the matched comparison is 3–4 points too close to "no effect" for every type (confounding by indication). The randomised pilot gives −4.9 (95% CI −9.0 to −0.9) against a true −3.1.
- **Snapshot model:** R² 0.745 with all features, 0.351 with workplace data only. Meetings have zero permutation importance.

## Commands

```powershell
pip install -r requirements.txt
python -m burnoutiq --employees Datasets/burnoutiq_dataset/data/employees.csv --monthly Datasets/burnoutiq_dataset/data/assessments.csv --interventions Datasets/burnoutiq_dataset/data/interventions.csv --out reports/loop
python train.py
python -m pytest            # 94 tests
python dashboard_server.py --port 8501
python frontend/serve.py --port 8600   # the demo frontend
```

The server reads `dashboard.html` once at startup, so restart it after editing the page. `artifacts/intervention_records.json` is a cache that is rebuilt when `RECORD_VERSION` in `longitudinal.py` changes.
