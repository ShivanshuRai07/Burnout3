"""Run the BurnoutIQ loop from the command line.

  python -m burnoutiq --employees employees.csv --monthly monthly.csv --interventions interventions.csv \
                      [--period 2025-12] [--out reports/loop] [--model artifacts/burnoutiq_loop.joblib]
  python -m burnoutiq --templates templates/          # write empty input templates
"""
import argparse
import json

from burnoutiq.loop import BurnoutLoop
from burnoutiq.schema import write_templates


def main() -> None:
    ap = argparse.ArgumentParser(prog="burnoutiq")
    ap.add_argument("--employees")
    ap.add_argument("--monthly")
    ap.add_argument("--interventions")
    ap.add_argument("--period", help="YYYY-MM to assess (default: latest)")
    ap.add_argument("--out", default="reports/loop")
    ap.add_argument("--model", help="also save the fitted loop model to this .joblib path")
    ap.add_argument("--templates", help="write empty CSV templates to this folder and exit")
    a = ap.parse_args()

    if a.templates:
        for p in write_templates(a.templates):
            print(p)
        return
    if not (a.employees and a.monthly):
        ap.error("--employees and --monthly are required")

    loop = BurnoutLoop.from_csv(a.employees, a.monthly, a.interventions).fit()
    result = loop.run(a.period)
    result.save(a.out)
    if a.model:
        loop.save_model(a.model)
    print(json.dumps({"company": result.company, "forecast": result.forecast_metrics,
                      "input_issues": result.issues}, indent=2, default=str))
    print(f"\nwritten to {a.out}")


if __name__ == "__main__":
    main()
