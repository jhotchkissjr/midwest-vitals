/* Midwest Vitals front end.
 * Reads data/dashboard.json (written by pipeline/build.py) and renders the
 * scorecard and every chart. Nothing about specific series lives here; the
 * config file drives everything. */
(() => {
  "use strict";

  const state = { data: null, years: 5, charts: [] };
  const $ = (sel, el = document) => el.querySelector(sel);
  const DAY = 86400000;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // ---------- formatting --------------------------------------------------
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const slotColor = (slot) => css(`--series-${slot}`) || css("--series-1");

  function parseDate(s) {
    const [y, m, d] = s.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  }

  // Infer frequency from spacing so labels read "Q2 2025", "Sep 2025", etc.
  function cadence(points) {
    if (points.length < 2) return "M";
    const gap = (parseDate(points[points.length - 1][0]) - parseDate(points[points.length - 2][0])) / DAY;
    if (gap > 300) return "A";
    if (gap > 80) return "Q";
    if (gap > 25) return "M";
    return "D";
  }

  function fmtDate(ts, freq) {
    const d = new Date(ts);
    const y = d.getUTCFullYear(), m = d.getUTCMonth();
    if (freq === "A") return String(y);
    if (freq === "Q") return `Q${Math.floor(m / 3) + 1} ${y}`;
    if (freq === "M") return `${MONTHS[m]} ${y}`;
    return `${MONTHS[m]} ${d.getUTCDate()}, ${y}`;
  }

  function fmtNum(v, units = "") {
    if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
    const a = Math.abs(v);
    let digits = a >= 100 ? 0 : a >= 1 || a === 0 ? 1 : 2;
    if (/count/.test(units)) digits = 0;
    return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function fmtDelta(v, units) {
    if (v === null || v === undefined) return "";
    const s = fmtNum(v, units);
    return v > 0 ? `+${s}` : v < 0 ? s.replace("-", "−") : "unch.";
  }

  // ---------- Chart.js setup ------------------------------------------------
  // Mixed frequencies (monthly U.S. vs quarterly states) never share x values,
  // so the tooltip picks the nearest point in each series instead of an index.
  function registerChartExtras() {
    Chart.Interaction.modes.nearestEach = function (chart, e) {
      const pos = Chart.helpers.getRelativePosition(e, chart);
      const area = chart.chartArea;
      if (!area || pos.x < area.left || pos.x > area.right) return [];
      const items = [];
      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        if (meta.hidden || !meta.data.length) return;
        let best = null, bestD = Infinity;
        for (let i = 0; i < meta.data.length; i++) {
          const d = Math.abs(meta.data[i].x - pos.x);
          if (d < bestD) { bestD = d; best = { element: meta.data[i], datasetIndex: di, index: i }; }
        }
        if (best && bestD < 60) items.push(best);
      });
      return items;
    };

    Chart.register({
      id: "crosshair",
      afterDatasetsDraw(chart) {
        const active = chart.tooltip && chart.tooltip.getActiveElements();
        if (!active || !active.length || chart.config.type === "bar") return;
        const x = active[0].element.x, { top, bottom } = chart.chartArea, ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = css("--axis");
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
        ctx.restore();
      },
    });
  }

  function baseOptions(chart) {
    const text3 = css("--text-3"), grid = css("--grid"), zero = css("--zero");
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
      interaction: { mode: chart.style === "bar" ? "index" : "nearestEach", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--surface"),
          titleColor: css("--text"),
          bodyColor: css("--text-2"),
          borderColor: css("--border"),
          borderWidth: 1,
          padding: 10,
          boxPadding: 4,
          usePointStyle: true,
          callbacks: {},
        },
      },
      scales: {
        y: {
          border: { display: false },
          grid: { color: (c) => (c.tick && c.tick.value === 0 ? zero : grid), lineWidth: (c) => (c.tick && c.tick.value === 0 ? 1.25 : 1) },
          ticks: { color: text3, font: { size: 11 }, maxTicksLimit: 6, callback: (v) => fmtNum(v, chart.units) },
        },
      },
    };
  }

  function cutoff() {
    const d = new Date();
    return Date.UTC(d.getUTCFullYear() - state.years, d.getUTCMonth(), 1);
  }

  function lineChart(canvas, chart) {
    const min = cutoff();
    const datasets = chart.series.map((s) => {
      const color = slotColor(s._slot);
      return {
        label: s.label,
        data: s.points.map(([d, v]) => ({ x: parseDate(d), y: v })).filter((p) => p.x >= min),
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBorderWidth: 2,
        pointHoverBorderColor: css("--surface"),
        tension: 0,
        spanGaps: true,
        _freq: cadence(s.points),
      };
    });
    const opts = baseOptions(chart);
    const max = Math.max(...datasets.flatMap((d) => d.data.map((p) => p.x)));
    opts.scales.x = {
      type: "linear",
      min,
      max: Number.isFinite(max) ? max : undefined,
      border: { color: css("--axis") },
      grid: { display: false },
      ticks: {
        color: css("--text-3"), font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 7,
        callback: (v) => {
          const d = new Date(v);
          return state.years <= 2 ? `${MONTHS[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}` : d.getUTCFullYear();
        },
      },
      afterBuildTicks: (axis) => {
        // Place ticks on Jan 1 (or quarter starts for short ranges) instead of arbitrary timestamps.
        const lo = new Date(axis.min), hi = axis.max, ticks = [];
        const step = state.years <= 2 ? 6 : state.years <= 5 ? 12 : 24;
        let y = lo.getUTCFullYear(), m = 0;
        for (let t = Date.UTC(y, m, 1); t <= hi; ) {
          if (t >= axis.min) ticks.push({ value: t });
          m += step; y += Math.floor(m / 12); m %= 12;
          t = Date.UTC(y, m, 1);
        }
        axis.ticks = ticks;
      },
    };
    opts.plugins.tooltip.callbacks = {
      title: (items) => (items.length ? fmtDate(items[0].parsed.x, items[0].dataset._freq) : ""),
      label: (item) => {
        const ds = item.dataset;
        const when = items_differ(item) ? ` (${fmtDate(item.parsed.x, ds._freq)})` : "";
        return ` ${ds.label}: ${fmtNum(item.parsed.y, chart.units)}${when}`;
      },
    };
    // Show the period beside a value when series in one tooltip are from different dates.
    function items_differ(item) {
      const active = item.chart.tooltip.dataPoints || [];
      return active.some((p) => p.parsed.x !== active[0].parsed.x);
    }
    return new Chart(canvas, { type: "line", data: { datasets }, options: opts });
  }

  function barChart(canvas, chart) {
    const min = cutoff();
    const s = chart.series[0];
    const freq = cadence(s.points);
    const pts = s.points.filter(([d]) => parseDate(d) >= min);
    const color = slotColor(s._slot);
    const opts = baseOptions(chart);
    opts.scales.x = {
      type: "category",
      border: { color: css("--axis") },
      grid: { display: false },
      ticks: { color: css("--text-3"), font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 },
    };
    opts.scales.y.beginAtZero = true;
    opts.plugins.tooltip.callbacks = {
      label: (item) => ` ${s.label}: ${fmtNum(item.parsed.y, chart.units)}`,
    };
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: pts.map(([d]) => fmtDate(parseDate(d), freq)),
        datasets: [{
          label: s.label,
          data: pts.map(([, v]) => v),
          backgroundColor: color,
          borderRadius: 3,
          borderSkipped: "start",
          maxBarThickness: 28,
          categoryPercentage: 0.85,
          barPercentage: 0.9,
        }],
      },
      options: opts,
    });
  }

  // ---------- rendering -----------------------------------------------------
  // Charts with several series from one geography (e.g. three Treasury yields)
  // take categorical slots in fixed order instead of the geography's slot.
  function assignSlots(chart) {
    const geos = chart.series.map((s) => s.geo);
    const distinct = new Set(geos).size === geos.length;
    chart.series.forEach((s, i) => { s._slot = distinct ? s.slot : i + 1; });
  }

  function latest(s) {
    const p = s.points;
    if (!p.length) return null;
    const freq = cadence(p);
    const last = p[p.length - 1];
    const prior = p.length > 1 ? p[p.length - 2] : null;
    const target = parseDate(last[0]) - 365 * DAY;
    let yearAgo = null;
    for (let i = p.length - 1; i >= 0; i--) {
      if (Math.abs(parseDate(p[i][0]) - target) < 20 * DAY) { yearAgo = p[i]; break; }
      if (parseDate(p[i][0]) < target - 20 * DAY) break;
    }
    return { freq, last, prior, yearAgo };
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  function swatch(slot) {
    const s = el("span", { class: "swatch", "aria-hidden": "true" });
    s.style.background = slotColor(slot);
    s.dataset.slot = slot;
    return s;
  }

  function renderScorecard(rows) {
    const box = $("#scorecard");
    box.replaceChildren();
    for (const r of rows) {
      const chart = findChart(r.id);
      if (!chart) continue;
      const tile = el("a", { class: "tile", href: `#chart-${r.id}`, style: "text-decoration:none;color:inherit" },
        el("h3", { text: r.title }), el("div", { class: "units", text: r.units }));
      for (const s of chart.series) {
        const L = latest(s);
        if (!L) continue;
        const delta = L.prior ? L.last[1] - L.prior[1] : null;
        tile.append(el("div", { class: "tile-row" },
          swatch(s._slot),
          el("span", { class: "label", text: s.label }),
          el("span", { class: "value", text: fmtNum(L.last[1], r.units) }),
          el("span", { class: "sub", text: `${fmtDate(parseDate(L.last[0]), L.freq)}${delta !== null ? `, ${fmtDelta(delta, r.units)} vs prior` : ""}` })));
      }
      box.append(tile);
    }
  }

  function findChart(id) {
    for (const sec of state.data.sections) for (const c of sec.charts) if (c.id === id) return c;
    return null;
  }

  function toCSV(chart) {
    const rows = [["series", "date", "value"]];
    for (const s of chart.series) for (const [d, v] of s.points) rows.push([s.label, d, v]);
    return rows.map((r) => r.map((x) => (/[",]/.test(String(x)) ? `"${String(x).replace(/"/g, '""')}"` : x)).join(",")).join("\n");
  }

  function dataTable(chart) {
    const table = el("table");
    table.append(el("thead", {}, el("tr", {},
      el("th", { text: "Series" }), el("th", { text: "Latest" }), el("th", { text: "Prior" }), el("th", { text: "Year ago" }))));
    const body = el("tbody");
    for (const s of chart.series) {
      const L = latest(s);
      if (!L) continue;
      const cell = (p) => el("td", { text: p ? `${fmtNum(p[1], chart.units)} (${fmtDate(parseDate(p[0]), L.freq)})` : "n/a" });
      body.append(el("tr", {}, el("td", { text: s.label }), cell(L.last), cell(L.prior), cell(L.yearAgo)));
    }
    table.append(body);
    return el("details", { class: "data" }, el("summary", { text: "Data table" }), table);
  }

  function renderCard(chart) {
    const legend = el("div", { class: "legend" });
    for (const s of chart.series) {
      const L = latest(s);
      legend.append(el("span", { class: "legend-item" },
        swatch(s._slot),
        s.label,
        L ? el("b", { text: fmtNum(L.last[1], chart.units) }) : null,
        L ? el("small", { text: fmtDate(parseDate(L.last[0]), L.freq) }) : null));
    }

    const canvas = el("canvas", { role: "img", "aria-label": `${chart.title}, ${chart.units}` });
    const foot = el("div", { class: "card-foot" });
    if (chart.note) foot.append(el("span", { class: "note", text: chart.note }));
    if (chart.stale) foot.append(el("span", { class: "stale", title: "The latest refresh failed; showing the last good data.", text: "Not refreshed" }));
    const links = chart.series.filter((s) => s.source_url).map((s) => el("a", { href: s.source_url, target: "_blank", rel: "noopener", text: s.source_id }));
    if (links.length) {
      foot.append("Source: ");
      links.forEach((a, i) => { if (i) foot.append(", "); foot.append(a); });
    } else {
      foot.append(`Source: ${chart.source === "fdic" ? "FDIC BankFind" : chart.source === "ncua" ? "NCUA call reports" : chart.source.toUpperCase()}`);
    }
    const csv = el("button", { type: "button", text: "CSV" });
    csv.addEventListener("click", () => {
      const blob = new Blob([toCSV(chart)], { type: "text/csv" });
      const a = el("a", { href: URL.createObjectURL(blob), download: `${chart.id}.csv` });
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    foot.append(csv);

    const card = el("article", { class: "card", id: `chart-${chart.id}` },
      el("h3", { text: chart.title }),
      el("div", { class: "units", text: chart.units }),
      legend,
      el("div", { class: "canvas-box" }, canvas),
      foot,
      dataTable(chart));
    card._chart = chart;
    card._canvas = canvas;
    return card;
  }

  function renderSections() {
    const root = $("#sections"), nav = $("#nav");
    root.replaceChildren();
    nav.replaceChildren(el("a", { href: "#scorecard", text: "Latest" }));
    for (const sec of state.data.sections) {
      if (!sec.charts.length) continue;
      nav.append(el("a", { href: `#${sec.id}`, text: sec.title }));
      const grid = el("div", { class: "grid" });
      sec.charts.forEach((c) => grid.append(renderCard(c)));
      root.append(el("section", { class: "section", id: sec.id },
        el("h2", { text: sec.title }),
        sec.intro ? el("p", { class: "section-intro", text: sec.intro }) : null,
        sec.ai_read ? el("p", { class: "ai-read" }, el("span", { class: "tag", text: "AI-generated summary of the latest data" }), sec.ai_read) : null,
        grid));
    }
  }

  // Charts are drawn only when scrolled near, which keeps the first paint fast.
  let observer;
  function drawCharts() {
    state.charts.forEach((c) => c.destroy());
    state.charts = [];
    if (observer) observer.disconnect();
    observer = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        observer.unobserve(e.target);
        const card = e.target;
        const make = card._chart.style === "bar" ? barChart : lineChart;
        state.charts.push(make(card._canvas, card._chart));
      }
    }, { rootMargin: "400px 0px" });
    document.querySelectorAll(".card").forEach((c) => observer.observe(c));
  }

  function redraw() {
    document.querySelectorAll(".swatch").forEach((s) => { s.style.background = slotColor(s.dataset.slot); });
    drawCharts();
  }

  function setRange(years) {
    state.years = years;
    document.querySelectorAll(".range button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.years) === years)));
    try { localStorage.setItem("mv-range", String(years)); } catch (_) { /* storage unavailable */ }
    drawCharts();
  }

  async function init() {
    registerChartExtras();
    Chart.defaults.font.family = css("--font") || "system-ui";
    try {
      const res = await fetch("data/dashboard.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      state.data = await res.json();
    } catch (e) {
      $("#load-error").hidden = false;
      return;
    }
    const d = state.data;
    if (d.site) {
      $("#site-title").textContent = d.site.title;
      $("#site-subtitle").textContent = d.site.subtitle;
      document.title = d.site.title;
    }
    $("#updated").textContent = `Data refreshed ${new Date(d.generated).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" })}`;
    $("#sample-banner").hidden = !d.sample;

    for (const sec of d.sections) sec.charts.forEach(assignSlots);
    renderScorecard(d.scorecard || []);
    renderSections();

    let saved = null;
    try { saved = Number(localStorage.getItem("mv-range")); } catch (_) { /* storage unavailable */ }
    document.querySelectorAll(".range button").forEach((b) => b.addEventListener("click", () => setRange(Number(b.dataset.years))));
    setRange([2, 5, 10].includes(saved) ? saved : 5);

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
