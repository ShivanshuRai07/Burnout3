# Academic Librarian CBI import — quality report

- Loader version: `1.2.0`
- Source workbook: `Academic_Librarian_Burnout_Dataset.xlsx` (sheet: `Burnout+Research_August+26%2C+2`)
- Rows in workbook: **1,836**
- Clean, eligible records exported: **1,598**
- Official repository description reports N=1,628; current export differs by 30 records and needs reconciliation.

## Checks

- Explicit consent recorded: 1,836/1,836
- `Finished = True`: 1,768/1,836
- Current US academic-library work marked Yes: 1,677/1,836
- MLS/ALA-equivalent degree marked Yes: 1,640/1,836
- All seven CBI items answered: 1,598
- At least four CBI items answered: 1,598
- Duplicate complete source rows: 0
- Score formula verified: **PASS**
- Scores within 0–100: **PASS**
- Item values on 0/25/50/75/100 scale: **PASS**

## Score summary

- Mean: 49.669
- Standard deviation: 20.593
- Median: 50.0
- Percentage with score ≥ 50: 52.13% (operational label only)
- Cronbach's alpha (complete item responses): 0.8965
- Raw item 7 correlation with items 1–6 mean: -0.4618 (should usually be negative before reverse-scoring)

## Important limits

- This file validates import and CBI score computation. Because the target score is calculated from these same seven CBI items, using those items to predict the score would cause target leakage.
- It has no workplace-system predictors or follow-up outcomes, so it cannot validate workplace-only early-warning, forecasting, or intervention-effectiveness claims.
- The employee IDs in the exported file are generated row IDs, not known persistent employee identities.
- Check the dataset repository's current licence and permission requirements before commercial use.

Detailed metrics: `real_librarian_cbi.report.json`
