# BurnoutIQ frontend

The pages follow the loop: **Assess → Predict → Simulate → Intervene → Verify**. The five stages are the navigation, each with a live count. The frontend **computes nothing**: every number comes from the `burnoutiq` package through the API.

## Run

```bash
python dashboard_server.py --port 8501
```

```bash
python frontend/serve.py --port 8600
```

Then open http://127.0.0.1:8600. `serve.py` serves these files, checks uploaded CSVs, and forwards `/api/*` to the dashboard server (`--api` changes its address). On the first visit in a browser session the Data page opens and asks which data to use.

## Month band

The month band is always visible below the navigation. It shows:
- the month being assessed (large), and a selector to look at any earlier month
- which data is active: full demo year, demo month by month, or uploaded files
- **Add next month**: in the month-by-month demo, the next month of the demo panel; for uploaded data, a new `monthly.csv`. The loop reruns, and Data & model shows how the previous month's forecast compared with what came in.

## Pages

Three pages plus one page per person. The person page shows all five loop stages for that person.

| Page | Address | Tiles |
|---|---|---|
| This month (01 Assess) | `#/` | How Assess works · key numbers and survey response · where everyone is in the loop (click a status) · departments ranked, click to see their people · **did support help?** (improved / no change / worsened, per support type, randomised pilot) |
| People | `#/people` | How the forecast and simulation work · **quick tabs**: Everyone, Needs a decision, In support, Follow-up due, Has a result · filters: ID, department, team, burnout level, workload level, flagged; rank by score, predicted rise, forecast, change vs own average or hours. Columns: burnout score, last 6 months sparkline, next-month forecast, workload, status, last support → result |
| Burnout journey (one person) | `#/employees/SYN-00339` | **01 Assess:** where they stand vs department and company, workload gauge, why flagged, what drives the score (7 survey answers) · **02 Predict / 03 Simulate:** months observed + 3 simulated, what-if options · **04 Intervene:** log support (type with its evidence, responsible person, dates, notes); mark it started, completed or stopped · **05 Verify:** each support card with before → after → result |
| Data & model | `#/data` | Start choices · three-file upload with check, then run the loop · can we trust the forecast? (after each added month) · forecast quality · calibration by department |

Logged support is kept in memory and fed into the loop. When the next month is added, Verify compares the person's latest score before the support with the score after it ends. In the demo the later months are pre-generated, so logged support cannot change them; with a company's own data the next survey reflects what actually happened.

Employees are identified by pseudonymous IDs only. Names are deliberately not part of the data; HR keeps the ID-to-name list outside the system.

## API used

| Route | Purpose |
|---|---|
| `GET /api/loop?period=YYYY-MM` | Every stage for one month, plus `periods`, `source`, and `check` (forecast vs actual after a month was added) |
| `GET /api/loop/employees?period=&department=&team=&level=&workload=&status=&flagged=1&q=&sort=&page=&page_size=` | Ranked, filtered employees for one month |
| `GET /api/forecast` | Held-out forecast points and next-month projection |
| `GET /api/search-employee?id=` | One employee: history, forecast, scenarios, support |
| `GET /api/interventions/records` | Support actions (filter, page) |
| `POST /api/loop/demo-start` (`{"until": "YYYY-MM"}` optional) | Demo panel up to one month before its end |
| `POST /api/loop/demo-next` | Add the demo's next month |
| `POST /api/loop/upload` (`employees`, `monthly`, optional `interventions`) | Run the loop on a company's files (in memory only) |
| `POST /api/loop/add-month` (`monthly`, optional `interventions`, `employees`) | Append a later month to the active data |
| `POST /api/loop/support` (`employee_id`, `intervention_type`, `owner`, `start_date`, `planned_end_date`, `notes`) | Log support for one person; the loop is refitted |
| `POST /api/loop/support/status` (`intervention_id`, `status`: started / completed / stopped) | Update logged support |
| `POST /api/loop/reset` | Back to the full demo year |
| `POST /data/check` (served by `serve.py`) | Validate the three CSVs with `burnoutiq.schema.validate` and report the adoption level |

## Layout

- **Large screens** (≥ 1100 × 640 px): each page is one screen of tiles, with no page scrolling. Lists page instead of scroll; list sizes follow the tile height.
- **Shorter laptops** (≤ 820 px tall): same layout, tighter type.
- **Tablets and phones**: tiles stack and the page scrolls; the stage navigation scrolls sideways.

## Design

Calm editorial base (warm paper, thin black rules, large grotesk type) with a heat scale from ash to flame: sage `#8FA39B` → sand → amber `#EBA54A` → ember `#E2621B` → flame `#C42B1C` → burn `#7A1410`. Score colours follow that scale. Motion (embers, breathing orb, cycling word) switches off under `prefers-reduced-motion`.
