"""BurnoutIQ monitoring loop: Assess -> Predict -> Simulate -> Intervene -> Verify, plus organisational learning.

The loop is the deliverable model. Feed it three CSV files (employees, monthly records, interventions);
the dashboard only displays what the loop computes.

    from burnoutiq import BurnoutLoop
    loop = BurnoutLoop.from_csv("employees.csv", "monthly.csv", "interventions.csv").fit()
    result = loop.run()            # latest period
    result.employees               # one row per employee: score, flags, forecast, status, outcome
"""
from burnoutiq.loop import BurnoutLoop, LoopResult

__all__ = ["BurnoutLoop", "LoopResult"]
