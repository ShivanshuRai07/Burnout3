| model | test_roc_auc | test_pr_auc | test_brier_score | test_f1_at_0_5 | test_precision_at_0_5 | test_recall_at_0_5 | val_optimal_threshold | test_f1_at_val_threshold | test_precision_at_val_threshold | test_recall_at_val_threshold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| majority_baseline | 0.5 | 0.1101 | 0.1101 | 0.0 | 0.0 | 0.0 | 0.1 | 0.0 | 0.0 | 0.0 |
| logistic_regression | 0.9524 | 0.7391 | 0.0505 | 0.6367 | 0.7373 | 0.5603 | 0.31 | 0.6693 | 0.6296 | 0.7144 |
| random_forest | 0.9446 | 0.7094 | 0.055 | 0.5571 | 0.7856 | 0.4316 | 0.28 | 0.6451 | 0.5984 | 0.6996 |
| hist_gradient_boosting | 0.9501 | 0.7309 | 0.0512 | 0.6382 | 0.7236 | 0.5709 | 0.35 | 0.6627 | 0.6383 | 0.689 |
