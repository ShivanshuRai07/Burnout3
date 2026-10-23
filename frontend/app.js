/* BurnoutIQ frontend. Renders what the loop API returns; it computes no scores, forecasts or effects. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const isNum = (x) => typeof x === "number" && Number.isFinite(x);
  const f1 = (x) => (isNum(x) ? x.toFixed(1) : "—");
  const f0 = (x) => (isNum(x) ? Math.round(x).toLocaleString() : "—");
  const signed = (x) => (isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "±") + Math.abs(x).toFixed(1) : "—");
  const pct = (a, b) => (isNum(a) && b ? `${Math.round((100 * a) / b)}%` : "—");
  const title = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bEap\b/g, "EAP");
  const clean = (s) => (s == null || s === "—" || s === "nan" || s === "" ? null : s);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- heat scale (presentation only) ----------
  const STOPS = [[0, [143, 163, 155]], [30, [217, 185, 140]], [47, [235, 165, 74]], [60, [226, 98, 27]], [78, [196, 43, 28]], [100, [122, 20, 16]]];
  function heat(score, alpha = 1) {
    if (!isNum(score)) return `rgba(179,173,163,${alpha})`;
    const s = Math.max(0, Math.min(100, score));
    let i = 0;
    while (i < STOPS.length - 2 && s > STOPS[i + 1][0]) i++;
    const [a, ca] = STOPS[i], [b, cb] = STOPS[i + 1];
    const t = (s - a) / (b - a);
    const c = ca.map((v, k) => Math.round(v + (cb[k] - v) * t));
    return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
  }

  // levels come from the Assess stage's own rule text; 50 / 65 only if it cannot be read
  let CUT = { high: 50, very: 65 };
  function readCuts(rule) {
    const m = String(rule || "").match(/(\d+)\s*-\s*(\d+)\s*high.*?(\d+)\+/i);
    if (m) CUT = { high: +m[1], very: +m[3] };
  }
  const level = (s) => (!isNum(s) ? "no score" : s >= CUT.very ? "very high" : s >= CUT.high ? "high" : "normal");
  const levelTag = (s) => `<span class="tag ${s >= CUT.high ? "tag--fire" : isNum(s) ? "tag--calm" : "tag--ash"}">${level(s)}</span>`;
  const WL_TAG = { high: "tag--fire", elevated: "tag--amber", normal: "tag--calm", no_data: "tag--ash" };
  const workTag = (w) => `<span class="tag ${WL_TAG[w] || "tag--ash"}">${esc(title(w || "no data"))}</span>`;

  // ---------- api ----------
  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("is-on"), 5000);
  }
  async function api(path, opts) {
    const r = await fetch(path, { headers: { Accept: "application/json" }, ...opts });
    const body = await r.json().catch(() => ({}));
    if (!r.ok || body.ok === false) throw new Error(body.error || `${path} returned ${r.status}`);
    return body;
  }
  const post = (path, body) => api(path, body instanceof FormData ? { method: "POST", body }
    : { method: "POST", body: JSON.stringify(body || {}), headers: { "Content-Type": "application/json", Accept: "application/json" } });

  // ---------- svg + date helpers ----------
  function svgSize(svg) {
    const r = svg.getBoundingClientRect();
    return { w: Math.max(260, Math.round(r.width)), h: Math.max(150, Math.round(r.height)) };
  }
  function nextPeriod(p, k = 1) {
    const [y, m] = p.split("-").map(Number);
    const d = new Date(Date.UTC(y, m - 1 + k, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  }
  const monthLabel = (p) => new Date(p + "-01T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" });
  const monthLong = (p) => (p ? new Date(p + "-01T00:00:00Z").toLocaleString("en", { month: "long", year: "numeric", timeZone: "UTC" }) : "—");
  function linePath(pts) {
    let d = "", pen = false;
    for (const p of pts) {
      if (!p) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
      pen = true;
    }
    return d;
  }
  function watch(svg, draw) {
    let raf;
    new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); }).observe(svg);
  }
  // rows that fit a tile body, so pages never scroll on large screens
  function rowsThatFit(body, rowH = 33, fallback = 10) {
    const h = body.getBoundingClientRect().height;
    return h > 100 ? Math.max(3, Math.floor((h - 36) / rowH)) : fallback;
  }
  const stageOf = (id) => (S.loop?.stages || []).find((s) => s.id === id) || {};

  // ---------- state ----------
  const S = {
    loop: null, fc: null, person: null, personRow: null, scenario: "no_change", rci: null,
    act: { status: "", dept: "", page: 0 },
    people: { q: "", department: "", team: "", level: "", workload: "", status: "", flagged: "", quadrant: "", sort: "urgent", page: 0 },
  };

  // ================= header: stage counts, month band =================
  function stageCount(id) {
    const c = S.loop.company, st = c.status || {}, t = S.loop.triage || {};
    const sum = (...k) => k.reduce((a, x) => a + (st[x] || 0), 0);
    return {
      assess: c.employees_scored, people: c.n_flagged,
      intervene: sum("flagged", "support_planned", "in_support"), verify: sum("follow_up_due", "follow_up_overdue"),
    }[id];
  }
  function renderHeader() {
    const c = S.loop.company;
    $("#meta").classList.remove("is-offline");
    $("#meta").innerHTML = `<span class="pulse"></span><span class="bar__metatext">${f0(c.employees_scored)} of ${f0(c.employees_with_record)} answered</span>`;
    $$("[data-count]").forEach((n) => { const v = stageCount(n.dataset.count); n.textContent = isNum(v) ? f0(v) : ""; });
    const assess = stageOf("assess");
    if (assess.rule) readCuts(assess.rule);
  }

  function renderMonth() {
    const src = S.loop.source || { kind: "demo" }, periods = S.loop.periods || [];
    const latest = periods[periods.length - 1];
    $("#month-label").textContent = monthLong(S.loop.period);
    $("#month-select").innerHTML = [...periods].reverse().map((p) => `<option value="${p}" ${p === S.loop.period ? "selected" : ""}>${monthLong(p)}${p === latest ? " (latest)" : ""}</option>`).join("");
    const kind = { demo: "Demo data · full year", demo_live: "Demo data · month by month", upload: esc(src.name || "Uploaded data") }[src.kind] || "Data";
    $("#month-src").innerHTML = `<b>${kind}</b><span>${esc(monthLong(periods[0]))} – ${esc(monthLong(latest))}${src.months_added ? ` · ${src.months_added} month${src.months_added > 1 ? "s" : ""} added` : ""}</span>`;
    const btns = [];
    if (src.kind === "demo_live" && src.next_period) btns.push(
      `<a class="btn btn--small btn--ghost" href="${demoFile(src.next_period)}" download>Get ${esc(monthLong(src.next_period))} file</a>`,
      `<button type="button" class="btn btn--small" data-act="file">Upload ${esc(monthLong(src.next_period))} data</button>`);
    if (src.kind === "upload") btns.push(`<button type="button" class="btn btn--small" data-act="file">Add next month's file</button>`);
    $("#month-actions").innerHTML = btns.join("");
    $("#month").classList.toggle("is-past", S.loop.period !== latest);
  }

  async function monthAction(act) {
    try {
      if (act === "next") {
        const before = S.loop.periods.slice(-1)[0];
        await post("/api/loop/demo-next");
        await loadData();
        toast(`${monthLong(nextPeriod(before))} added. Here is how last month's forecast did.`);
        location.hash = "#/data";
      } else if (act === "live") {
        await post("/api/loop/demo-start", {});
        sessionStorage.setItem("biq-started", "1");
        await loadData();
        toast(`Demo runs up to ${monthLong(S.loop.period)}. Add the next month from the month bar.`);
        location.hash = "#/";
      } else if (act === "full" || act === "reset") {
        await post("/api/loop/reset");
        sessionStorage.setItem("biq-started", "1");
        await loadData();
        if (act === "full") location.hash = "#/";
      } else if (act === "file") {
        $("#addmonth-file").click();
      } else if (act === "upload") {
        if (location.hash !== "#/data") { location.hash = "#/data"; await new Promise((r) => setTimeout(r, 60)); }
        $("#upload").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
        $("#upload .drop").classList.add("is-drag");
        setTimeout(() => $("#upload .drop").classList.remove("is-drag"), 1200);
      }
    } catch (e) { toast(e.message); }
  }

  // ================= "how this stage works": algorithm + live numbers =================
  function howLines(id) {
    const c = S.loop.company, m = S.loop.forecast_metrics || {}, mm = m.model || {}, pm = m.persistence || {};
    const ref = c.reference || {};
    switch (id) {
      case "assess": return [
        ["Measure", `CBI work survey: 7 questions → 0–100 (α ${isNum(c.cbi_reliability_alpha) ? c.cbi_reliability_alpha.toFixed(2) : "—"})`],
        ["Levels", `under ${CUT.high} normal · ${CUT.high}–${CUT.very - 1} high · ${CUT.very}+ very high · not a diagnosis`],
        ["Flags", "score ≥ 50 · far above own department · +10 vs own last 3 months · forecast rising"],
        ["Reference", `PUMA workers: mean ${f1(ref.mean)}, ${f1(ref.pct_high)}% high`],
      ];
      case "predict": return [
        ["Model", "Ridge regression: this month's score + work data → next month"],
        ["Tested", `on ${f0(m.test_employees)} employees never seen in training`],
        ["Accuracy", `average error ${f1(mm.mae)} points vs ${f1(pm.mae)} for "same as last month"`],
        ["Range", `95% range ±${f1(m.interval_95_halfwidth)}, held ${isNum(m.interval_95_coverage) ? (100 * m.interval_95_coverage).toFixed(1) : "—"}% of held-out cases`],
      ];
      case "people": return [
        ["Predict", `Ridge regression, this month → next month · average error ${f1(mm.mae)} vs ${f1(pm.mae)} for "same as last month" · 95% range ±${f1(m.interval_95_halfwidth)}`],
        ["Simulate", "open a person: 500 possible paths 3 months ahead, with no change, overtime −5 h, or support with reliable evidence"],
        ["Used by", "HR or a manager deciding on support for one person; it shows options, a person decides"],
      ];
      case "intervene": return [
        ["Rule", "the model only flags and suggests; a named person decides and logs the support"],
        ["Tracked", "type, start, planned end · planned → in progress → completed or stopped"],
        ["Never", "used for performance reviews, pay, discipline or hiring"],
      ];
      case "verify": return [
        ["Change", "score when support ends minus score at referral"],
        ["Classes", `≤ −5 improved · ±5 no change · ≥ +5 worsened · reliable beyond ±${f1(c.reliable_change_threshold)}`],
        ["Learn", "vs similar people without support; the randomised pilot is the strongest evidence"],
      ];
      default: return [];
    }
  }
  function renderHow() {
    $$("[data-how]").forEach((tile) => {
      const id = tile.dataset.how;
      const st = id === "people" ? { name: "Predict · Simulate", what: "Forecast next month for everyone; simulate options for one person" } : stageOf(id);
      tile.innerHTML = `<h2 class="tile__title"><span>how ${esc(st.name || id)} works</span>${esc(st.what || "")}</h2>
        <dl class="how tile__body">${howLines(id).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}</dl>`;
    });
  }

  // ================= 01 ASSESS =================
  // share of employees who took this month's survey: filled part = took it, empty part = did not
  const surveyBar = (rate) => (isNum(rate)
    ? `<span class="surveybar" title="${Math.round(rate * 100)}% took the survey"><span style="width:${Math.min(100, rate * 100)}%"></span></span>`
    : "");

  // ring for one share (0-1): the filled arc is the share, the label sits in the middle
  function ring(share, label, color = "var(--ink-2)") {
    const r = 42, C = 2 * Math.PI * r, f = isNum(share) ? Math.max(0, Math.min(1, share)) : 0;
    return `<svg class="kring" viewBox="0 0 100 100" role="img" aria-label="${esc(label)}">
      <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--stone)" stroke-width="11"/>
      <circle cx="50" cy="50" r="${r}" fill="none" stroke="${color}" stroke-width="11" stroke-linecap="round"
        stroke-dasharray="${(C * f).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 50 50)"/>
      <text x="50" y="50" text-anchor="middle" dominant-baseline="central">${esc(label)}</text></svg>`;
  }
  // a value and the norm on one short scale (0 to a bit past the larger of the two)
  function normScale(value, norm, unit = "%") {
    if (!isNum(value)) return "";
    const max = Math.max(value, norm || 0) * 1.35 || 1, x = (v) => `${Math.min(100, (100 * v) / max)}%`;
    return `<span class="nscale"><span class="nscale__track"></span>
      ${isNum(norm) ? `<i class="nscale__norm" style="left:${x(norm)}" title="norm ${f1(norm)}${unit}"><em>norm ${f1(norm)}${unit}</em></i>` : ""}
      <b class="nscale__dot ${isNum(norm) && value > norm ? "is-hot" : ""}" style="left:${x(value)}"></b></span>`;
  }

  function renderKpis() {
    const c = S.loop.company, ref = c.reference || {}, np = S.fc?.next_projection || {};
    const took = isNum(c.response_rate) ? Math.round(c.response_rate * 100) : null;
    const now = c.mean_score, next = np.projected_mean_cbi;
    const rise = isNum(now) && isNum(next) ? next - now : null;
    // waffle: 100 squares, one per 1% of the people who took the survey; flagged squares are ember
    const flaggedShare = c.employees_scored ? c.n_flagged / c.employees_scored : null;
    const cells = isNum(flaggedShare) ? Math.round(flaggedShare * 100) : 0;
    const waffle = `<span class="waffle" role="img" aria-label="${cells} in 100 flagged">${Array.from({ length: 100 }, (_, i) => `<i class="${i < cells ? "on" : ""}"></i>`).join("")}</span>`;
    $("#kpis").innerHTML = `
      <div class="kpi kpi--ring"><dt>Took this month's survey</dt>
        <dd>${ring(c.response_rate, took == null ? "—" : `${took}%`)}<small>${f0(c.employees_scored)} of ${f0(c.employees_with_record)} employees. The rest are not in the burnout numbers.</small></dd></div>
      <div class="kpi"><dt>Scoring high</dt>
        <dd><span class="kpi__v">${f1(c.pct_high)}%</span>${normScale(c.pct_high, ref.pct_high)}<small>of those who took the survey · average score ${f1(c.mean_score)}</small></dd></div>
      <div class="kpi"><dt>Next month</dt>
        <dd><span class="kpi__v">${f1(now)} <span class="kpi__arrow ${rise > 0 ? "is-up" : rise < 0 ? "is-down" : ""}">→</span> ${f1(next)}</span>
          <span class="nowstrip"><span class="nowstrip__track"></span>${isNum(now) ? `<i style="left:${now}%" title="now ${f1(now)}"></i>` : ""}${isNum(next) ? `<i class="is-next" style="left:${next}%" title="next ${f1(next)}"></i>` : ""}</span>
          <small>average score now → company forecast for ${esc(monthLong(np.forecast_period))} · 0 calm · 100 burnt out</small></dd></div>
      <div class="kpi kpi--waffle"><dt>Flagged now</dt>
        <dd><span class="kpi__row">${waffle}<span class="kpi__v">${f0(c.n_flagged)}</span></span><small>about ${cells} in every 100 who took the survey · flagged for a check-in</small></dd></div>`;
  }

  const STATUS_COLOR = {
    monitoring: "#8FA39B", outcome_improved: "#5E8C7B", outcome_no_change: "#B3ADA3", outcome_worsened: "#7A1410",
    flagged: "#EBA54A", support_planned: "#D9B98C", in_support: "#E2621B", follow_up_due: "#F0B46A", follow_up_overdue: "#C42B1C",
  };
  // the loop's nine statuses, grouped into the four a manager acts on
  const STATUS_GROUPS = [
    { label: "Watching", hint: "no flag, no support", color: "#8FA39B", keys: ["monitoring"] },
    { label: "Needs action", hint: "flagged, planned or follow-up due", color: "#EBA54A", keys: ["flagged", "support_planned", "follow_up_due", "follow_up_overdue"] },
    { label: "In support", hint: "support under way", color: "#E2621B", keys: ["in_support"] },
    { label: "Has a result", hint: "improved, no change or worse", color: "#5E8C7B", keys: ["outcome_improved", "outcome_no_change", "outcome_worsened"] },
  ];

  const appCharts = {};
  function destroyAppChart(id) {
    if (appCharts[id]) {
      try { appCharts[id].destroy(); } catch (e) {}
      delete appCharts[id];
    }
  }

  const BREAKDOWN_DATA = {
    work_mode: {
      name: "Work Mode",
      categories: ["Onsite", "Hybrid", "Remote"],
      counts: [241, 413, 346],
      scores: [4.07, 3.89, 3.89],
      elevated: [22.8, 21.3, 22.5],
      risks: ["Elevated", "Elevated", "Elevated"]
    },
    duration: {
      name: "Work Duration",
      categories: ["0–1 Year", "1–3 Years", "3+ Years"],
      counts: [198, 462, 340],
      scores: [3.72, 3.94, 4.05],
      elevated: [18.2, 22.1, 24.1],
      risks: ["Moderate", "Elevated", "Elevated"]
    },
    gender: {
      name: "Gender",
      categories: ["Female", "Male"],
      counts: [485, 515],
      scores: [3.91, 3.95],
      elevated: [21.6, 22.5],
      risks: ["Elevated", "Elevated"]
    },
    location: {
      name: "Geography",
      categories: ["Bangalore", "Hyderabad", "Pune", "Delhi NCR"],
      counts: [380, 290, 185, 145],
      scores: [3.98, 3.91, 3.88, 3.96],
      elevated: [23.2, 21.4, 20.5, 22.8],
      risks: ["Elevated", "Elevated", "Elevated", "Elevated"]
    }
  };

  let activeBreakdownCat = "work_mode";

  function renderBreakdownSection(catKey) {
    activeBreakdownCat = catKey || activeBreakdownCat;
    const data = BREAKDOWN_DATA[activeBreakdownCat] || BREAKDOWN_DATA.work_mode;

    const colHdr = document.getElementById("breakdown-col-header");
    if (colHdr) colHdr.textContent = data.name;

    const tbody = document.getElementById("breakdown-tbody");
    if (tbody) {
      tbody.innerHTML = data.categories.map((cat, i) => `
        <tr>
          <td style="font-weight:600;color:var(--navy)">${cat}</td>
          <td>${data.counts[i]}</td>
          <td><strong>${data.scores[i].toFixed(2)}</strong><span style="font-size:11px;color:var(--ink-2)">/10</span></td>
          <td>${data.elevated[i].toFixed(1)}%</td>
          <td><span class="risk-badge ${data.risks[i] === 'Elevated' ? 'risk-badge--elevated' : 'risk-badge--moderate'}">${data.risks[i]}</span></td>
        </tr>
      `).join("");
    }

    const canvas = document.getElementById("chart-breakdown");
    if (canvas && typeof Chart !== "undefined") {
      destroyAppChart("breakdown");
      appCharts["breakdown"] = new Chart(canvas, {
        type: "bar",
        data: {
          labels: data.categories,
          datasets: [
            {
              label: "Avg Burnout Score (0–10)",
              data: data.scores,
              backgroundColor: "#1a6fc4",
              borderRadius: 3,
              yAxisID: "y"
            },
            {
              label: "Elevated Review Rate (%)",
              data: data.elevated,
              backgroundColor: "#ea580c",
              borderRadius: 3,
              yAxisID: "y1"
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { font: { family: "'Inter', sans-serif", size: 11 } } },
            y: { min: 0, max: 8, grid: { color: "rgba(0,0,0,0.06)" }, ticks: { font: { family: "'Inter', sans-serif", size: 10 } } },
            y1: { min: 0, max: 100, position: "right", grid: { display: false }, ticks: { callback: v => v + "%", font: { size: 10 } } }
          },
          plugins: {
            legend: { position: "bottom", labels: { boxWidth: 10, padding: 8, font: { family: "'Inter', sans-serif", size: 11 } } }
          }
        }
      });
    }
  }

  function renderAnalyticsUI() {
    // 1. Top 4 Metric Cards
    const kpiScored = document.getElementById("kpi-scored");
    if (kpiScored) kpiScored.textContent = "1,000";
    const kpiAvg = document.getElementById("kpi-avg-score");
    if (kpiAvg) kpiAvg.innerHTML = `3.93<span class="stat-scale">/10</span>`;
    const kpiElevated = document.getElementById("kpi-elevated-rate");
    if (kpiElevated) kpiElevated.textContent = "22.1%";
    const kpiProb = document.getElementById("kpi-probability");
    if (kpiProb) kpiProb.textContent = "59.1%";

    // 2. Risk Band Boxes & Donut Chart
    const bLow = document.getElementById("band-low-val");
    if (bLow) bLow.textContent = "35";
    const bMod = document.getElementById("band-mod-val");
    if (bMod) bMod.textContent = "744";
    const bEle = document.getElementById("band-ele-val");
    if (bEle) bEle.textContent = "221";

    const donutCanvas = document.getElementById("chart-risk-donut");
    if (donutCanvas && typeof Chart !== "undefined") {
      destroyAppChart("donut");
      appCharts["donut"] = new Chart(donutCanvas, {
        type: "doughnut",
        data: {
          labels: ["Low Risk (< 2.5)", "Moderate Risk (2.5–3.7)", "Elevated Risk (≥ 3.7)"],
          datasets: [{
            data: [35, 744, 221],
            backgroundColor: ["#059669", "#d97706", "#dc2626"],
            borderWidth: 2,
            borderColor: "#fff"
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "65%",
          plugins: {
            legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { family: "'Inter', sans-serif", size: 11 } } }
          }
        }
      });
    }

    // 3. Roles Bar Chart
    const rolesCanvas = document.getElementById("chart-role-bars");
    if (rolesCanvas && typeof Chart !== "undefined") {
      destroyAppChart("roles");
      const roles = ["Backend Developer", "Data Scientist", "ML Engineer", "Frontend Developer", "DevOps", "QA Engineer", "Product Manager", "Software Engineer"];
      const scores = [4.01, 4.00, 3.98, 3.95, 3.94, 3.90, 3.86, 3.85];
      appCharts["roles"] = new Chart(rolesCanvas, {
        type: "bar",
        data: {
          labels: roles,
          datasets: [{
            label: "Avg Burnout Score",
            data: scores,
            backgroundColor: "#1a6fc4",
            borderRadius: 3
          }]
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { min: 0, max: 10, grid: { color: "rgba(0,0,0,0.06)" }, ticks: { font: { family: "'Inter', sans-serif", size: 10 } } },
            y: { grid: { display: false }, ticks: { font: { family: "'Inter', sans-serif", size: 11 } } }
          },
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => ` Score: ${ctx.parsed.x} / 10` } }
          }
        }
      });
    }

    // 4. Elevated Review Rate by Role Table
    const roleTbody = document.getElementById("role-table-tbody");
    if (roleTbody) {
      const rows = [
        { role: "Backend Developer", count: 122, score: "4.01/10", elevated: "25.4%", d1: "Extended Hours (+14.3h/wk)", d2: "Overtime Load (+1.7h/wk)", risk: "Elevated" },
        { role: "Data Scientist", count: 139, score: "4.00/10", elevated: "23.7%", d1: "Extended Hours (+14.6h/wk)", d2: "Overtime Load (+2.0h/wk)", risk: "Elevated" },
        { role: "ML Engineer", count: 126, score: "3.98/10", elevated: "25.4%", d1: "Extended Hours (+13.4h/wk)", d2: "Overtime Load (+2.3h/wk)", risk: "Elevated" },
        { role: "Frontend Developer", count: 129, score: "3.95/10", elevated: "21.7%", d1: "Extended Hours (+14.0h/wk)", d2: "Overtime Load (+1.9h/wk)", risk: "Elevated" },
        { role: "DevOps", count: 114, score: "3.94/10", elevated: "20.2%", d1: "Extended Hours (+13.4h/wk)", d2: "Overtime Load (+2.8h/wk)", risk: "Elevated" },
        { role: "QA Engineer", count: 61, score: "3.90/10", elevated: "14.8%", d1: "Extended Hours (+13.2h/wk)", d2: "Overtime Load (+1.6h/wk)", risk: "Moderate" },
        { role: "Product Manager", count: 75, score: "3.86/10", elevated: "22.7%", d1: "Extended Hours (+13.5h/wk)", d2: "Overtime Load (+1.7h/wk)", risk: "Elevated" },
        { role: "Software Engineer", count: 234, score: "3.85/10", elevated: "20.5%", d1: "Extended Hours (+13.1h/wk)", d2: "Overtime Load (+1.8h/wk)", risk: "Elevated" },
      ];
      roleTbody.innerHTML = rows.map(r => `
        <tr>
          <td style="font-weight:600;color:var(--navy)">${r.role}</td>
          <td>${r.count}</td>
          <td><strong>${r.score}</strong></td>
          <td>${r.elevated}</td>
          <td>
            <span class="driver-pill"><span>⚡</span> ${r.d1}</span>
            <span class="driver-pill"><span>⚡</span> ${r.d2}</span>
          </td>
          <td><span class="risk-badge ${r.risk === 'Elevated' ? 'risk-badge--elevated' : 'risk-badge--moderate'}">${r.risk}</span></td>
        </tr>
      `).join("");
    }

    // 5. Demographic Breakdown
    renderBreakdownSection(activeBreakdownCat);

    // Wire up tab strip buttons
    const tabStrip = document.getElementById("breakdown-tab-strip");
    if (tabStrip && !tabStrip.dataset.wired) {
      tabStrip.dataset.wired = "1";
      tabStrip.addEventListener("click", e => {
        const btn = e.target.closest(".tab-btn");
        if (!btn) return;
        tabStrip.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        renderBreakdownSection(btn.dataset.cat);
      });
    }
  }

  // Global Simulator Dialog handlers
  window.openSimModal = function() {
    const m = document.getElementById("sim-modal");
    if (m && m.showModal) m.showModal();
  };
  window.closeSimModal = function() {
    const m = document.getElementById("sim-modal");
    if (m && m.close) m.close();
  };
  window.onSimInput = function() {
    const hours = parseFloat(document.getElementById("sim-hours")?.value || 45);
    const ot = parseFloat(document.getElementById("sim-ot")?.value || 6);
    const meet = parseFloat(document.getElementById("sim-meet")?.value || 4);
    const stress = parseFloat(document.getElementById("sim-stress")?.value || 6.5);

    if (document.getElementById("disp-sim-hours")) document.getElementById("disp-sim-hours").textContent = hours + "h";
    if (document.getElementById("disp-sim-ot")) document.getElementById("disp-sim-ot").textContent = ot + "h";
    if (document.getElementById("disp-sim-meet")) document.getElementById("disp-sim-meet").textContent = meet.toFixed(1);
    if (document.getElementById("disp-sim-stress")) document.getElementById("disp-sim-stress").textContent = stress.toFixed(1);

    const score = Math.min(10, Math.max(0, 1.2 + (hours - 35) * 0.08 + ot * 0.14 + meet * 0.18 + stress * 0.22)).toFixed(2);
    const prob = Math.min(99, Math.max(5, Math.round(score * 15))).toFixed(1);
    const isElevated = score >= 3.7;
    const isMod = score >= 2.5 && score < 3.7;

    const scoreEl = document.getElementById("sim-res-score");
    if (scoreEl) scoreEl.innerHTML = `${score} <span style="font-size:13px;color:var(--ink-2);font-weight:400">/ 10</span>`;
    const bandEl = document.getElementById("sim-res-band");
    if (bandEl) {
      bandEl.className = `risk-badge ${isElevated ? "risk-badge--elevated" : isMod ? "risk-badge--moderate" : "risk-badge--low"}`;
      bandEl.textContent = `${isElevated ? "Elevated" : isMod ? "Moderate" : "Low"} Risk (${prob}%)`;
    }
  };
  window.resetSimModal = function() {
    if (document.getElementById("sim-hours")) document.getElementById("sim-hours").value = 45;
    if (document.getElementById("sim-ot")) document.getElementById("sim-ot").value = 6;
    if (document.getElementById("sim-meet")) document.getElementById("sim-meet").value = 4;
    if (document.getElementById("sim-stress")) document.getElementById("sim-stress").value = 6.5;
    window.onSimInput();
  };

  function renderAssess() {
    renderAnalyticsUI();
    const c = S.loop.company, st = c.status || {};
    const groups = STATUS_GROUPS.map((g) => ({ ...g, n: g.keys.reduce((a, k) => a + (st[k] || 0), 0) }));
    const total = groups.reduce((a, g) => a + g.n, 0);
    const r = 40, C = 2 * Math.PI * r;
    let off = 0;
    const arcs = groups.map((g) => {
      const len = total ? (C * g.n) / total : 0;
      const arc = `<circle cx="50" cy="50" r="${r}" fill="none" stroke="${g.color}" stroke-width="16" stroke-dasharray="${len.toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 50 50)"><title>${g.label}: ${g.n}</title></circle>`;
      off += len;
      return arc;
    }).join("");
    $("#statusdonut").innerHTML = `
      <svg class="donut" viewBox="0 0 100 100" role="img" aria-label="Where everyone is in the loop">${arcs}
        <text x="50" y="47" text-anchor="middle" class="donut__n">${f0(total)}</text><text x="50" y="60" text-anchor="middle" class="donut__l">employees</text></svg>
      <ul class="donutkey">${groups.map((g) => `<li data-status="${g.keys.join(",")}" title="${esc(g.hint)} · click to see them"><i style="background:${g.color}"></i><span>${g.label}</span><b>${f0(g.n)}</b></li>`).join("")}</ul>`;
    $$("#statusdonut li").forEach((li) => li.addEventListener("click", () => (location.hash = `#/people?status=${li.dataset.status}`)));

    // dot plot: % scoring high per department against the norm line; dot size = people who took the survey
    const ref = c.reference?.pct_high;
    const divs = [...(S.loop.divisions || [])].sort((a, b) => (b.pct_high ?? -1) - (a.pct_high ?? -1));
    const vals = [...divs.map((d) => d.pct_high), c.pct_high, ref].filter(isNum);
    const max = Math.max(...vals, 1) * 1.15;
    const nMax = Math.max(...divs.map((d) => d.n_scored || 0), 1);
    const X = (v) => `${(100 * v) / max}%`;
    const normLine = isNum(ref) ? `<i class="dp__norm" style="left:${X(ref)}"></i>` : "";
    const row = (d, company) => {
      if (d.suppressed) return `<div class="dp__row"><span class="dp__name">${esc(d.department)}</span><span class="dp__survey">—</span><span class="dp__plot">${normLine}<span class="note">hidden: under 5 took the survey</span></span><span class="dp__v">—</span></div>`;
      const v = d.pct_high, hot = isNum(ref) && v > ref;
      const size = company ? 12 : 8 + 12 * Math.sqrt((d.n_scored || 0) / nMax);
      return `<div class="dp__row ${company ? "dp__row--total" : ""}" ${company ? "" : `data-dept="${esc(d.department)}"`} title="${esc(d.department)}: ${f1(v)}% high · average ${f1(d.mean_score)} · ${f0(d.n_scored)} took the survey${isNum(d.median_hours) ? ` · median ${f1(d.median_hours)} h/week` : ""}">
        <span class="dp__name">${esc(d.department)}${d.systemic ? ` <span class="dp__flag" title="more high scores than the norm explains">⚑</span>` : ""}</span>
        <span class="dp__survey">${isNum(d.survey_rate) ? Math.round(d.survey_rate * 100) + "%" : "—"}</span>
        <span class="dp__plot">${normLine}<b class="dp__dot ${company ? "is-company" : hot ? "is-hot" : ""}" style="left:${X(v)};width:${size}px;height:${size}px"></b></span>
        <span class="dp__v">${f1(v)}%</span>
      </div>`;
    };
    $("#divisions").innerHTML = `
      <div class="dp__row dp__head"><span>Department</span><span class="dp__survey">Survey</span><span class="dp__plot">${isNum(ref) ? `<em class="dp__normlabel" style="left:${X(ref)}">norm ${f1(ref)}%</em>` : ""}</span><span class="dp__v">% high</span></div>
      ${divs.map((d) => row(d, false)).join("")}
      ${row({ department: "Company", pct_high: c.pct_high, mean_score: c.mean_score, n_scored: c.employees_scored, survey_rate: c.response_rate }, true)}
      <p class="dp__key"><b class="dp__dot is-hot"></b> above the norm <b class="dp__dot"></b> at or below · bigger dot = more people · ⚑ more high scores than chance</p>`;
    $$("#divisions .dp__row[data-dept]").forEach((rw) => rw.addEventListener("click", () => (location.hash = `#/people?department=${encodeURIComponent(rw.dataset.dept)}`)));
  }

  async function peopleQuery(params) {
    return api(`/api/loop/employees?${new URLSearchParams({ period: S.loop.period, ...params })}`);
  }
  // Verify + Learn in one tile: what happened after support, per support type, and the randomised pilot
  // (i) buttons open a floating card next to the button; any click elsewhere, Escape or scrolling closes it.
  // The card's text lives in a hidden element (aria-controls) inside the panel.
  function wireHelpInfo() {
    const card = document.createElement("div");
    card.className = "floatcard";
    card.setAttribute("role", "dialog");
    card.hidden = true;
    document.body.append(card);
    let owner = null;
    const close = () => { card.hidden = true; owner?.setAttribute("aria-expanded", "false"); owner = null; };
    const open = (btn) => {
      card.innerHTML = $(`#${btn.getAttribute("aria-controls")}`).innerHTML;
      card.hidden = false;
      const r = btn.getBoundingClientRect(), w = card.offsetWidth, h = card.offsetHeight;
      const left = Math.max(12, Math.min(r.right - w, innerWidth - w - 12));
      const top = r.top - h - 10 > 12 ? r.top - h - 10 : Math.min(r.bottom + 10, innerHeight - h - 12);
      card.style.left = `${left}px`;
      card.style.top = `${top}px`;
      owner = btn;
      btn.setAttribute("aria-expanded", "true");
    };
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".infobtn");
      if (btn) { e.stopPropagation(); return owner === btn ? close() : open(btn); }
      if (!card.hidden && !card.contains(e.target)) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    addEventListener("scroll", close, true);
    addEventListener("resize", close);
    addEventListener("hashchange", close);
  }
  function renderHelp() {
    const imp = S.loop.impact || {}, o = imp.outcomes || {}, iv = S.loop.company?.interventions || {};
    const n = (o.improved || 0) + (o.no_change || 0) + (o.worsened || 0);
    const seg = (v, c, label) => (v ? `<span style="flex-grow:${v};background:${c}" title="${label}: ${v}"></span>` : "");
    // forest plot: each support type's change compared with similar people (dot + 95% interval);
    // left of zero = lower burnout than without support. The randomised pilot is the only true effect.
    const pl = S.loop.randomised_pilot;
    const items = (S.loop.effects || []).filter((e) => isNum(e.adjusted_difference)).map((e) => ({
      name: title(e.intervention_type), d: e.adjusted_difference, lo: e.adjusted_ci_low, hi: e.adjusted_ci_high,
      note: `${e.evidence} · ${f0(e.n_followed_up)} followed up`, sim: isNum(e.simulation_effect),
    }));
    if (pl && isNum(pl.difference)) items.push({ name: title(pl.intervention_type), sub: `${f0(pl.n_treatment)} by lottery vs ${f0(pl.n_control)} waitlisted`, d: pl.difference, lo: pl.ci_low, hi: pl.ci_high,
      note: `randomised: ${f0(pl.n_treatment)} supported vs ${f0(pl.n_control)} on a waitlist`, pilot: true });
    const span = Math.max(5, ...items.flatMap((i) => [Math.abs(i.lo), Math.abs(i.hi)]).filter(isNum)) * 1.1;
    const X = (v) => `${50 + (50 * v) / span}%`;
    const forest = items.map((i, k) => {
      const clear = isNum(i.hi) && i.hi < 0;  // whole interval below zero: support lowered burnout
      const group = k === 0 ? `<p class="fp__group">compared with similar people · can be biased</p>`
        : i.pilot ? `<p class="fp__group fp__group--fair">★ fair test · support given by lottery · trust this one
            <button type="button" class="infobtn" data-info="fair" aria-expanded="false" aria-controls="fair-info" title="What is a fair test?">i</button></p>
          <div class="infopop" id="fair-info" hidden>
            <b>What is a fair test?</b>
            <p>A group of people who could all have had a schedule adjustment were split by lottery: <b>${f0(pl.n_treatment)}</b> got it, <b>${f0(pl.n_control)}</b> went on a waitlist instead.</p>
            <p>Because chance decided, both groups started out alike. So the difference afterwards, <b>${signed(pl.difference)} points</b> (likely between ${signed(pl.ci_low)} and ${signed(pl.ci_high)}), comes from the support itself.</p>
            <p>The rows above can't do that: managers give support to people who are struggling, so those people are compared with others who were doing better.</p>
          </div>` : "";
      return `${group}<div class="fp__row ${i.pilot ? "fp__row--pilot" : ""}" title="${esc(i.note)}">
        <span class="fp__name">${esc(i.name)}${i.sub ? `<small>${esc(i.sub)}</small>` : ""}</span>
        <span class="fp__plot"><i class="fp__zero"></i>${isNum(i.lo) && isNum(i.hi) ? `<i class="fp__ci" style="left:${X(i.lo)};right:${100 - parseFloat(X(i.hi))}%"></i>` : ""}<b class="fp__dot ${clear ? "is-clear" : ""}" style="left:${X(i.d)}"></b></span>
        <span class="fp__v">${signed(i.d)}</span></div>`;
    }).join("");
    $("#help").innerHTML = `
      <div class="helpbar">${seg(o.improved, "#5E8C7B", "improved")}${seg(o.no_change, "#B3ADA3", "no change")}${seg(o.worsened, "#C42B1C", "worsened")}</div>
      <ul class="helplegend"><li><i style="background:#5E8C7B"></i>improved <b>${f0(o.improved)}</b></li><li><i style="background:#B3ADA3"></i>no change <b>${f0(o.no_change)}</b></li><li><i style="background:#C42B1C"></i>worsened <b>${f0(o.worsened)}</b></li></ul>
      <p class="tile__fine">${f0(iv.followed_up)} of ${f0(iv.follow_up_due_by_now)} follow-ups in.</p>
      <div class="fp">
        <div class="fp__row fp__head"><span class="fp__name">Support</span><span class="fp__plot"><em class="fp__ax fp__ax--l">← less burnout</em><em class="fp__ax fp__ax--r">more →</em></span><span class="fp__v">pts</span></div>
        ${forest}
      </div>
      <p class="tile__fine fp__key"><span><b class="fp__dot"></b> change vs no support</span><span><i class="fp__keyline"></i> likely range</span><span><b class="fp__dot is-clear"></b> clearly less burnout</span></p>`;
  }

  // ================= forecast check (Data & model page) =================
  // Data page: what is loaded (by month) and how complete each field is
  const FIELD_LABEL = {
    work_hours_per_week: "Hours per week", overtime_hours_per_week: "Overtime", meeting_hours_per_week: "Meeting hours",
    after_hours_messages_per_week: "After-hours messages", pto_days_taken: "Leave taken", perceived_workload_1_5: "Workload (1–5)",
    manager_support_1_5: "Manager support (1–5)", job_control_1_5: "Control (1–5)", work_life_balance_1_5: "Work-life balance (1–5)",
    job_satisfaction_1_5: "Satisfaction (1–5)", stress_level_0_10: "Stress (0–10)", sleep_hours_avg: "Sleep hours",
  };
  async function renderDataSummary() {
    if (!S.loop || locked()) return;
    if (!S.dsum) { try { S.dsum = await api("/api/loop/data"); } catch { return; } }
    const d = S.dsum, months = d.months || [];
    const kind = { demo: "Demo data · full year", demo_live: "Demo data · month by month", upload: d.source?.name || "Uploaded data" }[d.source?.kind] || "Data";
    $("#loaded-title").textContent = kind;
    $("#loadkpis").innerHTML = [
      [f0(d.employees), "people"], [f0(d.departments), "departments"], [f0(d.teams), "teams"],
      [f0(months.length), "months"], [f0(d.answered), "surveys answered"], [f0(d.interventions), "support actions"],
    ].map(([v, k]) => `<div><dd>${v}</dd><dt>${k}</dt></div>`).join("");
    const top = Math.max(...months.map((m) => m.records), 1);
    const short = (p) => new Date(p + "-01T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" });
    const nxt = nextPeriod(months.length ? months[months.length - 1].period : S.loop.period);
    $("#mbars").innerHTML = months.map((m, i) => `<div class="mbar" style="--i:${i}" title="${monthLong(m.period)}: ${f0(m.answered)} of ${f0(m.records)} answered (${Math.round(100 * m.response_rate)}%) · average score ${f1(m.mean_score)}">
        <span class="mbar__pct">${Math.round(100 * m.response_rate)}%</span>
        <i style="height:${(100 * m.records) / top}%"><b style="height:${100 * m.response_rate}%"></b></i>
        <small>${short(m.period)}</small></div>`).join("") +
      `<div class="mbar mbar--next" title="Next expected: ${monthLong(nxt)}"><span class="mbar__pct">next</span><i style="height:100%"></i><small>${short(nxt)}</small></div>`;
    const bar = (f) => {
      const v = f.complete, pct = isNum(v) ? Math.round(100 * v) : null;
      return `<div class="qbar ${pct === null ? "is-missing" : pct < 80 ? "is-low" : ""}"><span>${esc(FIELD_LABEL[f.field] || f.field)}</span>
        <span class="qbar__track"><i style="width:${pct ?? 0}%"></i></span><b>${pct === null ? "not sent" : pct + "%"}</b></div>`;
    };
    const sys = d.fields.filter((f) => f.group === "system"), srv = d.fields.filter((f) => f.group === "survey");
    $("#quality").innerHTML = `
      <div class="qcols">
        <div><p class="tile__label">work systems · of ${f0(d.records)} records</p>${sys.map(bar).join("")}</div>
        <div><p class="tile__label">survey answers · of ${f0(d.answered)} who answered</p>${srv.map(bar).join("")}</div>
      </div>
      <p class="qissues ${d.issues.length ? "is-warn" : ""}">${d.issues.length ? `${d.issues.length} issue${d.issues.length > 1 ? "s" : ""} fixed on load: ${d.issues.slice(0, 2).map(esc).join(" · ")}` : "No issues on load."} Level ${d.level}: ${d.level >= 2 ? "all six stages run" : "Assess and Verify run"}.</p>`;
  }

  function renderCheck() {
    const c = S.loop.check, src = S.loop.source || {};
    if (!c) {
      const last = S.loop.periods.slice(-1)[0], nxt = nextPeriod(last);
      const m = S.loop.forecast_metrics || {};
      $("#check").innerHTML = `<p class="note">Every new month is a test: the model forecasts it <b>before</b> seeing the answers. No month added yet.</p>
        <ol class="checksteps">
          <li><b>1</b><strong>Forecast</strong><span>With data up to ${esc(monthLong(last))}, the model predicts ${esc(monthLong(nxt))} for everyone.</span></li>
          <li><b>2</b><strong>New month arrives</strong><span>${esc(monthLong(nxt))}'s surveys are uploaded on the left (or by a connector).</span></li>
          <li><b>3</b><strong>Compare</strong><span>Average error, how many landed inside their range, and which departments were off.</span></li>
        </ol>
        <p class="tile__label">until then: tested on people it never saw</p>
        <div class="checkpre"><div><b>±${f1(m.model?.mae)}</b><small>typical error (baseline ${f1(m.persistence?.mae)})</small></div>
          <div><b>${isNum(m.interval_95_coverage) ? (100 * m.interval_95_coverage).toFixed(1) + "%" : "—"}</b><small>inside the ±${f1(m.interval_95_halfwidth)} range</small></div></div>
        ${src.kind === "demo_live" && src.next_period ? `<button type="button" class="btn" data-act="file">Upload ${esc(monthLong(src.next_period))} data and check →</button>`
          : `<a class="more" href="#/model">full model check →</a>`}`;
      $$("#check [data-act]").forEach((b) => b.addEventListener("click", () => monthAction(b.dataset.act)));
      return;
    }
    const deps = c.by_department || [];
    const cols = "grid-template-columns:minmax(90px,1.6fr) 44px 70px 60px 60px;gap:10px";
    $("#check").innerHTML = `
      <dl class="checkkpis">
        <div><dt>Forecast · ${esc(monthLong(c.period))}</dt><dd>${f1(c.mean_predicted)}</dd></div>
        <div><dt>What came in</dt><dd style="color:${heat(c.mean_actual)}">${f1(c.mean_actual)}</dd></div>
        <div><dt>Average error</dt><dd>±${f1(c.mae)}</dd></div>
        <div><dt>Inside 95% range</dt><dd>${f1(c.inside_range_pct)}%</dd></div>
      </dl>
      <div class="table table--compact checktable"><div class="tr tr--head" style="${cols}"><span>Department</span><span class="num">n</span><span class="num">Forecast</span><span class="num">Actual</span><span class="num">Off by</span></div>
      ${deps.map((d) => `<div class="tr" style="${cols}"><span class="ellip">${esc(d.department)}</span><span class="num">${f0(d.n)}</span><span class="num">${f1(d.predicted)}</span><span class="num">${f1(d.actual)}</span><span class="num ${Math.abs(d.actual - d.predicted) >= 2 ? "is-off" : ""}">${signed(d.actual - d.predicted)}</span></div>`).join("")}</div>
      <p class="tile__fine">${f0(c.n)} people, forecast before their ${esc(monthLong(c.period))} answers existed.</p>`;
  }

  // ================= 02 PEOPLE: ranked list, filters =================
  const STATUSES = ["monitoring", "flagged", "support_planned", "in_support", "follow_up_due", "follow_up_overdue", "outcome_improved", "outcome_no_change", "outcome_worsened"];
  function readPeopleHash() {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const p = S.people;
    Object.keys(p).forEach((k) => { if (k !== "page") p[k] = q.get(k) ?? (k === "sort" ? "urgent" : ""); });
    p.page = 0;
    const f = $("#filters");
    Object.entries(p).forEach(([k, v]) => {
      const el = f.elements[k];
      if (!el) return;
      if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
    });
  }
  // ================= teams ranked =================
  // same month as the people list; a click opens that team's people
  async function loadTeams(page = 0) {
    const f = $("#tfilters"), dept = f.elements.department.value, sort = f.elements.sort.value;
    if (f.elements.department.options.length <= 1) {
      f.elements.department.innerHTML = `<option value="">All departments</option>` +
        (S.loop.divisions || []).map((d) => d.department).sort().map((x) => `<option>${esc(x)}</option>`).join("");
      f.elements.department.value = dept;
    }
    let d;
    try { d = await api(`/api/loop/teams?${new URLSearchParams({ period: S.loop.period, department: dept, sort })}`); }
    catch (e) { $("#teams").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
    S.teams = d;
    const all = d.rows.filter((r) => f.elements.small.checked || !r.suppressed);
    const size = 50, pages = Math.max(1, Math.ceil(all.length / size));
    page = Math.max(0, Math.min(page, pages - 1));
    const rows = all.slice(page * size, (page + 1) * size);
    const waiting = d.rows.reduce((a, r) => a + (r.n_needs_decision || 0), 0);
    $("#teamsum").innerHTML = `<a class="urgent__n" href="#/people?${new URLSearchParams({ status: "flagged", ...(dept ? { department: dept } : {}) })}">${f0(waiting)} need a decision</a> · <b>${f0(d.rows.length - d.n_hidden)}</b> teams with 5+ scored · <b class="hot">${f0(d.n_hot)}</b> running hot · company ${f1(d.company_pct_high)}% high · ${esc(monthLong(d.period))}${d.n_hidden ? ` · ${f0(d.n_hidden)} small teams hidden for privacy` : ""}`;
    const cols = "grid-template-columns:34px minmax(80px,.7fr) minmax(100px,.9fr) 130px minmax(110px,1fr) minmax(130px,1.1fr) minmax(160px,1.3fr) 84px 92px 60px 104px;gap:12px";
    const ref = d.company_pct_high;
    $("#teams").innerHTML = `<div class="tr tr--head" style="${cols}"><span>#</span><span>Team</span><span>Department</span><span>Surveyed</span><span>Average score</span><span>Share high (| company)</span><span>Needs action</span><span class="num">vs last month</span><span class="num">Next month</span><span class="num">Hours</span><span></span></div>` +
      rows.map((r, i) => {
        const n = page * size + i + 1;
        if (r.suppressed) return `<div class="tr is-muted" style="${cols}" data-dept="${esc(r.department)}" data-team="${esc(r.team_id)}"><span class="num">—</span><span><b>${esc(r.team_id)}</b></span><span class="ellip">${esc(r.department)}</span><span class="note">${f0(r.n_scored)} of ${f0(r.n)}</span><span class="note">under 5 scored, not shown</span><span></span>${urgentCell(r, { department: r.department, team: r.team_id })}<span></span><span></span><span></span><span class="tag tag--ash">too few</span></div>`;
        return `<div class="tr ${r.n_needs_decision ? "is-urgent" : ""}" style="${cols}" data-dept="${esc(r.department)}" data-team="${esc(r.team_id)}" title="Open ${esc(r.team_id)}: ${f0(r.n_high)} of ${f0(r.n_scored)} scored high">
          <span class="num rank">${n}</span>
          <span><b>${esc(r.team_id)}</b></span>
          <span class="ellip">${esc(r.department)}</span>
          <span class="surveycell">${surveyBar(r.survey_rate)}<span class="num">${f0(r.n_scored)}/${f0(r.n)}</span></span>
          <span class="scorecell"><span class="bar-mini"><span style="width:${Math.min(100, r.mean_score)}%;background:${heat(r.mean_score)}"></span></span><b style="color:${heat(r.mean_score)}">${f1(r.mean_score)}</b></span>
          <span class="scorecell"><span class="bar-mini"><span style="width:${Math.min(100, r.pct_high)}%;background:${r.hot ? "var(--flame)" : "var(--amber)"}"></span>${isNum(ref) ? `<em style="left:${Math.min(100, ref)}%"></em>` : ""}</span><b>${f0(r.pct_high)}%</b></span>
          ${urgentCell(r, { department: r.department, team: r.team_id })}
          <span class="num ${isNum(r.change) && r.change >= 5 ? "is-up" : isNum(r.change) && r.change <= -5 ? "is-down" : ""}">${signed(r.change)}</span>
          <span class="num">${f1(r.mean_forecast)} <small class="note">${signed(r.rise)}</small></span>
          <span class="num">${f1(r.mean_hours)}</span>
          <span>${r.hot ? `<span class="tag tag--fire">running hot</span>` : `<span class="tag tag--calm">in range</span>`}</span>
        </div>`;
      }).join("");
    $("#teams-pager").innerHTML = `<span>${f0(all.length)} teams · page ${page + 1} of ${pages} · "running hot" = more high scores than the company rate would give by chance</span><span><button type="button" data-p="-1" ${page <= 0 ? "disabled" : ""}>←</button> <button type="button" data-p="1" ${page >= pages - 1 ? "disabled" : ""}>→</button></span>`;
    $$("#teams-pager button").forEach((b) => b.addEventListener("click", () => loadTeams(page + +b.dataset.p)));
  }
  // ================= drill-down: departments > teams > people =================
  // urgency cell: people flagged with no support yet (links to them), plus very high now and gone quiet
  function urgentCell(r, params) {
    const nd = r.n_needs_decision || 0, vh = r.n_very_high || 0, gq = r.n_gone_quiet || 0;
    const href = `#/people?${new URLSearchParams({ ...params, status: "flagged" })}`;
    const extra = [vh ? `${f0(vh)} very high` : "", gq ? `${f0(gq)} gone quiet` : ""].filter(Boolean).join(" · ");
    return `<span class="urgent">${nd ? `<a class="urgent__n" href="${href}" title="Open the ${nd} people flagged with no support decided yet">${f0(nd)} need a decision</a>` : `<span class="urgent__ok">none waiting</span>`}${extra ? `<small>${extra}</small>` : ""}</span>`;
  }
  function renderDepts() {
    const c = S.loop.company || {}, ref = c.reference?.pct_high;
    const divs = [...(S.loop.divisions || [])].sort((a, b) => (b.mean_score ?? -1) - (a.mean_score ?? -1));
    const hot = divs.filter((d) => d.systemic).length;
    const waiting = divs.reduce((a, d) => a + (d.n_needs_decision || 0), 0);
    $("#deptsum").innerHTML = `<a class="urgent__n" href="#/people?status=flagged">${f0(waiting)} people need a decision now</a> · <b>${f0(c.n_flagged)}</b> flagged · <b class="hot">${f0(hot)}</b> department${hot === 1 ? "" : "s"} running hot · ${esc(monthLong(S.loop.period))}`;
    const cols = "grid-template-columns:34px minmax(130px,1.1fr) 150px minmax(130px,1fr) minmax(150px,1.1fr) minmax(170px,1.3fr) 64px 70px 110px;gap:14px";
    $("#depts").innerHTML = `<div class="tr tr--head" style="${cols}"><span>#</span><span>Department</span><span>Surveyed</span><span>Average score</span><span>Share high (| reference)</span><span>Needs action</span><span class="num">Flagged</span><span class="num">Hours</span><span></span></div>` +
      divs.map((d, i) => d.suppressed
        ? `<div class="tr is-muted" style="${cols}"><span class="num">—</span><span><b>${esc(d.department)}</b></span><span class="note">${f0(d.n_scored)} of ${f0(d.n_employees)}</span><span class="note">under 5 scored, not shown</span><span></span><span></span><span></span><span></span><span class="tag tag--ash">too few</span></div>`
        : `<div class="tr ${d.n_needs_decision ? "is-urgent" : ""}" style="${cols}" data-dept="${esc(d.department)}" title="Open ${esc(d.department)}'s teams">
          <span class="num rank">${i + 1}</span>
          <span><b>${esc(d.department)}</b></span>
          <span class="surveycell">${surveyBar(d.survey_rate)}<span class="num">${f0(d.n_scored)}/${f0(d.n_employees)}</span></span>
          <span class="scorecell"><span class="bar-mini"><span style="width:${Math.min(100, d.mean_score)}%;background:${heat(d.mean_score)}"></span></span><b style="color:${heat(d.mean_score)}">${f1(d.mean_score)}</b></span>
          <span class="scorecell"><span class="bar-mini"><span style="width:${Math.min(100, d.pct_high)}%;background:${d.systemic ? "var(--flame)" : "var(--amber)"}"></span>${isNum(ref) ? `<em style="left:${Math.min(100, ref)}%"></em>` : ""}</span><b>${f0(d.pct_high)}%</b></span>
          ${urgentCell(d, { department: d.department })}
          <span class="num">${f0(d.n_flagged)}</span>
          <span class="num">${f1(d.median_hours)}</span>
          <span>${d.systemic ? `<span class="tag tag--fire">running hot</span>` : `<span class="tag tag--calm">in range</span>`}</span>
        </div>`).join("");
  }
  // where you are: All departments > Department > Team; each part goes back up one click
  function renderCrumbs() {
    const v = $(".t-list").dataset.view;
    const dept = v === "teams" ? $("#tfilters").elements.department.value : v === "people" ? S.people.department : "";
    const team = v === "people" ? S.people.team : "";
    const parts = [`<a href="#/people?view=departments">All departments</a>`];
    if (dept) parts.push(v === "teams" && !team ? `<b>${esc(dept)}</b>` : `<a href="#/people?view=teams&department=${encodeURIComponent(dept)}">${esc(dept)}</a>`);
    else if (v !== "departments") parts.push(`<b>${v === "teams" ? "all teams" : "everyone"}</b>`);
    if (team) parts.push(`<b>${esc(team)}</b>`);
    $("#crumbs").innerHTML = parts.join(`<span aria-hidden="true">›</span>`);
    renderSeats();
  }
  // ================= stadium: one seat per person, a wedge per group =================
  const SEAT = { d: ["need a decision", "#C42B1C"], f: ["flagged, other", "#E2621B"], s: ["in support", "#E8A03C"],
                 w: ["watch", "#F0CB8E"], o: ["ok", "#CFC8BC"], n: ["no score", "none"] };
  const SEAT_ORDER = "dfswon";
  // one sector per group, separated by a small gap; seats fill each sector ring by ring, clockwise from the top.
  // A single spacing is shrunk until every sector holds its people, so seat size is the same everywhere.
  function sectorLayout(sizes, cx, cy, r0, R, gap, full = 2 * Math.PI, offset = 0, maxDot = 8) {
    const n = sizes.reduce((x, y) => x + y, 0) || 1, k = sizes.length;
    const avail = full - (k > 1 ? gap * k : 0);
    let s = Math.sqrt((avail / 2) * (R * R - r0 * r0) / n) * 0.97, out = [];
    for (let tries = 0; tries < 40; tries++, s *= 0.96) {
      let start = offset + (k > 1 ? gap / 2 : 0), ok = true;
      out = sizes.map((m) => {
        const span = (avail * m) / n, cand = [];
        for (let r = r0 + s / 2; r <= R; r += s) {
          const q = Math.max(1, Math.floor((span * r) / s));
          for (let i = 0; i < q; i++) cand.push({ a: start + ((i + 0.5) * span) / q, r });
        }
        if (cand.length < m) ok = false;
        cand.sort((p, q2) => p.a - q2.a || q2.r - p.r);
        const pts = Array.from({ length: m }, (_, i) => cand[Math.floor((i * cand.length) / Math.max(1, m))]).filter(Boolean)
          .map((p) => ({ x: cx + p.r * Math.sin(p.a), y: cy - p.r * Math.cos(p.a), a: p.a }));
        const sec = { a0: start, a1: start + span, pts };
        start += span + (k > 1 ? gap : 0);
        return sec;
      });
      if (ok) break;
    }
    return { sectors: out, dot: Math.min(maxDot, s * 0.4) };
  }

  function countUp(el, to, ms = 600) {
    if (!el || reduced) { if (el) el.textContent = f0(to); return; }
    const t0 = performance.now();
    const step = (t) => { const k = Math.min(1, (t - t0) / ms); el.textContent = f0(Math.round(to * (1 - Math.pow(1 - k, 3)))); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  async function renderSeats() {
    if (!S.loop || !$("#seats")) return;
    if (!S.seats || S.seats.period !== S.loop.period) {
      try { S.seats = await api(`/api/loop/seats?period=${encodeURIComponent(S.loop.period)}`); } catch { return; }
    }
    const v = $(".t-list").dataset.view;
    const dept = v === "teams" ? $("#tfilters").elements.department.value : v === "people" ? S.people.department : "";
    const team = v === "people" ? S.people.team : "";
    let rows = S.seats.rows.filter((r) => (!dept || r[1] === dept) && (!team || r[2] === team));
    const level = team ? "person" : dept ? "team" : "department";
    const key = (r) => (level === "department" ? r[1] : r[2]);
    // groups with the most people waiting for a decision first, so urgent wedges start at the top
    const groups = {};
    rows.forEach((r) => (groups[key(r)] = groups[key(r)] || []).push(r));
    const order = Object.entries(groups).sort((x, y) => y[1].filter((r) => r[3] === "d").length - x[1].filter((r) => r[3] === "d").length || y[1].length - x[1].length);
    // one team: a slice cut from the department circle (apex at the bottom), seats filling it
    const slice = level === "person", SPAN = 1.4;
    const cx = 160, cy = slice ? 262 : 150, R = slice ? 226 : 118, r0 = slice ? 30 : rows.length > 40 ? 52 : 38;
    const gap = order.length > 1 ? Math.min(0.09, 0.9 / order.length) : 0;
    const { sectors, dot } = sectorLayout(order.map(([, list]) => list.length), cx, cy, r0, R, gap,
      slice ? SPAN : 2 * Math.PI, slice ? -SPAN / 2 : 0, slice ? 12 : 8);
    const wedge = (a, rr) => `${(cx + rr * Math.sin(a)).toFixed(1)} ${(cy - rr * Math.cos(a)).toFixed(1)}`;
    const band = (a0, a1, ri, ro) => `M${wedge(a0, ri)} L${wedge(a0, ro)} A${ro} ${ro} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${wedge(a1, ro)} L${wedge(a1, ri)} A${ri} ${ri} 0 ${a1 - a0 > Math.PI ? 1 : 0} 0 ${wedge(a0, ri)}Z`;
    let g = slice ? `<path class="slice" d="${band(-SPAN / 2, SPAN / 2, 0, R + 10)}"/><path class="slice__crust" d="M${wedge(-SPAN / 2, R + 10)} A${R + 10} ${R + 10} 0 0 1 ${wedge(SPAN / 2, R + 10)}"/>` : "";
    order.forEach(([name, list], gi) => {
      list.sort((x, y) => SEAT_ORDER.indexOf(x[3]) - SEAT_ORDER.indexOf(y[3]));
      const sec = sectors[gi], mine = sec.pts;
      const nd = list.filter((r) => r[3] === "d").length;
      const href = level === "department" ? `#/people?view=teams&department=${encodeURIComponent(name)}`
        : level === "team" ? `#/people?department=${encodeURIComponent(dept)}&team=${encodeURIComponent(name)}` : "";
      const a0 = sec.a0, a1 = sec.a1, mid = (a0 + a1) / 2;
      const big = a1 - a0 > Math.PI ? 1 : 0;
      // a tinted band behind each sector (alternating), which is also the click/hover target
      const hit = level !== "person" && mine.length ? `<path class="sg__hit ${gi % 2 ? "is-alt" : ""}" d="${band(a0, a1, r0 - 7, R + 7)}"/>` : "";
      g += `<g class="sg" ${href ? `data-href="${esc(href)}" tabindex="0" role="link"` : ""}><title>${esc(name)} · ${f0(list.length)} people · ${f0(nd)} need a decision</title>${hit}` +
        list.map((r, j) => {
          const p = mine[j], [label, col] = SEAT[r[3]];
          const fill = col === "none" ? `fill="none" stroke="#B3ADA3" stroke-width="1"` : `fill="${col}"`;
          return level === "person"
            ? `<circle class="seat seat--person" style="--d:${((p.a / (2 * Math.PI)) * 0.5).toFixed(3)}s" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${dot.toFixed(2)}" ${fill} data-href="#/employees/${encodeURIComponent(r[0])}" tabindex="0" role="link"><title>${esc(r[0])} · ${label}</title></circle>`
            : `<circle class="seat" style="--d:${((p.a / (2 * Math.PI)) * 0.5).toFixed(3)}s" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${dot.toFixed(2)}" ${fill}/>`;
        }).join("") +
        (order.length <= 8 && level === "department" && mine.length
          ? (() => { const lx = cx + (R + 12) * Math.sin(mid), ly = cy - (R + 12) * Math.cos(mid);
              return `<text class="sg__label" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${Math.sin(mid) > 0.15 ? "start" : Math.sin(mid) < -0.15 ? "end" : "middle"}" dominant-baseline="middle">${esc(name.replace("Customer Support", "Cust. Support").replace("Human Resources", "HR"))}</text>`; })()
          : "") + `</g>`;
    });
    if (order.length > 1) sectors.forEach((sec) => {
      const a = sec.a1 + gap / 2;
      g += `<line class="sg__div" x1="${wedge(a, r0 - 10).split(" ")[0]}" y1="${wedge(a, r0 - 10).split(" ")[1]}" x2="${wedge(a, R + 10).split(" ")[0]}" y2="${wedge(a, R + 10).split(" ")[1]}"/>`;
    });
    const nd = rows.filter((r) => r[3] === "d").length;
    const up = level === "person" ? `#/people?view=teams&department=${encodeURIComponent(dept)}` : level === "team" ? "#/people?view=departments" : "";
    g += slice
      ? `<g class="seats__mid" data-href="${esc(up)}" tabindex="0" role="link">
      <text x="10" y="246" class="seats__n">${f0(nd)}</text>
      <text x="10" y="262" class="seats__l">need a decision</text>
      <text x="10" y="276" class="seats__l2">of ${f0(rows.length)} in ${esc(team)}</text><text x="10" y="290" class="seats__l2 seats__back">↑ back to ${esc(dept)}</text></g>`
      : `<g class="seats__mid" ${up ? `data-href="${esc(up)}" tabindex="0" role="link"` : ""}>
      <text x="${cx}" y="${cy - 6}" text-anchor="middle" class="seats__n">${f0(nd)}</text>
      <text x="${cx}" y="${cy + 10}" text-anchor="middle" class="seats__l">need a decision</text>
      <text x="${cx}" y="${cy + 23}" text-anchor="middle" class="seats__l2">of ${f0(rows.length)}${up ? " · ↑ back" : ""}</text></g>`;
    $("#seats").innerHTML = g;
    countUp($("#seats .seats__n"), nd);
    $("#seats-title").textContent = team ? `${team} · each seat is a person` : dept ? `${dept} · a wedge per team` : "Company · a wedge per department";
    const counts = Object.fromEntries([...SEAT_ORDER].map((k) => [k, rows.filter((r) => r[3] === k).length]));
    $("#seats-key").innerHTML = [...SEAT_ORDER].map((k) => `<li><i style="${SEAT[k][1] === "none" ? "border:1px solid #B3ADA3" : `background:${SEAT[k][1]}`}"></i>${SEAT[k][0]}<b>${f0(counts[k])}</b></li>`).join("");
  }

  function fillTeamDepts() {
    const sel = $("#tfilters").elements.department;
    if (sel.options.length > 1) return;
    sel.innerHTML = `<option value="">All departments</option>` +
      (S.loop.divisions || []).map((d) => d.department).sort().map((x) => `<option>${esc(x)}</option>`).join("");
  }
  function setPeopleView(v, dept) {
    $(".t-list").dataset.view = v;
    $(".t-pfilter").dataset.view = v;
    $$("#peopleview button").forEach((x) => { x.classList.toggle("is-on", x.dataset.view === v); x.setAttribute("aria-selected", x.dataset.view === v); });
    if (v === "departments") renderDepts();
    if (v === "teams") { fillTeamDepts(); if (dept !== undefined) $("#tfilters").elements.department.value = dept; loadTeams(); }
    renderCrumbs();
  }
  function wireTeams() {
    // level tabs go through the URL, so back/forward and the breadcrumb all work the same way
    $("#peopleview").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) location.hash = `#/people?view=${b.dataset.view}`; });
    $("#tfilters").addEventListener("change", () => { loadTeams(); renderCrumbs(); });
    const seatGo = (e) => { const t = e.target.closest("[data-href]"); if (t) location.hash = t.dataset.href; };
    $("#seats").addEventListener("click", seatGo);
    $("#seats").addEventListener("keydown", (e) => { if (e.key === "Enter") seatGo(e); });
    $("#depts").addEventListener("click", (e) => {
      if (e.target.closest("a")) return;       // the urgency link opens the people directly
      const r = e.target.closest(".tr[data-dept]");
      if (r) location.hash = `#/people?view=teams&department=${encodeURIComponent(r.dataset.dept)}`;
    });
    $("#teams").addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const r = e.target.closest(".tr[data-team]");
      if (!r) return;
      setPeopleView("people");
      location.hash = `#/people?department=${encodeURIComponent(r.dataset.dept)}&team=${encodeURIComponent(r.dataset.team)}`;
    });
  }

  async function loadPeople() {
    const p = S.people, body = $("#people-body");
    const size = 50;   // up to 50 rows per page; the table scrolls inside its tile
    const params = Object.fromEntries(Object.entries({ ...p, page_size: size }).filter(([, v]) => v !== "" && v != null));
    try {
      const d = await peopleQuery(params);
      const f = $("#filters");
      f.elements.department.innerHTML = `<option value="">All departments</option>` + d.facets.departments.map((x) => `<option ${x === p.department ? "selected" : ""}>${esc(x)}</option>`).join("");
      f.elements.team.innerHTML = `<option value="">${p.department ? "All teams" : "Pick a department first"}</option>` + d.facets.teams.map((x) => `<option ${x === p.team ? "selected" : ""}>${esc(x)}</option>`).join("");
      f.elements.team.disabled = !p.department;
      $$("#quicktabs button").forEach((b) => b.classList.toggle("is-on", b.dataset.status === (p.status || "")));
      const cols = "grid-template-columns:92px minmax(84px,1fr) 66px 128px 118px 96px 132px minmax(112px,1fr) minmax(150px,1.3fr);gap:10px";
      $("#people").innerHTML = `<div class="tr tr--head" style="${cols}"><span>Employee</span><span>Department</span><span>Team</span><span>Burnout</span><span>Last 6 months</span><span class="num">Next month</span><span>Workload</span><span>Status</span><span>Last support → result</span></div>` +
        (d.rows.length ? d.rows.map((r) => `<div class="tr ${r.status === "flagged" ? "is-urgent" : ""}" style="${cols}" data-id="${esc(r.employee_id)}" title="Open ${esc(r.employee_id)}${r.flag_reasons ? " · flagged: " + esc(r.flag_reasons) : ""}">
          <span><b>${esc(r.employee_id)}</b></span><span class="ellip">${esc(r.department)}</span><span class="ellip">${esc(r.team_id || "")}</span>
          <span><b class="score" style="color:${heat(r.cbi_work_score)}">${f1(r.cbi_work_score)}</b> ${levelTag(r.cbi_work_score)}</span>
          <span>${spark(r.trend)}</span>
          <span class="num">${isNum(r.forecast) ? `${f1(r.forecast)} <small class="${r.forecast - r.cbi_work_score >= 5 ? "up" : "note"}">${signed(r.forecast - r.cbi_work_score)}</small>` : "—"}</span>
          <span>${workTag(r.workload_level)} <small class="note">${f1(r.work_hours_per_week)}h</small></span>
          <span class="ellip">${r.status === "flagged" ? `<span class="urgent__n">needs a decision</span>` : `<i class="sw" style="background:${STATUS_COLOR[r.status] || "#B3ADA3"};margin-right:6px"></i>${esc(title(r.status))}`}</span>
          <span class="ellip">${supportCell(r)}</span></div>`).join("") : `<p class="empty">No employees match these filters in ${esc(monthLong(d.period))}.</p>`);
      $$("#people .tr[data-id]").forEach((row) => row.addEventListener("click", () => (location.hash = `#/employees/${row.dataset.id}`)));
      $("#people-pager").innerHTML = `<span>${f0(d.total)} employees · ${esc(monthLong(d.period))} · page ${d.page + 1} of ${d.pages}</span><span><button type="button" data-p="-1" ${d.page <= 0 ? "disabled" : ""}>←</button> <button type="button" data-p="1" ${d.page >= d.pages - 1 ? "disabled" : ""}>→</button></span>`;
      $$("#people-pager button").forEach((b) => b.addEventListener("click", () => { S.people.page += +b.dataset.p; loadPeople(); }));
    } catch (e) {
      $("#people").innerHTML = `<p class="empty">${esc(e.message)}</p>`;
    }
  }
  // tiny line of the last 6 monthly scores; dashed line = the high threshold
  function spark(vals) {
    if (!Array.isArray(vals)) return `<span class="note">—</span>`;   // server did not send a trend
    const v = vals, W = 110, H = 26, n = Math.max(1, v.length - 1);
    const X = (i) => 3 + (i * (W - 6)) / n, Y = (s) => 3 + ((100 - s) * (H - 6)) / 100;
    if (!v.some(isNum)) return `<span class="note">no survey answered</span>`;
    const last = [...v.keys()].filter((i) => isNum(v[i])).pop();
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Last ${v.length} months: ${v.map((x) => (isNum(x) ? x : "no survey")).join(", ")}">
      <line x1="0" x2="${W}" y1="${Y(CUT.high)}" y2="${Y(CUT.high)}" stroke="#C42B1C" stroke-opacity=".35" stroke-dasharray="2 3"/>
      <path d="${linePath(v.map((x, i) => (isNum(x) ? [X(i), Y(x)] : null)))}" fill="none" stroke="#1D1D1B" stroke-width="1.6"/>
      <circle cx="${X(last)}" cy="${Y(v[last])}" r="3.2" fill="${heat(v[last])}" stroke="#1D1D1B" stroke-width="1"/></svg>`;
  }
  function supportCell(r) {
    if (!r.latest_intervention) return `<span class="note">none yet</span>`;
    const out = r.latest_outcome;
    const tone = out === "improved" ? "tag--calm" : out === "worsened" ? "tag--fire" : "tag--ash";
    return `${esc(title(r.latest_intervention))} → <span class="tag ${tone}">${esc(out ? title(out) : "pending")}</span>`;
  }

  function wireFilters() {
    const f = $("#filters");
    let t;
    const apply = () => {
      const p = S.people;
      ["q", "department", "team", "level", "workload", "sort"].forEach((k) => (p[k] = f.elements[k].value));
      p.flagged = f.elements.flagged.checked ? "1" : "";
      if (f.elements.department.value !== (new URLSearchParams(location.hash.split("?")[1] || "").get("department") || "")) p.team = "";
      p.page = 0;
      const qs = new URLSearchParams(Object.fromEntries(Object.entries(p).filter(([k, v]) => v && k !== "page" && !(k === "sort" && v === "urgent"))));
      history.replaceState(null, "", `#/people?${qs.toString() || "view=people"}`);
      loadPeople();
      renderCrumbs();
    };
    f.addEventListener("change", apply);
    f.elements.q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(apply, 300); });
    f.addEventListener("submit", (e) => { e.preventDefault(); apply(); });
    $$("#quicktabs button").forEach((b) => b.addEventListener("click", () => { S.people.status = b.dataset.status; apply(); }));
  }

  // ================= one employee =================
  const SCEN_LABEL = { no_change: "No change", overtime_minus_5h: "Overtime −5 h" };
  const scenLabel = (k) => SCEN_LABEL[k] || `${title(k)} (support)`;

  async function openEmployee(id) {
    id = String(id || "").trim();
    if (!id) return;
    if (S.person?.employee_id?.toUpperCase() === id.toUpperCase() && S.personRow?.period === S.loop.period) return;
    try {
      const [data, row] = await Promise.all([
        api(`/api/search-employee?id=${encodeURIComponent(id)}`),
        peopleQuery({ q: id, page_size: 5 }).catch(() => ({ rows: [] })),
      ]);
      const L = data.longitudinal;
      if (!L || !L.timeline?.length) throw new Error(`${id} has no monthly survey record to track.`);
      S.person = L;
      S.personRow = (row.rows || []).find((r) => String(r.employee_id).toUpperCase() === id.toUpperCase()) || null;
      S.scenario = L.scenarios?.no_change ? "no_change" : Object.keys(L.scenarios || {})[0];
      renderPerson();
      renderStanding();
      renderDrivers();
      renderInsights();
      renderResults();
    } catch (e) {
      toast(e.message);
    }
  }

  function renderPerson() {
    const L = S.person, tl = L.timeline, f = L.forecast;
    const lastScored = [...tl].reverse().find((r) => isNum(r.cbi_work_score));
    $("#p-id").textContent = L.employee_id;
    $("#p-now").innerHTML = `
      <div><dt>Latest</dt><dd style="color:${heat(lastScored?.cbi_work_score)}">${f1(lastScored?.cbi_work_score)}</dd><small>${level(lastScored?.cbi_work_score)} · ${esc(monthLabel(lastScored?.period || "2000-01"))}</small></div>
      <div><dt>Next month</dt><dd>${f ? f1(f.forecast) : "—"}</dd><small>${f ? `range ${f1(f.forecast_low)}–${f1(f.forecast_high)}` : "no forecast"}</small></div>`;

    const keys = Object.keys(L.scenarios || {});
    $("#scenarios").innerHTML = keys.map((k) => {
      const rows = L.scenarios[k], last = rows[rows.length - 1] || {};
      return `<button type="button" role="tab" class="scen ${k === S.scenario ? "is-on" : ""}" aria-selected="${k === S.scenario}" data-k="${esc(k)}">
        <span class="scen__name">${esc(scenLabel(k))}</span><span class="scen__val">${f1(last.p50)}</span>
        <span class="scen__sub">${isNum(last.share_high) ? Math.round(last.share_high * 100) + "%" : "—"} high</span>
      </button>`;
    }).join("") || `<p class="note">No simulation for this employee (no score in the latest month).</p>`;
    $$("#scenarios .scen").forEach((b) => b.addEventListener("click", () => { S.scenario = b.dataset.k; renderPerson(); }));
    $("#scennote").textContent = "Shaded = support periods. Median and 10–90% of 500 simulated paths; not a promise.";
    drawPerson();
    renderLogForm();
  }

  // 04 intervene: the person deciding picks a support type (with its evidence), owner and dates
  const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
  function renderLogForm() {
    const f = $("#logform"), latest = S.loop.periods.slice(-1)[0];
    const types = S.loop.support_types || [];
    f.elements.intervention_type.innerHTML = types.map((t) => {
      const ev = isNum(t.simulation_effect) ? `expected ${signed(t.simulation_effect)} pts · ${/randomised/.test(t.evidence) ? "randomised pilot" : "observational"}` : "no reliable effect yet";
      return `<option value="${esc(t.type)}">${esc(title(t.type))} — ${esc(ev)}</option>`;
    }).join("");
    const start = nextPeriod(latest), end = nextPeriod(start, 1), [ey, em] = end.split("-").map(Number);
    if (!f.elements.start_date.value) f.elements.start_date.value = `${start}-01`;
    if (!f.elements.planned_end_date.value) f.elements.planned_end_date.value = `${end}-${String(lastDay(ey, em)).padStart(2, "0")}`;
    $("#logform-note").textContent = "The survey after it ends checks if it helped.";
  }
  function wireLogForm() {
    $("#logform").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target, btn = f.querySelector(".btn");
      const body = Object.fromEntries(new FormData(f));
      body.employee_id = S.person.employee_id;
      btn.disabled = true; btn.textContent = "Logging…";
      try {
        const r = await post("/api/loop/support", body);
        f.elements.notes.value = "";
        await reloadPerson();
        toast(`${title(r.support.intervention_type)} logged for ${r.support.employee_id} (${r.support.intervention_id}).`);
      } catch (err) { toast(err.message); }
      btn.disabled = false; btn.textContent = "Log support";
    });
    // started / completed / stopped buttons on open support cards
    $("#results").addEventListener("change", async (e) => {
      const b = e.target.closest("select[data-sid]");
      if (!b || !b.value) return;
      b.disabled = true;
      try {
        await post("/api/loop/support/status", { intervention_id: b.dataset.sid, status: b.value });
        await reloadPerson();
        toast(`${b.dataset.sid} marked ${b.value}.`);
      } catch (err) { toast(err.message); b.disabled = false; }
    });
  }
  // support changes refit the loop, so counts, statuses and this person's record are reloaded
  async function reloadPerson() {
    const id = S.person?.employee_id;
    await loadData(S.loop.period);
    if (id) { S.person = null; await openEmployee(id); }
  }

  // where this person stands on the 0-100 scale against their department, the company and the reference
  function renderStanding() {
    const st = S.person.standing;
    if (!st || !isNum(st.score)) { $("#standing").innerHTML = `<p class="note">No survey score yet.</p>`; return; }
    // dots on the bar only; names and values go in the legend below, so nearby values never overlap
    const marks = [[st.score, "this person", "is-me"], [st.department_mean, st.department || "department", "is-dept"],
                   [st.company_mean, "company", "is-co"]].filter(([v]) => isNum(v));
    const legend = marks.filter(([, , cls]) => cls !== "is-me");
    $("#standing").innerHTML = `
      <div class="standing__track"><span class="standing__cut" style="left:${CUT.high}%" title="high from ${CUT.high}"></span>
        ${[...marks].reverse().map(([v, label, cls]) => `<span class="standing__dot ${cls}" style="left:${Math.max(0, Math.min(100, v))}%" title="${esc(label)}: ${f1(v)}"></span>`).join("")}</div>
      <div class="standing__ticks"><span>0 calm</span><span>${CUT.high} high</span><span>100</span></div>
      <ul class="standing__legend">${legend.map(([v, label, cls]) => `<li><i class="standing__dot ${cls}"></i>${esc(label)}<b>${f1(v)}</b></li>`).join("")}</ul>`;
  }

  // the 7 survey answers of the latest month, so a manager sees which part of work wears the person down
  const ANSWER = { 0: "never", 25: "seldom", 50: "sometimes", 75: "often", 100: "always" };
  function renderDrivers() {
    const it = S.person.items;
    if (!it) { $("#drivers").innerHTML = `<p class="note">No survey answers yet.</p>`; return; }
    const rows = [...it.answers].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    $("#drivers-month").textContent = `${monthLong(it.period)} survey · strongest first`;
    $("#drivers").innerHTML = rows.map((a) => `
      <div class="driver"><span class="driver__q">${esc(a.question)}</span>
        <span class="driver__bar"><span style="width:${isNum(a.score) ? Math.max(2, a.score) : 0}%;background:${heat(a.score)}"></span></span>
        <span class="driver__a">${isNum(a.score) ? esc(ANSWER[a.score] ?? f0(a.score)) : "no answer"}</span></div>`).join("");
  }

  // workload gauge (hours vs contract and the legal limit) and the reasons behind the flag, for the viewed month
  function renderInsights() {
    const r = S.personRow, contract = S.person.contracted_hours;
    $("#p-where").innerHTML = r ? `${esc(r.department)}${r.team_id ? ` · ${esc(r.team_id)}` : ""}${r.role_type ? ` · ${esc(title(r.role_type))}` : ""} · ${esc(monthLong(r.period))}
      <span class="statuschip"><i class="sw" style="background:${STATUS_COLOR[r.status] || "#B3ADA3"}"></i>${esc(title(r.status))}</span>` : "";
    if (!r) { $("#gauge").innerHTML = $("#gauge-head").innerHTML = ""; $("#insights").innerHTML = `<p class="note">No record for ${esc(monthLong(S.loop.period))}.</p>`; return; }
    const MAX = 70, P = (h) => `${Math.max(0, Math.min(100, (100 * h) / MAX))}%`;
    const hrs = r.work_hours_per_week;
    // hours sit in the label line so this bar lines up with the "where they stand" bar
    $("#gauge-head").innerHTML = isNum(hrs) ? `<b>${f1(hrs)} h/week</b>${workTag(r.workload_level)}` : "";
    $("#gauge").innerHTML = isNum(hrs) ? `
      <div class="gauge__track"><span class="gauge__fill" style="width:${P(hrs)};background:${r.workload_level === "high" ? "var(--flame)" : r.workload_level === "elevated" ? "var(--amber)" : "var(--calm)"}"></span>
        ${isNum(contract) ? `<span class="gauge__tick" style="left:${P(contract)}" title="contract ${f0(contract)} h"></span>` : ""}
        <span class="gauge__tick gauge__tick--limit" style="left:${P(48)}" title="48 h limit"></span></div>
      <p class="gauge__key">${isNum(contract) ? `<span><i class="gauge__mark"></i>contract ${f0(contract)} h</span>` : ""}<span><i class="gauge__mark gauge__mark--limit"></i>48 h limit</span><span>overtime ${f1(r.overtime_hours_per_week)} h</span>${isNum(r.perceived_workload_1_5) ? `<span>says ${f0(r.perceived_workload_1_5)}/5</span>` : ""}</p>` : `<p class="note">No hours recorded this month.</p>`;
    // why flagged: the trajectory rule (sustained, reliable rise, quiet after high); one high month is "watch";
    // the reference points (department, own average, forecast) are shown as context in grey
    const chips = [], ctx = [];
    if (r.sustained_high ?? (r.trajectory_level === "flagged" && isNum(r.prev_score) && r.prev_score >= CUT.high && r.cbi_work_score >= CUT.high))
      chips.push(`high two surveys running · ${f1(r.prev_score)} → ${f1(r.cbi_work_score)}`);
    if (r.trajectory_level === "flagged" && isNum(r.personal_change) && isNum(S.rci) && r.personal_change >= S.rci && r.cbi_work_score >= 40)
      chips.push(`${signed(r.personal_change)} vs own avg ${f1(r.personal_baseline)}, beyond noise`);
    if (r.trajectory_level === "flagged" && !isNum(r.cbi_work_score) && isNum(r.prev_score))
      chips.push(`no survey for ${f0(r.missed_streak)} month${r.missed_streak > 1 ? "s" : ""} after scoring ${f1(r.prev_score)}`);
    if (isNum(r.division_score_z) && r.division_score_z >= 2) ctx.push(`far above ${esc(r.department)}`);
    if (isNum(r.forecast)) ctx.push(`next month ${f1(r.forecast)}`);
    const head = r.trajectory_level === "flagged" ? "why flagged" : r.trajectory_level === "watch" ? "watch · one high month, flagged if it repeats" : "";
    $("#insights").innerHTML = head
      ? `<p class="tile__label">${head}</p><div class="flagchips">${(chips.length ? chips : [`score ${f1(r.cbi_work_score)} ≥ ${CUT.high}`])
          .map((c) => `<span class="tag ${r.trajectory_level === "flagged" ? "tag--fire" : "tag--amber"}">${c}</span>`).join("")}${ctx.map((c) => `<span class="tag tag--ash">${c}</span>`).join("")}</div>`
      : `<p class="note">Not flagged in ${esc(monthLong(r.period))}.</p>`;
  }

  function drawPerson() {
    const svg = $("#personchart");
    if (!S.person || !svg.getBoundingClientRect().width) return;
    const { w, h } = svgSize(svg);
    const tl = S.person.timeline, scen = S.person.scenarios || {};
    const periods = tl.map((r) => r.period), last = periods[periods.length - 1];
    const all = [...periods, ...[1, 2, 3].map((k) => nextPeriod(last, k))];
    const pad = { l: 34, r: 12, t: 22, b: 24 };
    const X = (i) => pad.l + (i * (w - pad.l - pad.r)) / (all.length - 1);
    const Y = (v) => pad.t + ((100 - v) * (h - pad.t - pad.b)) / 100;
    let g = "";
    g += `<rect x="${pad.l}" y="${Y(100)}" width="${w - pad.l - pad.r}" height="${Y(CUT.very) - Y(100)}" fill="rgba(196,43,28,.07)"/>`;
    g += `<rect x="${pad.l}" y="${Y(CUT.very)}" width="${w - pad.l - pad.r}" height="${Y(CUT.high) - Y(CUT.very)}" fill="rgba(235,165,74,.11)"/>`;
    [0, 25, CUT.high, CUT.very, 100].forEach((v) => { g += `<line class="grid" x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`; });
    g += `<text x="${w - pad.r}" y="${Y(CUT.very) - 5}" text-anchor="end" style="fill:#C42B1C">very high</text><text x="${w - pad.r}" y="${Y(CUT.high) - 5}" text-anchor="end" style="fill:#9A5A0C">high</text>`;
    const fx = X(periods.length - 1);
    g += `<line x1="${fx}" x2="${fx}" y1="${pad.t - 8}" y2="${h - pad.b}" stroke="#1D1D1B" stroke-dasharray="2 4"/><text x="${fx + 6}" y="${pad.t - 10}">simulated →</text>`;
    const vi = periods.indexOf(S.loop.period);
    if (vi >= 0 && vi < periods.length - 1) g += `<line x1="${X(vi)}" x2="${X(vi)}" y1="${pad.t}" y2="${h - pad.b}" stroke="#E2621B" stroke-width="2"/><text x="${X(vi) + 4}" y="${pad.t + 10}" style="fill:#E2621B">viewing</text>`;
    const idx = (p) => all.indexOf(String(p || "").slice(0, 7));
    (S.person.linked_interventions || []).forEach((v) => {
      const a = idx(clean(v.start_date));
      if (a < 0) return;
      const b0 = idx(clean(v.completed_date) || clean(v.follow_up_due_date));
      const b = b0 >= a ? b0 : Math.min(a + 1, all.length - 1);
      const name = title(v.intervention_type);
      g += `<rect x="${X(a) - 6}" y="${pad.t}" width="${Math.max(12, X(b) - X(a) + 12)}" height="${h - pad.t - pad.b}" rx="8" fill="rgba(226,98,27,.13)"><title>${esc(name)}: ${esc(v.action_status)}</title></rect>`;
    });
    all.forEach((p, i) => { if (i % (w < 560 ? 2 : 1) === 0) g += `<text x="${X(i)}" y="${h - 6}" text-anchor="middle">${monthLabel(p)}</text>`; });
    const lastIdx = tl.map((r, i) => (isNum(r.cbi_work_score) ? i : -1)).filter((i) => i >= 0).pop();
    const lastPt = lastIdx != null ? [X(lastIdx), Y(tl[lastIdx].cbi_work_score)] : null;
    const fut = (rows, key) => rows.map((r) => [X(periods.length - 1 + r.month_ahead), Y(r[key])]);
    Object.entries(scen).forEach(([k, rows]) => {
      if (k !== S.scenario) g += `<path d="${linePath([lastPt, ...fut(rows, "p50")])}" fill="none" stroke="#8C867D" stroke-width="1.5" stroke-dasharray="3 4"/>`;
    });
    const rows = scen[S.scenario] || [];
    if (rows.length && lastPt) {
      const top = fut(rows, "p90"), bot = fut(rows, "p10").reverse();
      g += `<defs><linearGradient id="fan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C42B1C" stop-opacity=".35"/><stop offset="1" stop-color="#EBA54A" stop-opacity=".25"/></linearGradient></defs>`;
      g += `<path d="M${lastPt[0]},${lastPt[1]}${top.map((p) => `L${p[0]},${p[1]}`).join("")}${bot.map((p) => `L${p[0]},${p[1]}`).join("")}Z" fill="url(#fan)"/>`;
      g += `<path d="${linePath([lastPt, ...fut(rows, "p50")])}" fill="none" stroke="#C42B1C" stroke-width="2.5" stroke-dasharray="6 5"/>`;
      rows.forEach((r) => { g += `<circle cx="${X(periods.length - 1 + r.month_ahead)}" cy="${Y(r.p50)}" r="4.5" fill="${heat(r.p50)}" stroke="#fff" stroke-width="1.5"><title>+${r.month_ahead} mo: median ${f1(r.p50)} (10–90%: ${f1(r.p10)}–${f1(r.p90)})</title></circle>`; });
    }
    g += `<path d="${linePath(tl.map((r, i) => (isNum(r.cbi_work_score) ? [X(i), Y(r.cbi_work_score)] : null)))}" fill="none" stroke="#1D1D1B" stroke-width="2.5"/>`;
    tl.forEach((r, i) => {
      if (isNum(r.cbi_work_score)) g += `<circle cx="${X(i)}" cy="${Y(r.cbi_work_score)}" r="5.5" fill="${heat(r.cbi_work_score)}" stroke="#1D1D1B" stroke-width="1.5"><title>${r.period}: ${f1(r.cbi_work_score)}</title></circle>`;
      else g += `<circle cx="${X(i)}" cy="${h - pad.b - 2}" r="3" fill="none" stroke="#8C867D"><title>${r.period}: no survey</title></circle>`;
    });
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = g;
  }

  // 05 verify: one row per support action, newest first; open ones can be marked started / completed / stopped
  function renderResults() {
    // open support first (not finished or not yet checked, soonest check first), then results latest first,
    // then anything left without a result (control, declined or stopped)
    const due = (v) => String(clean(v.follow_up_due_date) || v.baseline_period || "");
    const rank = (v) => {
      const st = String(v.action_status || "").toLowerCase();
      if (isNum(v.follow_up_cbi_score)) return 1;
      const closed = String(v.trial_arm || "").toLowerCase() === "control" || ["waitlist_control", "declined", "not_completed"].includes(st);
      return closed ? 2 : 0;
    };
    const list = [...(S.person?.linked_interventions || [])].sort((a, b) =>
      (rank(a) - rank(b)) ||
      (rank(a) === 0 ? due(a).localeCompare(due(b)) : due(b).localeCompare(due(a))) ||
      String(b.action_id).localeCompare(String(a.action_id)));
    const cards = list.map((v) => {
      const st = String(v.action_status || "").toLowerCase();
      const control = String(v.trial_arm || "").toLowerCase() === "control" || st === "waitlist_control";
      const out = String(v.outcome_status || ""), ch = v.observed_change;
      const followed = isNum(v.follow_up_cbi_score);
      const tone = /improv/i.test(out) ? "tag--calm" : /worsen/i.test(out) ? "tag--fire" : "tag--ash";
      const reliable = isNum(ch) && isNum(S.rci) && Math.abs(ch) >= S.rci;
      // status stays editable until the follow-up survey has scored it
      const editable = !control && !followed;
      const cur = st === "in_progress" ? "started" : st === "completed" ? "completed" : st === "not_completed" ? "stopped" : "";
      const rule = isNum(S.rci) ? `better if it drops ${f1(S.rci)}+, worse if it rises ${f1(S.rci)}+, else same` : "compared with the next survey";
      const dates = control ? "waitlist control" : `${esc(clean(v.start_date) || "—")} → ${esc(clean(v.follow_up_due_date) || "—")}`;
      return `<article class="rcard">
        <div class="rcard__top"><b class="ellip">${esc(title(v.intervention_type))}</b><span class="tag ${control ? "tag--amber" : st === "completed" ? "tag--calm" : "tag--ash"}">${esc(control ? "control" : title(st))}</span></div>
        <small class="note ellip">${esc(title(v.referral_reason))} · ${esc(v.responsible_owner || "—")}</small>
        <small class="note">${dates}</small>
        <div class="rcard__ba ba-row"><b style="color:${heat(v.baseline_cbi_score)}">${f1(v.baseline_cbi_score)}</b> → <b style="color:${heat(v.follow_up_cbi_score)}">${followed ? f1(v.follow_up_cbi_score) : "…"}</b>
          ${followed ? `<span class="tag ${tone}">${esc(title(out))}</span>` : ""}</div>
        <small class="note">${followed ? `${signed(ch)}${isNum(S.rci) ? ` · ${reliable ? "beyond" : "within"} noise (±${f1(S.rci)})` : ""}` : control ? `no support given; compared after ${esc(clean(v.follow_up_due_date) || "the wait")}` : `result after ${esc(clean(v.follow_up_due_date) || "it ends")}: ${rule}`}</small>
        ${editable ? `<label class="rcard__set">Status<select data-sid="${esc(v.action_id)}">
          ${cur ? "" : `<option value="" selected disabled>${esc(title(st) || "Planned")}</option>`}
          ${["started", "completed", "stopped"].map((o) => `<option value="${o}"${o === cur ? " selected" : ""}>${title(o)}</option>`).join("")}
        </select></label>` : ""}
      </article>`;
    }).join("");
    $("#results").innerHTML = cards || `<p class="empty">${esc(S.person.employee_id)} has no support recorded yet. Log one on the right.</p>`;
  }

  // ================= DATA & MODEL =================
  // ================= model page =================
  // the six stages with this month's live number; shared by the ring and its detail panel
  function frameworkStages() {
    const L = S.loop, c = L.company || {}, m = L.forecast_metrics || {}, im = L.impact || {}, o = im.outcomes || {};
    const pilot = L.randomised_pilot || {}, rule = Object.fromEntries((L.stages || []).map((x) => [x.id, x]));
    const simulated = (L.effects || []).filter((e) => isNum(e.simulation_effect)).length;
    const followed = (o.improved || 0) + (o.no_change || 0) + (o.worsened || 0);
    const pct = (x, y) => (y ? Math.round((100 * x) / y) : 0);
    return [
      { id: "assess", n: "01", name: "Assess", big: `${f1(c.pct_high)}%`, unit: "scored high",
        sub: `${f0(c.employees_scored)} of ${f0(c.employees_with_record)} answered the 7-question CBI work survey. Reference group: ${f1(c.reference?.pct_high)}% high.`, href: "#/" },
      { id: "predict", n: "02", name: "Predict", big: `±${f1(m.model?.mae)}`, unit: "typical error",
        sub: `Next month's score for each person, with a 95% range. "Same as last month" is off by ${f1(m.persistence?.mae)}.`, href: "#/model" },
      { id: "simulate", n: "03", name: "Simulate", big: "500", unit: "paths, 3 mo",
        sub: `No change, overtime −5 h, and ${simulated + (isNum(pilot.difference) ? 1 : 0)} support type(s) with reliable evidence. Shown on each person's page.`, href: "#/people" },
      { id: "intervene", n: "04", name: "Intervene", big: f0(im.delivery?.logged), unit: "support actions",
        sub: `${f0(im.delivery?.completed)} completed. A named owner decides; the model only flags and suggests.`, href: "#/people?status=support_planned,in_support" },
      { id: "verify", n: "05", name: "Verify", big: `${pct(o.improved, followed)}%`, unit: "improved after",
        sub: `${f0(o.improved)} better, ${f0(o.no_change)} same, ${f0(o.worsened)} worse at the next survey. Changes under ±${f1(S.rci)} are treated as noise.`, href: "#/people?status=outcome_improved,outcome_no_change,outcome_worsened" },
      { id: "learn", n: "06", name: "Learn", big: isNum(pilot.difference) ? signed(pilot.difference) : "—", unit: "pts, pilot",
        sub: `Randomised pilot: ${esc(title(pilot.intervention_type || ""))} vs waitlist, 95% CI ${signed(pilot.ci_low)} to ${signed(pilot.ci_high)}. Feeds Simulate.`, href: "#/" },
    ].map((x) => ({ ...x, rule: rule[x.id]?.rule || "", what: rule[x.id]?.what || "" }));
  }

  function renderModelPage() {
    if (!S.loop) return;
    renderRing();
    drawForecastChart();
    renderErrors();
    renderCalibration();
    renderSnap();
  }

  // the loop as a ring: six nodes, arrows between them, learn feeding back into simulate
  function renderRing() {
    const st = frameworkStages(), cx = 230, cy = 196, R = 122;
    S.ringPick = S.ringPick || "assess";
    const pos = st.map((_, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / st.length; return [cx + R * Math.cos(a), cy + R * Math.sin(a), a]; });
    let g = `<defs><marker id="ra" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--ember)"/></marker></defs>`;
    // arcs between nodes
    st.forEach((_, i) => {
      const a0 = pos[i][2] + 0.24, a1 = pos[(i + 1) % st.length][2] - 0.24 + (i === st.length - 1 ? 2 * Math.PI : 0);
      const p = (a) => `${(cx + R * Math.cos(a)).toFixed(1)} ${(cy + R * Math.sin(a)).toFixed(1)}`;
      g += `<path d="M${p(a0)} A${R} ${R} 0 0 1 ${p(a1)}" fill="none" stroke="var(--ember)" stroke-width="2" marker-end="url(#ra)" opacity=".75"/>`;
    });
    // learn -> simulate chord through the middle
    const [lx, ly] = pos[5], [sx, sy] = pos[2];
    g += `<path d="M${lx + 18} ${ly + 16} Q${cx} ${cy + 84} ${sx - 24} ${sy - 4}" fill="none" stroke="var(--ember)" stroke-width="1.5" stroke-dasharray="4 4" marker-end="url(#ra)"/>`;
    g += `<text x="${cx}" y="${cy - 30}" text-anchor="middle" class="ring__c1">every month</text><text x="${cx}" y="${cy - 10}" text-anchor="middle" class="ring__c2">${esc(monthLong(S.loop.period))}</text>`;
    st.forEach((x, i) => {
      const [px, py] = pos[i], on = x.id === S.ringPick;
      const out = 1.48, tx = cx + R * out * Math.cos(pos[i][2]), ty = cy + R * out * Math.sin(pos[i][2]);
      const anchor = Math.abs(tx - cx) < 20 ? "middle" : tx > cx ? "start" : "end";
      const dy = Math.abs(tx - cx) < 20 ? (ty < cy ? -14 : 8) : -6;
      g += `<g class="ring__node ${on ? "is-on" : ""}" data-stage="${x.id}" tabindex="0" role="button" aria-label="${x.name}: ${x.big} ${x.unit}">
        <title>${esc(x.rule)}</title>
        <circle cx="${px}" cy="${py}" r="25"/><text x="${px}" y="${py + 5}" text-anchor="middle" class="ring__n">${x.n}</text>
        <text x="${tx}" y="${ty + dy}" text-anchor="${anchor}" class="ring__name">${x.name}</text>
        <text x="${tx}" y="${ty + dy + 22}" text-anchor="${anchor}" class="ring__big">${x.big}</text>
        <text x="${tx}" y="${ty + dy + 36}" text-anchor="${anchor}" class="ring__unit">${x.unit}</text></g>`;
    });
    $("#ring").innerHTML = g;
    const pick = st.find((x) => x.id === S.ringPick);
    $("#ringinfo").innerHTML = `<p class="tile__label">${pick.n} ${pick.name} · ${esc(pick.what)}</p><p class="note">${pick.sub}</p><p class="tile__fine">Rule: ${esc(pick.rule)}</p><a class="more" href="${pick.href}">see it →</a>`;
    $$("#ring .ring__node").forEach((n) => {
      const go = () => { S.ringPick = n.dataset.stage; renderRing(); };
      n.addEventListener("click", go);
      n.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  }

  // company average each month: what happened, the forecast made the month before, and "same as last month"
  function drawForecastChart() {
    const svg = $("#fchart");
    if (!svg || svg.closest(".page").hidden) return;
    const pts = (S.fc?.monthly_points || []).filter((p) => isNum(p.future_actual_target_t1));
    const box = svg.getBoundingClientRect(), w = Math.max(320, box.width), h = Math.max(160, box.height);
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    if (!pts.length) { svg.innerHTML = `<text x="16" y="24" class="note">No held-out months yet.</text>`; return; }
    const rows = pts.map((p) => ({ x: nextPeriod(p.period), a: p.future_actual_target_t1, f: p.forecast_predicted_t1, b: p.persistence_baseline_t1 }));
    const nx = S.fc.next_projection;
    const vals = rows.flatMap((r) => [r.a, r.f, r.b]).concat(isNum(nx?.projected_mean_cbi) ? [nx.projected_mean_cbi] : []).filter(isNum);
    const lo = Math.floor(Math.min(...vals) - 1.5), hi = Math.ceil(Math.max(...vals) + 1.5);
    const pad = { l: 34, r: 16, t: 10, b: 24 }, n = rows.length + (nx ? 1 : 0);
    const X = (i) => pad.l + (i * (w - pad.l - pad.r)) / Math.max(1, n - 1), Y = (v) => pad.t + ((hi - v) * (h - pad.t - pad.b)) / (hi - lo);
    const line = (k) => rows.map((r, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(r[k]).toFixed(1)}`).join("");
    let g = "";
    for (let v = Math.ceil(lo); v <= hi; v += Math.max(1, Math.round((hi - lo) / 4))) g += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end" class="axis">${v}</text>`;
    rows.forEach((r, i) => { if (i % 2 === 0 || i === rows.length - 1) g += `<text x="${X(i)}" y="${h - 6}" text-anchor="middle" class="axis">${new Date(r.x + "-01T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" })}</text>`; });
    g += `<path d="${line("b")}" fill="none" stroke="var(--ash-2)" stroke-width="1.5" stroke-dasharray="4 4"/>`;
    g += `<path d="${line("f")}" fill="none" stroke="var(--ember)" stroke-width="2.5"/>`;
    g += `<path d="${line("a")}" fill="none" stroke="var(--ink)" stroke-width="2"/>`;
    rows.forEach((r, i) => { g += `<circle cx="${X(i)}" cy="${Y(r.a)}" r="3" fill="var(--ink)"><title>${monthLong(r.x)}: actual ${f1(r.a)}, forecast ${f1(r.f)}, same-as-last ${f1(r.b)}</title></circle>`; });
    if (isNum(nx?.projected_mean_cbi)) {
      const i = rows.length;
      g += `<path d="M${X(i - 1)} ${Y(rows[i - 1].a)} L${X(i)} ${Y(nx.projected_mean_cbi)}" stroke="var(--ember)" stroke-width="2" stroke-dasharray="3 3" fill="none"/>
        <circle cx="${X(i)}" cy="${Y(nx.projected_mean_cbi)}" r="5" fill="var(--paper)" stroke="var(--ember)" stroke-width="2"><title>${monthLong(nx.forecast_period)} forecast ${f1(nx.projected_mean_cbi)}</title></circle>
        <text x="${X(i)}" y="${h - 6}" text-anchor="middle" class="axis" style="fill:var(--ember)">${new Date(nx.forecast_period + "-01T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" })}?</text>`;
    }
    svg.innerHTML = g;
    $("#fnote").textContent = `${S.fc.leakage_safeguard || ""} Open circle: next month, not yet surveyed.`;
  }

  // error as bars (shorter is better), range coverage as a filled meter
  function renderErrors() {
    const m = S.loop.forecast_metrics || {}, mm = m.model || {}, pm = m.persistence || {};
    const top = Math.max(mm.mae || 0, pm.mae || 0) * 1.15 || 1;
    const bar = (label, v, cls) => `<div class="errbar"><span>${label}</span><span class="errbar__track"><i class="${cls}" style="width:${(100 * (v || 0)) / top}%"></i></span><b>${f1(v)}</b></div>`;
    const better = isNum(mm.mae) && isNum(pm.mae) ? Math.round((100 * (pm.mae - mm.mae)) / pm.mae) : null;
    const cov = isNum(m.interval_95_coverage) ? 100 * m.interval_95_coverage : null;
    $("#modelkpis").innerHTML = `
      <p class="tile__label">typical error, points (shorter is better)</p>
      ${bar("BurnoutIQ", mm.mae, "is-model")}${bar("Same as last month", pm.mae, "is-base")}
      <p class="errline"><b>${isNum(better) ? better + "%" : "—"}</b> smaller error on ${f0(m.test_employees)} people the model never saw</p>
      <p class="tile__label">95% range: how often the real score fell inside</p>
      <div class="meter"><i style="width:${cov || 0}%"></i><em style="left:95%"></em></div>
      <p class="errline"><b>${isNum(cov) ? cov.toFixed(1) + "%" : "—"}</b> inside ±${f1(m.interval_95_halfwidth)} points (target 95%)</p>`;
  }

  // calibration as a dot plot: forecast (ring) and actual (dot) per department
  function renderCalibration() {
    const rows = S.loop.calibration || [];
    const vals = rows.flatMap((r) => [r.mean_forecast, r.mean_actual]).filter(isNum);
    const lo = Math.floor(Math.min(...vals, 20) - 2), hi = Math.ceil(Math.max(...vals, 40) + 2), P = (v) => `${(100 * (v - lo)) / (hi - lo)}%`;
    $("#calibration").innerHTML = rows.map((r) => `<div class="cdot" title="${esc(r.department)}: forecast ${f1(r.mean_forecast)}, actual ${f1(r.mean_actual)}, ${f0(r.n)} forecasts">
        <span class="ellip">${esc(r.department)}</span>
        <span class="cdot__track"><i class="cdot__f" style="left:${P(r.mean_forecast)}"></i><i class="cdot__a" style="left:${P(r.mean_actual)}"></i></span>
        <span class="num ${r.needs_recalibration ? "is-off" : ""}">${signed(r.bias)}</span></div>`).join("") +
      `<div class="cdot cdot--axis"><span></span><span class="cdot__track"><small style="left:0">${lo}</small><small style="right:0">${hi}</small></span><span></span></div>`;
    $("#forecastnote").textContent = "Ring = average forecast, dot = average actual. Close together means no department is systematically over- or under-forecast.";
  }

  // the team's original 0–10 model: one moment, from one survey, separate from the monthly loop
  async function renderSnap() {
    if (!S.lab) {
      try { S.lab = await api("/api/model-lab"); } catch { $("#snap").innerHTML = `<p class="note">Model lab offline.</p>`; return; }
    }
    const t = S.lab.tasks?.task_a_regression || {}, best = (t.rankings || []).find((r) => r.best) || (t.rankings || [])[0] || {};
    const fi = (S.lab.feature_importance || []).slice(0, 5), top = Math.max(...fi.map((f) => f.importance), 0.01);
    $("#snap").innerHTML = `
      <div class="snap__kpis"><div><b>${isNum(best.test_r2) ? best.test_r2.toFixed(2) : "—"}</b><small>R² on held-out records</small></div><div><b>±${isNum(best.test_mae) ? best.test_mae.toFixed(2) : "—"}</b><small>error on a 0–10 scale</small></div></div>
      <p class="tile__label">what drives the score most</p>
      ${fi.map((f) => `<div class="errbar"><span class="ellip">${esc(f.feature)}</span><span class="errbar__track"><i class="is-snap" style="width:${(100 * f.importance) / top}%"></i></span><b>${Math.round(100 * f.importance)}%</b></div>`).join("")}
      <p class="tile__fine">${esc(best.name || "")} on ${esc(t.dataset_source || "")}. Scores one moment; the loop above follows people month to month. Stress is self-reported and close to the target, so it carries most of the weight.</p>`;
  }

  // This month: is the burnout about the person, or about their whole department?
  function renderQuad() {
    const c = S.loop.company || {}, q = c.quadrants || {};
    // 2x2: person flagged or not × department running hot or not; circle area = number of people
    const keys = ["healthy", "systemic", "individual", "individual_and_systemic"];
    const max = Math.max(...keys.map((k) => q[k] || 0), 1);
    const cell = (k, tone, act) => {
      const n = q[k] || 0, d = Math.max(6, 34 * Math.sqrt(n / max));
      return `<a class="q2 q2--${tone}" href="#/people?quadrant=${k}" title="${f0(n)} people · ${esc(act)} · click to see them"><span class="q2__dot" style="width:${d}px;height:${d}px"></span><b>${f0(n)}</b><small>${esc(act)}</small></a>`;
    };
    $("#quad").innerHTML = `
      <span class="q2__corner"></span><span class="q2__col">department normal</span><span class="q2__col">department running hot</span>
      <span class="q2__rowh">person fine</span>${cell("healthy", "calm", "keep monitoring")}${cell("systemic", "amber", "fix team workload early")}
      <span class="q2__rowh">person flagged</span>${cell("individual", "fire", "personal support")}${cell("individual_and_systemic", "burn", "support + fix team")}
      <p class="tile__fine q2__note">${f0(q.no_score || 0)} people have no score this month. "Running hot" = more high scores than chance would give.</p>`;
  }

  // connectors: CSV upload works today; the rest, including an MCP connector, are a future update
  const CONNECTORS = {
    mcp: ["MCP connector", "An MCP (Model Context Protocol) server for BurnoutIQ. HR tools, survey platforms or an AI assistant could send each month's files through it, and ask the loop questions such as \"who needs a follow-up this week?\". It would write the same three files the upload uses, so the rest of the loop stays as it is."],
    hr: ["HR system connector", "Would export employees.csv (pseudonymous IDs, department, team, role, contracted hours) once a month."],
    survey: ["Survey tool connector", "Would send each month's CBI work answers straight into monthly.csv."],
    time: ["Timesheets connector", "Would add hours, overtime and meeting time to monthly.csv."],
    cases: ["Case notes connector", "Would send support actions and their status into interventions.csv."],
  };
  function wireConnectors() {
    $("#connectors").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-conn]");
      if (!b) return;
      if (b.dataset.conn === "csv") {
        (locked() ? $(".upload-block") : $("#add-data")).scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
        return;
      }
      const [name, text] = CONNECTORS[b.dataset.conn];
      await ask({ label: "future update", title: `${name}: coming soon`, cancel: "OK, I'll wait", okDisabled: true,
        body: `<div class="soon"><span class="soon__dot"></span><p>${esc(text)}</p></div><p class="note">Until then, upload the CSV files each month (or a whole year at once) from this page.</p>` });
    });
  }

  function wireData() {
    $$(".drop__tpl").forEach((a) => {
      a.href = `/templates/${a.dataset.tpl}`;
      a.setAttribute("download", a.dataset.tpl);
      a.addEventListener("click", (e) => e.stopPropagation());
    });
    $$(".drop").forEach((drop) => {
      const input = drop.querySelector("input");
      const state = drop.querySelector(".drop__state");
      const initial = state.textContent;
      const show = () => {
        const f = input.files[0];
        drop.classList.toggle("has-file", !!f);
        state.textContent = f ? `${f.name} · ${(f.size / 1024).toFixed(0)} KB` : initial;
      };
      input.addEventListener("change", show);
      ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.add("is-drag")));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("is-drag")));
    });
    renderLevels(null);
    $("#upload").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      S.checked = fd;
      if (!fd.get("employees")?.size || !fd.get("monthly")?.size) { toast("employees.csv and monthly.csv are required."); return; }
      const btn = e.target.querySelector(".btn");
      btn.disabled = true; btn.textContent = "Checking…";
      try {
        renderReport(await api("/data/check", { method: "POST", body: fd }));
      } catch (err) {
        renderReport({ ok: false, error: err.message });
      } finally {
        btn.disabled = false; btn.textContent = "Check files";
      }
    });
    $$("#start [data-start]").forEach((b) => b.addEventListener("click", () => monthAction(b.dataset.start)));
    // add months: one monthly.csv holding a month or a whole year, always after the latest loaded month
    $("#addmonth-file").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      e.target.value = "";
      if (f) await addData(f);
    });
    $("#add-data").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const m = fd.get("monthly"), iv = fd.get("interventions");
      if (!m?.size) { toast("Choose the monthly CSV first."); return; }
      if (await addData(m, iv?.size ? iv : null)) e.target.reset();
    });
    $("#add-data").addEventListener("change", (e) => {
      const drop = e.target.closest(".drop");
      if (!drop) return;
      const f = e.target.files[0], st = drop.querySelector(".drop__state");
      drop.classList.toggle("has-file", !!f);
      st.textContent = f ? `${f.name} · ${(f.size / 1024).toFixed(0)} KB` : st.dataset.initial;
    });
    $("#add-data").addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (b) { e.preventDefault(); monthAction(b.dataset.act); }
      if (e.target.closest("[data-replace]")) { document.body.classList.add("show-replace"); $(".upload-block").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }); }
    });
  }
  function renderLevels(lvl) {
    $("#levels").innerHTML = `
      <div class="level ${lvl >= 1 ? "is-on" : ""}"><b>Level 1 · CBI answers</b><span>Runs Assess and Verify</span></div>
      <div class="level ${lvl >= 2 ? "is-on" : ""}"><b>Level 2 · + work data</b><span>Also runs Predict and Simulate</span></div>`;
  }
  function renderReport(r) {
    const box = $("#report");
    box.querySelectorAll(".checked").forEach((n) => n.remove());
    renderLevels(r.ok ? r.level : null);
    const div = document.createElement("div");
    div.className = "checked";
    if (!r.ok) {
      div.innerHTML = `<p class="tile__label" style="color:var(--flame)">Files not usable</p><p class="note">${esc(r.error)}</p>`;
    } else {
      const c = r.counts || {};
      div.innerHTML = `
        <p class="tile__label">${r.issues.length ? `${r.issues.length} issue${r.issues.length > 1 ? "s" : ""} fixed or dropped` : "No issues found"}</p>
        <p class="note">${f0(c.employees)} employees · ${f0(c.monthly)} employee-months (${esc(r.periods?.[0] || "—")} to ${esc(r.periods?.[1] || "—")}) · ${f0(c.interventions)} support actions. Stages your data can run: <b>${esc((r.stages || []).join(", "))}</b>.</p>
        ${r.issues.length ? `<ul class="issues">${r.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
        <button type="button" class="btn" id="run-loop">Run the loop on these files</button>
        <p class="tile__fine">The files replace the demo data in memory only; nothing is saved on the server. Add later months from the month bar.</p>`;
    }
    box.prepend(div);
    const run = $("#run-loop");
    if (run) run.addEventListener("click", async () => {
      const c = r.counts || {}, months = monthsBetween(r.periods?.[0], r.periods?.[1]);
      const name = user()?.name || "your company";
      const ok = await ask({
        title: `Load ${name}'s data?`,
        body: facts([["Employees", f0(c.employees)], ["Surveys", `${f0(c.monthly)} employee-months`],
                     ["Months", `${monthLong(r.periods?.[0])} – ${monthLong(r.periods?.[1])} (${months.length})`],
                     ["Support actions", f0(c.interventions)], ["Replaces", S.loop ? `${S.loop.source?.kind === "upload" ? "the files loaded now" : "the demo data"}` : "—"]]) +
          `<p class="note">The loop is trained from scratch on these files. They stay in memory on this server and are removed when you sign out.</p>`,
        ok: "Load and run the loop",
      });
      if (!ok) return;
      run.disabled = true;
      const anim = progress({ title: `Loading ${name}`, label: "company data", months, fresh: months,
        steps: ["Reading the three files", "Checking IDs, months and answers", "Scoring every survey", "Training the forecast", "Running simulate and verify"] });
      try {
        await post("/api/loop/upload", S.checked);
        document.body.classList.remove("show-replace");
        await loadData();
        anim.done(`${f0(S.loop.source?.employees)} people · ${monthLong(S.loop.periods[0])} – ${monthLong(S.loop.periods.slice(-1)[0])} are loaded and the loop has run.`,
          [["#/", "Open this month →"], ["#/data", "Stay here"]]);
      } catch (err) {
        anim.fail(err.message);
        run.disabled = false;
      }
    });
  }

  // ================= decoration =================
  function cycleWord() {
    const words = ["fire", "burnout", "ash"];
    const node = $("#cycle");
    let i = 0;
    if (reduced || !node) return;
    setInterval(() => {
      node.classList.add("is-swap");
      setTimeout(() => { i = (i + 1) % words.length; node.textContent = words[i]; node.classList.remove("is-swap"); }, 350);
    }, 2800);
  }
  function embers(canvas, density) {
    if (reduced || !canvas) return;
    const ctx = canvas.getContext("2d");
    let w = 0, h = 0, parts = [], visible = false;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const colors = ["255,180,90", "255,122,46", "226,98,27", "196,43,28"];
    const spawn = (y) => ({
      x: Math.random() * w, y: y ?? h + Math.random() * 40, r: 0.6 + Math.random() * 2.2,
      vy: 0.25 + Math.random() * 0.9, vx: (Math.random() - 0.5) * 0.3, life: 0.4 + Math.random() * 0.6,
      c: colors[(Math.random() * colors.length) | 0], ph: Math.random() * 6.28,
    });
    function size() {
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return;
      w = r.width; h = r.height;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      parts = Array.from({ length: Math.round((w * density) / 30) }, () => spawn(Math.random() * h));
    }
    function tick(t) {
      if (!visible) return;
      ctx.clearRect(0, 0, w, h);
      for (const p of parts) {
        p.y -= p.vy; p.x += p.vx + Math.sin(t / 900 + p.ph) * 0.25;
        const a = Math.max(0, Math.min(1, p.y / h)) * p.life * (0.6 + 0.4 * Math.sin(t / 180 + p.ph));
        ctx.beginPath();
        ctx.fillStyle = `rgba(${p.c},${a})`;
        ctx.shadowColor = `rgba(${p.c},${a})`; ctx.shadowBlur = 8;
        ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
        if (p.y < -10) Object.assign(p, spawn());
      }
      requestAnimationFrame(tick);
    }
    new ResizeObserver(size).observe(canvas);
    new IntersectionObserver(([e]) => {
      const was = visible; visible = e.isIntersecting;
      if (visible && !was) { if (!w) size(); requestAnimationFrame(tick); }
    }).observe(canvas);
  }

  // ================= router =================
  const PAGES = { "": "assess", assess: "assess", analytics: "assess", people: "people", employees: "employee", model: "model", data: "data", interventions: "assess" };
  const NAV_OF = { employee: "people", interventions: "assess", analytics: "assess" };
  let firstEmployee = null;
  // ================= example survey (Data page) =================
  // CBI work-related subscale: items 1-3 answered on a degree scale, 4-7 on a frequency scale; item 7 is reversed
  const SURVEY = [
    ["cbi_w1", "Is your work emotionally exhausting?", "degree"],
    ["cbi_w2", "Do you feel burnt out because of your work?", "degree"],
    ["cbi_w3", "Does your work frustrate you?", "degree"],
    ["cbi_w4", "Do you feel worn out at the end of the working day?", "freq"],
    ["cbi_w5", "Are you exhausted in the morning at the thought of another day at work?", "freq"],
    ["cbi_w6", "Do you feel that every working hour is tiring for you?", "freq"],
    ["cbi_w7", "Do you have enough energy for family and friends during leisure time?", "freq"],
  ];
  const SCALE = {
    degree: [["To a very high degree", 100], ["To a high degree", 75], ["Somewhat", 50], ["To a low degree", 25], ["To a very low degree", 0]],
    freq: [["Always", 100], ["Often", 75], ["Sometimes", 50], ["Seldom", 25], ["Never / almost never", 0]],
  };
  function openSurvey() {
    const depts = (S.loop?.divisions || []).map((d) => d.department).sort();
    $("#survey-form").innerHTML = SURVEY.map(([id, q, kind], i) => `
      <fieldset class="sq"><legend><b>${i + 1}</b>${esc(q)}</legend>
        <div class="sq__opts">${SCALE[kind].map(([t, v]) => `<label><input type="radio" name="${id}" value="${v}" required><span>${esc(t)}</span></label>`).join("")}</div>
      </fieldset>`).join("") + `
      <fieldset class="sq sq--work"><legend><b>+</b>About your work this month <small>(from timesheets in a real setup)</small></legend>
        <label class="sq__range">Hours worked per week <output id="sq-hours-out">40 h</output>
          <input type="range" name="hours" min="30" max="70" step="1" value="40"></label>
        <label class="sq__dept">Department <select name="department">${depts.map((d) => `<option>${esc(d)}</option>`).join("")}</select></label>
      </fieldset>
      <div class="survey__acts"><button type="submit" class="btn">See my score</button><button type="reset" class="btn btn--ghost">Clear</button></div>`;
    $("#survey-result").innerHTML = `<p class="tile__label">your result</p><p class="note">Answer the questions and press <b>See my score</b>. The score is worked out the same way as the real monthly data. Nothing is saved.</p>`;
    S.tried = null;
    $("#survey").showModal();
  }
  async function submitSurvey(e) {
    e.preventDefault();
    const fd = new FormData(e.target), answers = Object.fromEntries(SURVEY.map(([id]) => [id, Number(fd.get(id))]));
    try {
      S.tried = await post("/api/loop/try-survey", { answers, hours: Number(fd.get("hours")), department: fd.get("department") });
      S.tried.answers = answers;
      drawSurveyResult();
    } catch (err) { toast(err.message); }
  }
  // the score comes from the answers; the slider moves only the forecast (read from the curve, no new request)
  function drawSurveyResult() {
    const r = S.tried;
    if (!r) return;
    const hours = Number($("#survey-form").elements.hours.value);
    const pt = r.by_hours.reduce((a, b) => (Math.abs(b.hours - hours) < Math.abs(a.hours - hours) ? b : a));
    const W = 300, H = 120, pad = 22, xs = r.by_hours.map((d) => d.hours), ys = r.by_hours.map((d) => d.forecast);
    const lo = Math.min(...ys, r.score) - 4, hi = Math.max(...ys, r.score) + 4;
    const X = (h) => pad + ((h - xs[0]) * (W - pad * 2)) / (xs[xs.length - 1] - xs[0]), Y = (v) => 8 + ((hi - v) * (H - 30)) / (hi - lo);
    const line = r.by_hours.map((d, i) => `${i ? "L" : "M"}${X(d.hours).toFixed(1)} ${Y(d.forecast).toFixed(1)}`).join("");
    const lvl = { very_high: "very high", high: "high", normal: "normal" }[r.level] || r.level;
    $("#survey-result").innerHTML = `
      <p class="tile__label">your burnout score (CBI work, 0–100)</p>
      <div class="sr__score"><b style="color:${heat(r.score)}">${f1(r.score)}</b><span>${levelTag(r.score)}</span></div>
      <div class="sr__gauge"><i style="left:${r.score}%"></i><em style="left:50%"></em><em style="left:65%"></em></div>
      <div class="sr__ticks"><span>0 calm</span><span style="left:50%">50 high</span><span style="left:65%">65 very high</span><span style="right:0">100</span></div>
      <p class="note">${lvl === "normal" ? "Below the line where the loop would start to look closer." : "High enough that the loop would watch this person; two high months in a row would flag them."}</p>
      <p class="tile__label">next month's forecast · move the hours slider</p>
      <div class="sr__fc"><b>${f1(pt.forecast)}</b><span>at ${pt.hours} h/week · range ±${f1(r.interval_95)}</span></div>
      <svg class="sr__chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Forecast by working hours">
        <line x1="${pad}" x2="${W - pad}" y1="${Y(50)}" y2="${Y(50)}" class="sr__fifty"/>
        <path d="${line}" class="sr__line"/>
        <line x1="${X(pt.hours)}" x2="${X(pt.hours)}" y1="6" y2="${H - 22}" class="sr__cursor"/>
        <circle cx="${X(pt.hours)}" cy="${Y(pt.forecast)}" r="5" class="sr__dot"/>
        <text x="${pad}" y="${H - 6}" class="sr__ax">30 h</text><text x="${W / 2}" y="${H - 6}" text-anchor="middle" class="sr__ax">50 h</text><text x="${W - pad}" y="${H - 6}" text-anchor="end" class="sr__ax">70 h</text>
      </svg>
      <p class="tile__fine"><b>Why hours don't change the score:</b> burnout is measured by the answers, not guessed from hours. Hours feed the forecast because, in this data, longer weeks go with higher scores the next month (an association, not proof of cause). The forecast also pulls towards the average, which is why it can sit below today's score.</p>
      <button type="button" class="btn btn--small btn--ghost" id="survey-csv">Download my answers as a monthly.csv row</button>`;
    $("#survey-csv").addEventListener("click", downloadAnswers);
  }
  function saveFile(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  // the blank survey as a standalone page that can be printed or shared
  function downloadBlankSurvey() {
    const q = SURVEY.map(([, text, kind], i) => `<li><p>${i + 1}. ${esc(text)}</p><p>${SCALE[kind].map(([t]) => `&#9744; ${esc(t)}`).join(" &nbsp; ")}</p></li>`).join("");
    saveFile("burnoutiq_monthly_survey.html", `<!doctype html><meta charset="utf-8"><title>Monthly work survey</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#1d1d1b}li{margin:0 0 18px}li p{margin:2px 0}h1{font-size:22px}</style>
<h1>Monthly work survey (Copenhagen Burnout Inventory, work-related)</h1>
<p>Employee ID: ____________ &nbsp; Month: ____________</p>
<p>Think about the last four weeks. Tick one answer per question.</p><ol style="list-style:none;padding:0">${q}</ol>
<p>Hours worked per week (from timesheets): ________</p>
<p style="font-size:12px;color:#555">Scoring: each answer is 0, 25, 50, 75 or 100; question 7 is reversed; the score is the average of at least 4 answers. 50 or more is "high".</p>`, "text/html");
  }
  function downloadAnswers() {
    const r = S.tried, period = nextPeriod(S.loop.periods.slice(-1)[0]);
    const cols = ["employee_id", "period", ...SURVEY.map(([id]) => id), "work_hours_per_week"];
    const row = ["SAMPLE-001", period, ...SURVEY.map(([id]) => r.answers[id]), Number($("#survey-form").elements.hours.value)];
    saveFile("monthly_sample.csv", `${cols.join(",")}\n${row.join(",")}\n`, "text/csv");
  }
  function wireSurvey() {
    document.addEventListener("click", (e) => { if (e.target.closest("[data-survey]")) openSurvey(); });
    $("#survey-form").addEventListener("submit", submitSurvey);
    $("#survey-form").addEventListener("input", (e) => {
      if (e.target.name === "hours") { $("#sq-hours-out").textContent = `${e.target.value} h`; drawSurveyResult(); }
    });
    $("#survey-form").addEventListener("reset", () => setTimeout(() => { $("#sq-hours-out").textContent = "40 h"; S.tried = null; openSurvey(); }));
    $("#survey-blank").addEventListener("click", downloadBlankSurvey);
  }

  // ================= sign in =================
  // a demo sign-in with no passwords: it only picks which data this browser looks at
  const USER_KEY = "biq-user";
  function user() { try { return JSON.parse(sessionStorage.getItem(USER_KEY) || "null"); } catch { return null; } }
  function setUser(u) { try { u ? sessionStorage.setItem(USER_KEY, JSON.stringify(u)) : sessionStorage.removeItem(USER_KEY); } catch { /* private mode */ } }
  function locked() { const u = user(); return !u || (u.kind === "company" && S.loop?.source?.kind !== "upload"); }
  function demoFile(p) { return `/templates/demo/monthly_${p}.csv`; }

  function renderAccount() {
    const u = user(), src = S.loop?.source || {}, per = S.loop?.periods || [];
    document.body.classList.toggle("signed-out", !u);
    document.body.classList.toggle("user-demo", u?.kind === "demo");
    document.body.classList.toggle("user-company", u?.kind === "company");
    document.body.classList.toggle("is-locked", locked());
    $("#acct").hidden = !u;
    $("#acct").innerHTML = u ? `<span class="acct__who"><small>${u.kind === "demo" ? "demo" : "company"}</small>${esc(u.name)}</span><button type="button" class="btn btn--small btn--ghost" data-signout>Sign out</button>` : "";
    const range = per.length ? `${esc(monthLong(per[0]))} – ${esc(monthLong(per[per.length - 1]))}` : "";
    $("#start").innerHTML = !u ? "" : locked()
      ? `<p class="note">Signed in as <b>${esc(u.name)}</b>. Add your three files below to run the loop.</p>`
      : `<p class="note">Signed in as <b>${esc(u.name)}</b> · ${f0(src.employees)} people · ${range}</p><a class="btn" href="#/">Open this month →</a>`;
    renderAddData();
  }
  // add data, every month or once a year: one monthly.csv (plus support actions if any) after the latest month
  function renderAddData() {
    const box = $("#add-data"), src = S.loop?.source || {};
    if (locked() || !S.loop) { box.innerHTML = ""; return; }
    const per = S.loop.periods, latest = per[per.length - 1], nxt = nextPeriod(latest), demo = src.kind === "demo_live";
    const offer = demo && src.next_period
      ? `<p class="note">Demo: the ${esc(monthLong(src.next_period))} surveys are ready as a file. <a href="${demoFile(src.next_period)}" download>Download monthly_${esc(src.next_period)}.csv</a>, then drop it below.</p>`
      : demo ? `<p class="note">Demo year complete · sign out to restart from November 2025.</p>` : "";
    box.innerHTML = `
      <div class="tile__row"><h2 class="tile__title"><span>add data · every month or year</span>Add new months</h2>
        ${src.kind === "upload" ? `<button type="button" class="more" data-replace>replace all files</button>` : ""}</div>
      <p class="addline"><b>${esc(monthLong(per[0]))} – ${esc(monthLong(latest))}</b> loaded · next expected <b>${esc(monthLong(nxt))}</b></p>
      ${offer}
      <form class="add-form" autocomplete="off">
        <label class="drop drop--small"><span class="drop__name">monthly.csv</span><span class="drop__state" data-initial="one month or a year · required">one month or a year · required</span><button type="button" class="drop__x" aria-label="Remove this file" title="Remove this file">×</button><input type="file" name="monthly" accept=".csv"></label>
        <label class="drop drop--small"><span class="drop__name">interventions.csv</span><span class="drop__state" data-initial="new support actions · optional">new support actions · optional</span><button type="button" class="drop__x" aria-label="Remove this file" title="Remove this file">×</button><input type="file" name="interventions" accept=".csv"></label>
        <div class="formacts"><button type="submit" class="btn">Review and add</button><button type="reset" class="btn btn--ghost">Discard</button></div>
      </form>`;
  }

  // a quick look inside the CSV before anything is sent, for the confirmation
  async function readCsvSummary(file) {
    const lines = (await file.text()).split(/\r?\n/).filter((l) => l.trim());
    const cell = (v) => String(v || "").trim().replace(/^"|"$/g, "");
    const head = (lines[0] || "").split(",").map(cell);
    const pi = head.indexOf("period"), ei = head.indexOf("employee_id"), si = head.findIndex((h) => /^cbi_q?1\b|^cbi_work_q1|^cbi_/.test(h));
    const periods = new Set(), people = new Set();
    for (const l of lines.slice(1)) {
      const c = l.split(",");
      if (pi >= 0 && cell(c[pi])) periods.add(cell(c[pi]).slice(0, 7));
      if (ei >= 0 && cell(c[ei])) people.add(cell(c[ei]));
    }
    return { rows: lines.length - 1, periods: [...periods].sort(), people: people.size, hasPeriod: pi >= 0, hasCbi: si >= 0 };
  }
  function monthsBetween(a, b) {
    const out = [];
    for (let p = a; p && b && p <= b && out.length < 120; p = nextPeriod(p)) out.push(p);
    return out;
  }
  const facts = (rows) => `<dl class="confirm__facts">${rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}</dl>`;

  function ask({ title, body, ok, okDisabled, label, cancel }) {
    const d = $("#confirm");
    $("#confirm-cancel").textContent = cancel || "Cancel";
    $("#confirm-label").textContent = label || "please confirm";
    $("#confirm-title").textContent = title;
    $("#confirm-body").innerHTML = body;
    $("#confirm-ok").textContent = ok;
    $("#confirm-ok").hidden = !!okDisabled;
    d.returnValue = "";
    d.showModal();
    return new Promise((res) => d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true }));
  }

  async function addData(monthly, interventions) {
    if (!S.loop) return false;
    const latest = S.loop.periods.slice(-1)[0];
    let sum;
    try { sum = await readCsvSummary(monthly); } catch { toast("Could not read that file."); return false; }
    const fresh = sum.periods.filter((p) => p > latest), old = sum.periods.filter((p) => p <= latest);
    const gap = fresh.length && fresh[0] !== nextPeriod(latest) ? `Note: ${monthLong(nextPeriod(latest))} is missing, so the file starts after a gap.` : "";
    const bad = !sum.hasPeriod ? "The file has no period column (YYYY-MM), so it is not a monthly.csv."
      : !sum.rows ? "The file has no rows."
      : old.length ? `It holds months that are already loaded (${old.map(monthLong).join(", ")}). Only months after ${monthLong(latest)} can be added.` : "";
    const span = fresh.length === 1 ? monthLong(fresh[0]) : fresh.length ? `${monthLong(fresh[0])} – ${monthLong(fresh[fresh.length - 1])}` : "—";
    const ok = await ask({
      title: bad ? "This file can't be added" : `Add ${span}?`,
      label: bad ? "check the file" : `${fresh.length} new month${fresh.length > 1 ? "s" : ""}`,
      body: facts([["File", `${esc(monthly.name)} · ${(monthly.size / 1024).toFixed(0)} KB`], ["Surveys", `${f0(sum.rows)} rows · ${f0(sum.people)} people`],
                   ["Months in file", esc(span)], ["Loaded now", `${esc(monthLong(S.loop.periods[0]))} – ${esc(monthLong(latest))}`],
                   ["Support actions", interventions ? esc(interventions.name) : "none added"]]) +
        (bad ? `<p class="confirm__warn">${esc(bad)}</p>`
             : `${gap ? `<p class="confirm__warn">${esc(gap)}</p>` : ""}<p class="note">Before reading the new scores, the model forecasts ${esc(monthLong(fresh[0]))} for everyone, then compares. The model is then refit on every month.</p>`),
      ok: `Add ${fresh.length} month${fresh.length > 1 ? "s" : ""}`, okDisabled: !!bad,
    });
    if (!ok) return false;
    const fd = new FormData();
    fd.append("monthly", monthly);
    if (interventions) fd.append("interventions", interventions);
    const before = S.loop.periods.slice(-Math.max(1, 12 - fresh.length));
    const anim = progress({ title: `Adding ${span}`, label: "new data", months: [...before, ...fresh], fresh,
      steps: [`Reading ${f0(sum.rows)} surveys`, `Forecasting ${monthLong(fresh[0])} before looking`, "Scoring the new answers", "Refitting the forecast on every month", "Comparing forecast with what came in"] });
    try {
      await post("/api/loop/add-month", fd);
      await loadData();
      const c = S.loop.check;
      anim.done(c && isNum(c.mae)
        ? `The forecast was off by <b>${f1(c.mae)}</b> points on average, and <b>${f1(c.inside_range_pct)}%</b> of ${f0(c.n)} people landed inside their range.`
        : `${esc(span)} is loaded.`,
        [["#/data", "See the forecast check"], ["#/", "Open this month →"]]);
      return true;
    } catch (err) {
      anim.fail(err.message);
      return false;
    }
  }

  // motion while data loads: the months fill in one by one and each step ticks off; the server does it in one call
  function progress({ title, label, months, fresh, steps }) {
    const o = $("#adding"), isNew = new Set(fresh);
    const short = (p) => new Date(p + "-01T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" });
    $("#adding-label").textContent = label;
    $("#adding-title").textContent = title;
    let k = 0;
    $("#adding-months").innerHTML = months.slice(-12).map((p) => `<span class="mcell ${isNew.has(p) ? "is-new" : ""}" style="--i:${isNew.has(p) ? k++ : 0}">
      <i></i><small>${short(p)}${p.endsWith("-01") || p === months[0] ? ` ’${p.slice(2, 4)}` : ""}</small></span>`).join("");
    $("#adding-steps").innerHTML = steps.map((t) => `<li><i></i>${esc(t)}</li>`).join("");
    $("#adding-result").innerHTML = "";
    o.classList.remove("is-done", "is-fail");
    o.hidden = false;
    requestAnimationFrame(() => o.classList.add("is-on"));
    const li = $$("#adding-steps li");
    let i = 0;
    li[0]?.classList.add("is-run");
    const tick = setInterval(() => {
      if (i >= li.length - 2) return;
      li[i].classList.replace("is-run", "is-ok");
      li[++i].classList.add("is-run");
    }, 1500);
    const close = () => {
      o.classList.remove("is-on");
      setTimeout(() => { o.hidden = true; }, 300);
    };
    const finish = (cls, html, links) => {
      clearInterval(tick);
      li.forEach((n) => { n.classList.remove("is-run"); if (cls === "is-done") n.classList.add("is-ok"); });
      o.classList.add(cls);
      $("#adding-result").innerHTML = `<p>${html}</p><div class="start">${links.map(([href, t], j) => `<a class="btn ${j ? "btn--ghost" : ""}" href="${href}" data-close>${t}</a>`).join("")}</div>`;
      $$("#adding-result [data-close]").forEach((a) => a.addEventListener("click", close));
      $("#adding-result .btn")?.focus();
    };
    return {
      done: (html, links) => finish("is-done", html, links),
      fail: (msg) => finish("is-fail", `Nothing was changed: ${esc(msg)}`, [[location.hash || "#/data", "Close"]]),
    };
  }

  async function signOut() {
    setUser(null);
    renderAccount();
    location.hash = "#/data";
    toast("Signed out. Resetting the demo to November 2025...");
    try { await post("/api/loop/demo-start", {}); await loadData(); toast("Signed out. The demo is back to November 2025."); }
    catch (e) { toast(e.message); }
  }
  function wireAccount() {
    $("#acct").addEventListener("click", (e) => { if (e.target.closest("[data-signout]")) signOut(); });
    $("[data-signin=demo]").addEventListener("click", async (e) => {
      const b = e.currentTarget;
      b.disabled = true; b.textContent = "Signing in...";
      try {
        await post("/api/loop/demo-start", {});
        setUser({ kind: "demo", name: "Demo" });
        await loadData();
        location.hash = "#/";
        toast("Demo data runs to November 2025. Add December from the month bar.");
      } catch (err) { toast(err.message); }
      b.disabled = false; b.textContent = "Sign in to the demo";
    });
    $("#signin-company").addEventListener("submit", (e) => {
      e.preventDefault();
      const name = String(new FormData(e.target).get("company") || "").trim();
      if (!name) return;
      setUser({ kind: "company", name });
      renderAccount();
      route();
      $(".upload-block").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    });
  }

  function route() {
    const [path] = location.hash.replace(/^#\/?/, "").split("?");
    const parts = path.split("/");
    const page = PAGES[parts[0]] || "assess";
    if (locked() && page !== "data") { location.hash = "#/data"; return; }
    $$(".page").forEach((p) => (p.hidden = p.dataset.page !== page));
    $$(".bar__nav a").forEach((a) => a.classList.toggle("is-on", a.dataset.page === (NAV_OF[page] || page)));
    $$(".nav-tab").forEach((a) => a.classList.toggle("active", a.dataset.page === (NAV_OF[page] || page)));
    if (page === "assess") renderAssess();
    window.scrollTo(0, 0);
    if (!S.loop) return;
    if (page === "people") {
      const q = new URLSearchParams(location.hash.split("?")[1] || "");
      const view = q.get("view") || ([...q.keys()].length ? "people" : "departments");
      if (view === "people") { readPeopleHash(); loadPeople(); }
      setPeopleView(view, view === "teams" ? q.get("department") || "" : undefined);
    }
    if (page === "employee") openEmployee(decodeURIComponent(parts[1] || "") || S.person?.employee_id || firstEmployee);
    if (page === "data") { renderCheck(); renderDataSummary(); }
    if (page === "model") renderModelPage();
  }

  async function init() {
    cycleWord();
    embers($("#embers"), 1);
    watch($("#personchart"), drawPerson);
    wireData();
    wireFilters();
    $("#month-select").addEventListener("change", (e) => loadData(e.target.value));
    $("#month-actions").addEventListener("click", (e) => { const b = e.target.closest("[data-act]"); if (b) monthAction(b.dataset.act); });
    wireLogForm();
    addEventListener("hashchange", route);
    wireAccount();
    wireHelpInfo();
    wireSurvey();
    wireTeams();
    const stagger = new MutationObserver((muts) => muts.forEach((m) =>
      [...m.target.querySelectorAll(":scope > .tr:not(.tr--head)")].forEach((r, i) => r.style.setProperty("--r", Math.min(i, 14)))));
    ["#depts", "#teams", "#people"].forEach((sel) => stagger.observe($(sel), { childList: true }));
    watch($("#fchart"), drawForecastChart);
    // remove one chosen file (×) or discard a whole form; drop labels go back to their empty state
    document.addEventListener("click", (e) => {
      const x = e.target.closest(".drop__x");
      if (!x) return;
      e.preventDefault(); e.stopPropagation();
      const input = x.closest(".drop").querySelector("input[type=file]");
      input.value = "";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    document.addEventListener("reset", (e) => {
      const form = e.target;
      setTimeout(() => form.querySelectorAll("input[type=file]").forEach((i) => i.dispatchEvent(new Event("change", { bubbles: true }))));
      if (form.id === "upload") { S.checked = null; $$("#report .checked").forEach((n) => n.remove()); renderLevels(null); }
    });
    wireConnectors();
    renderAccount();
    // signed out: the Data & model page is the landing page with the sign-in
    if (!user()) location.hash = "#/data";
    route();
    await loadData();
  }

  async function loadData(period) {
    S.person = null; S.personRow = null; firstEmployee = null; S.seats = null; S.dsum = null;
    try {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      [S.loop, S.fc] = await Promise.all([api(`/api/loop${q}`), api("/api/forecast").catch(() => null)]);
      if (!S.loop.available) throw new Error("The loop has no data yet.");
    } catch (e) {
      $("#meta").classList.add("is-offline");
      $("#meta").innerHTML = `<span class="pulse"></span><span class="bar__metatext">model offline</span>`;
      toast(e.message);
      return;
    }
    S.rci = S.loop.company?.reliable_change_threshold;
    renderHeader();
    renderMonth();
    renderAccount();
    renderHow();
    renderKpis();
    renderAssess();
    renderHelp();
    firstEmployee = S.loop.triage?.very_high?.example?.employee_id || null;
    renderQuad();
    if (!$('[data-page="model"].page').hidden) renderModelPage();
    if (!$('[data-page="data"].page').hidden) renderDataSummary();
    route();
  }

  init();
})();
