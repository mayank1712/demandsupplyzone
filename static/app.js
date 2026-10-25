const $ = (s) => document.querySelector(s);
const state = { results: [], selected: null, tf: "2h", chart: null, settings: null, pg: { page: 1, size: 25 } };

const fmt = (n, d = 2) => (n === null || n === undefined || Number.isNaN(n)) ? "–"
  : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pill = (cls, text) => `<span class="pill ${cls}">${text}</span>`;
const TIPS = {
  htf: "<b>HTF · Higher Time Frame</b> = Weekly chart (1 candle = 1 week).<br>The big picture: finds the major demand and supply zones and the curve (is price low, middle or high between them?). Trade in its direction.",
  itf: "<b>ITF · Intermediate Time Frame</b> = Daily chart.<br>The direction: Pulse (EMA 20 vs 50) + Trend (7th candle clock) decide the Action: Buy, Sell or No action.",
  ltf: "<b>LTF · Lower Time Frame</b> = 2h or 1h chart.<br>The precise trade: finds a small fresh zone for the exact Entry (proximal) and Stop loss (distal), so the stop stays tight.",
  curve: "<b>HTF curve</b>: the range from the nearest weekly demand zone up to the nearest weekly supply zone, split into 3.<br>Low = good area to buy · Equilibrium = middle, no edge · High = good area to sell.",
  wdz: "<b>Weekly DZ</b>: nearest weekly (HTF) demand zone, where big buyers stepped in before.",
  wsz: "<b>Weekly SZ</b>: nearest weekly (HTF) supply zone, where big sellers stepped in before.",
  ltfSetup: "<b>LTF setup</b>: the best fresh 2h/1h zone in the direction of the Action. This becomes the trade plan.",
  againstHtf: "<b>Against HTF</b>: the daily Action points one way but the weekly curve points the other (e.g. Buy while price is high, near weekly supply). Lower probability.",
  withHtf: "Does the trade agree with the weekly (HTF) curve? Buy in the low part / Sell in the high part = yes.",
  tfW: "<b>W · Weekly = HTF</b><br>Big-picture zones and curve.",
  tfD: "<b>D · Daily = ITF</b><br>Pulse and trend, which give the Action.",
  tfLtf: "<b>2h / 1h = LTF</b><br>Exact entry and stop-loss zone for the trade plan.",
  tr: "<b>TR · True Range</b> = the biggest of: high − low, |high − previous close|, |low − previous close|. How far price really moved in this candle, including gaps.",
  atr: "<b>ATR 14</b> = average True Range of the last 14 candles (RMA, same as TradingView \"ATR 14 RMA\"). Normal candle size for this stock.",
  r124: "<b>1-2-4 rule</b>: tallest UOC candle height = 1 (high − low). 1st candle ≥ 2× and 3rd candle ≥ 4× that height. Not required, but only zones that meet it get grade <b>A</b> (best category).",
  uoc: "<b>UOC candle</b>: TR is smaller than ATR, a quiet candle. 1–4 of these in a row form a zone base.",
  trAtr: "TR is at least ATR: a big candle. It can be the 1st candle (before the UOCs) or the 3rd candle (leaving the zone).",
};
const tip = (key, label) => `<span class="tip" data-tip="${key}">${label}</span>`;

// One floating tooltip for every [data-tip] element (a CSS-only tooltip gets clipped by scrolling tables).
function initTooltips() {
  const box = $("#tooltip");
  const show = (target) => {
    box.innerHTML = TIPS[target.dataset.tip] || target.dataset.tip;
    box.hidden = false;
    const r = target.getBoundingClientRect(), b = box.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left), window.innerWidth - b.width - 8);
    const top = r.bottom + 6 + b.height > window.innerHeight ? r.top - b.height - 6 : r.bottom + 6;
    box.style.left = left + "px";
    box.style.top = top + "px";
  };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (t) show(t); else box.hidden = true;
  });
  document.addEventListener("scroll", () => { box.hidden = true; }, true);
}
initTooltips();

const fmtTime = (iso) => iso ? iso.replace("T", " ").replace(":00", "").replace(" 00", "").slice(0, 16) : "–";

async function api(path) {
  const r = await fetch(path);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

function params() {
  return new URLSearchParams({
    ltf: $("#ltf").value, capital: $("#capital").value, risk_pct: $("#risk").value,
    reward_ratio: $("#rr").value, refresh: $("#refresh").checked,
  });
}

// ---------------- scan ----------------
async function scan(e) {
  e.preventDefault();
  const symbols = state.settings.watchlist;
  state.results = [];
  state.pg.page = 1;
  $("#scanBtn").disabled = true;
  $("#empty").hidden = true;
  $("#ltfLabel").textContent = $("#ltf").value;
  let done = 0;
  const queue = [...symbols];
  const worker = async () => {
    while (queue.length) {
      const sym = queue.shift();
      try {
        state.results.push(await api(`/api/analyze/${encodeURIComponent(sym)}?${params()}`));
      } catch (err) {
        state.results.push({ symbol: sym, error: err.message });
      }
      done++;
      $("#progress").textContent = `${done} / ${symbols.length}`;
      renderTable();
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  $("#scanBtn").disabled = false;
  $("#progress").textContent = `Done · ${state.results.filter(r => r.plan).length} setups`;
}

function passesFilter(r) {
  const f = $("#filter").value;
  if (f === "all") return true;
  if (r.error) return false;
  if (f === "plan") return !!r.plan;
  if (f === "aligned") return !!r.plan && r.action.htf_aligned;
  if (f === "inzone") return r.curve && r.curve.label.startsWith("In ");
  return r.action.side === f;
}

function zoneCell(z) {
  if (!z) return `<span class="small">none</span>`;
  const fresh = z.fresh ? pill("pos", "fresh") : `<span class="small">tested ${z.tests}</span>`;
  return `${fmt(z.proximal)} – ${fmt(z.distal)} <span class="small">(${z.distance_pct}%)</span> ${z.grade} ${fresh}`;
}

function renderTable() {
  const order = { BUY: 0, SELL: 1, NONE: 2 };
  const rows = state.results.filter(passesFilter).sort((a, b) => {
    if (a.error || b.error) return a.error ? 1 : -1;
    return (b.plan ? 1 : 0) - (a.plan ? 1 : 0) || order[a.action.side] - order[b.action.side]
      || a.symbol.localeCompare(b.symbol);
  });
  const first = pageStart(rows.length, state.pg);
  renderPager($("#pager"), rows.length, state.pg, renderTable, $("#listPane"));
  $("#results tbody").innerHTML = rows.slice(first, first + state.pg.size).map((r, i) => {
    const num = `<td class="num">${first + i + 1}</td>`;
    if (r.error) return `<tr>${num}<td>${r.symbol}</td><td colspan="8" class="err">${r.error}</td></tr>`;
    const p = r.pulse, t = r.trend;
    const plan = r.plan
      ? `${pill(r.plan.side, r.plan.side)} ${fmt(r.plan.entry)} / SL ${fmt(r.plan.stoploss)} / T ${fmt(r.plan.target)}
         · ${r.plan.quantity ? "Qty " + r.plan.quantity : pill("warn", "Qty 0 – capital too small")}`
      : `<span class="small">–</span>`;
    return `<tr data-sym="${r.symbol}" class="${state.selected === r.symbol ? "sel" : ""}">
      ${num}<td><b>${r.symbol}</b></td>
      <td>${fmt(r.price)}</td>
      <td>${pill(p.state === "positive" ? "pos" : "neg", p.state)} <span class="small">${p.candles_since_cross ?? "–"}d</span></td>
      <td>${pill(t.state === "uptrend" ? "pos" : t.state === "downtrend" ? "neg" : "neutral", t.state)} <span class="small">${t.clock ?? "–"} o'clock</span></td>
      <td>${pill(r.action.side, r.action.text)}</td>
      <td>${r.curve.label}${r.action.side !== "NONE" && !r.action.htf_aligned ? " " + `<span class="pill warn" data-tip="againstHtf">against HTF</span>` : ""}</td>
      <td>${zoneCell(r.htf_demand)}</td>
      <td>${zoneCell(r.htf_supply)}</td>
      <td>${plan}</td></tr>`;
  }).join("");
  document.querySelectorAll("#results tbody tr[data-sym]").forEach((tr) =>
    tr.addEventListener("click", () => openDetail(tr.dataset.sym)));
}

// Generic pager: pg = { page, size }. Renders into el and calls rerender() after a change.
function renderPager(el, total, pg, rerender, scrollTo) {
  el.hidden = total === 0;
  if (!total) return;
  const pages = Math.max(1, Math.ceil(total / pg.size));
  const cur = pg.page, first = (cur - 1) * pg.size;
  // Page numbers: first, last, and 2 either side of the current page, with "…" for gaps.
  const nums = [...new Set([1, pages, ...Array.from({ length: 5 }, (_, k) => cur - 2 + k)])]
    .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const btns = [];
  nums.forEach((n, k) => {
    if (k && n - nums[k - 1] > 1) btns.push(`<span class="gap">…</span>`);
    btns.push(`<button type="button" data-page="${n}" class="${n === cur ? "on" : ""}">${n}</button>`);
  });
  const sizes = [25, 50, 100, 100000].map((n) =>
    `<option value="${n}" ${n === pg.size ? "selected" : ""}>${n === 100000 ? "All" : n}</option>`).join("");
  el.innerHTML = `
    <span class="small">Showing ${first + 1}–${Math.min(first + pg.size, total)} of ${total}</span>
    <span class="pages">
      <button type="button" data-page="${cur - 1}" ${cur === 1 ? "disabled" : ""}>‹ Prev</button>
      ${btns.join("")}
      <button type="button" data-page="${cur + 1}" ${cur === pages ? "disabled" : ""}>Next ›</button>
    </span>
    <label class="small">Rows <select class="page-size">${sizes}</select></label>`;
  el.querySelectorAll("button[data-page]").forEach((b) => b.addEventListener("click", () => {
    pg.page = Number(b.dataset.page);
    rerender();
    if (scrollTo) scrollTo.scrollIntoView({ block: "start", behavior: "smooth" });
  }));
  el.querySelector(".page-size").addEventListener("change", (e) => {
    pg.size = Number(e.target.value);
    pg.page = 1;
    rerender();
  });
}

// Clamp pg.page to the available pages and return the slice start.
function pageStart(total, pg) {
  pg.page = Math.min(Math.max(1, pg.page), Math.max(1, Math.ceil(total / pg.size)));
  return (pg.page - 1) * pg.size;
}

// ---------------- detail ----------------
function openDetail(sym) {
  state.selected = sym;
  state.tf = $("#ltf").value;
  $("#detailPane").hidden = false;
  document.querySelector("main").classList.add("split");
  $("#dSymbol").textContent = sym;
  renderTable();
  renderCards();
  loadChart();
}

function renderCards() {
  const r = state.results.find((x) => x.symbol === state.selected);
  if (!r || r.error) { $("#cards").innerHTML = ""; return; }
  const z = r.setup, pl = r.plan;
  const kv = (o) => `<div class="kv">${Object.entries(o).map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("")}</div>`;
  $("#cards").innerHTML = `
    <div class="card"><h4>1 · Pulse (${tip("itf", "Daily")} EMA 20/50)</h4><div class="big">${r.pulse.state}</div>
      ${kv({ "EMA 20": fmt(r.pulse.ema20), "EMA 50": fmt(r.pulse.ema50), "Since cross": (r.pulse.candles_since_cross ?? "–") + " candles", Confirmed: r.pulse.confirmed ? "yes" : "no" })}</div>
    <div class="card"><h4>2 · Trend (7th candle clock)</h4><div class="big">${r.trend.state}</div>
      ${kv({ "Needle": (r.trend.clock ?? "–") + " o'clock", Angle: (r.trend.angle ?? "–") + "°" })}</div>
    <div class="card"><h4>3 · Action</h4><div class="big">${pill(r.action.side, r.action.text)}</div>
      ${kv({ [tip("curve", "HTF curve")]: r.curve.label, [tip("withHtf", "With HTF?")]: r.action.side === "NONE" ? "–" : r.action.htf_aligned ? "yes" : "no – trading against weekly zone","Close − W.ATR": fmt(r.atr_levels.demand_hint), "Close + W.ATR": fmt(r.atr_levels.supply_hint) })}</div>
    <div class="card"><h4>4 · Trade plan (${tip("ltf", r.ltf)})</h4>
      ${pl ? `<div class="big">${pill(pl.side, pl.side)} ${z.pattern} · grade ${z.grade}</div>
        ${kv({ Entry: fmt(pl.entry), "Stop loss": fmt(pl.stoploss), [`Target ${pl.rr}`]: fmt(pl.target),
               Quantity: pl.quantity || "0 (raise capital/risk)", Risk: "₹" + fmt(pl.actual_risk), Reward: "₹" + fmt(pl.reward),
               "Capital needed": "₹" + fmt(pl.capital_needed) })}`
        : `<div class="small">No fresh ${r.ltf} zone in the direction of the action.</div>`}</div>`;
}

async function loadChart() {
  const sym = state.selected;
  document.querySelectorAll("#tfButtons button").forEach((b) => b.classList.toggle("on", b.dataset.tf === state.tf));
  let data;
  try {
    data = await api(`/api/chart/${encodeURIComponent(sym)}?tf=${state.tf}`);
  } catch (err) {
    $("#chart").innerHTML = `<p class="err">${err.message}</p>`;
    return;
  }
  if (sym !== state.selected) return;
  drawChart(data);
  renderZoneTable(data.zones);
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function drawChart(data) {
  const el = $("#chart");
  el.innerHTML = "";
  if (state.chart) state.chart.remove();
  const intraday = data.tf === "2h" || data.tf === "1h";
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: cssVar("--panel") }, textColor: cssVar("--muted") },
    grid: { vertLines: { color: cssVar("--line") }, horzLines: { color: cssVar("--line") } },
    timeScale: { timeVisible: intraday, secondsVisible: false },
    rightPriceScale: { borderColor: cssVar("--line") },
    // Price-axis drag is replaced by our own vertical zoom (it would switch auto-scale off).
    handleScale: { axisPressedMouseMove: { time: true, price: false } },
  });
  state.chart = chart;
  state.view = { zoom: 1, shift: 0, range: null };
  bindVerticalZoom(el);
  const green = cssVar("--green"), red = cssVar("--red"), gray = cssVar("--tested");
  const candles = chart.addCandlestickSeries({ upColor: green, downColor: red, borderVisible: false, wickUpColor: green, wickDownColor: red });
  state.candles = candles;
  candles.setData(data.candles);
  bindCandleInfo(chart, data);
  applyVerticalView();
  // Only the candles drive the price range, so vertical zoom/pan stays consistent.
  const lineOpts = { lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
                     autoscaleInfoProvider: () => null };
  chart.addLineSeries({ ...lineOpts, color: "#e0a100" }).setData(data.ema20);
  chart.addLineSeries({ ...lineOpts, color: "#7b61ff" }).setData(data.ema50);

  const showBroken = $("#showBroken").checked, showTested = $("#showTested").checked;
  const markers = [];
  data.zones.filter((z) => (showBroken || !z.broken) && (showTested || z.tests === 0)).forEach((z) => {
    // Fresh = green (demand) / red (supply); tested = gray; broken = faded gray
    const color = z.fresh ? (z.kind === "demand" ? green : red) : gray;
    const c = hexToRgba(color, z.broken ? 0.35 : 1);
    const pts = (v) => [{ time: z.start_ts, value: v }, { time: z.end_ts, value: v }];
    if (z.start_ts >= z.end_ts) return;
    chart.addLineSeries({ ...lineOpts, color: c, lineWidth: 2 }).setData(pts(z.proximal));
    chart.addLineSeries({ ...lineOpts, color: c, lineStyle: LightweightCharts.LineStyle.Dashed }).setData(pts(z.distal));
    markers.push({
      time: z.start_ts, position: z.kind === "demand" ? "belowBar" : "aboveBar",
      color: c, shape: z.kind === "demand" ? "arrowUp" : "arrowDown", text: `${z.pattern} ${z.grade}${z.fresh ? "" : " · tested"}`,
    });
  });
  markers.sort((a, b) => a.time - b.time);
  candles.setMarkers(markers);
  chart.timeScale().fitContent();
}

// Info line above the chart: O/H/L/C, TR, ATR of the hovered candle (last candle when not hovering).
function bindCandleInfo(chart, data) {
  const byTime = new Map(data.candles.map((c) => [c.time, c]));
  const last = data.candles[data.candles.length - 1];
  const intraday = data.tf === "2h" || data.tf === "1h";
  const show = (c) => {
    if (!c) { $("#chartInfo").innerHTML = ""; return; }
    const d = new Date(c.time * 1000).toISOString();          // times are IST stored as UTC
    const when = intraday ? `${d.slice(0, 10)} ${d.slice(11, 16)}` : d.slice(0, 10);
    const up = c.close >= c.open;
    const uoc = c.tr < c.atr;
    $("#chartInfo").innerHTML = `<b>${when}</b>
      <span class="${up ? "pos-t" : "neg-t"}">O ${fmt(c.open)} H ${fmt(c.high)} L ${fmt(c.low)} C ${fmt(c.close)}</span>
      <span>${tip("tr", "TR")} <b>${fmt(c.tr)}</b></span>
      <span>${tip("atr", "ATR 14")} <b>${fmt(c.atr)}</b></span>
      ${uoc ? `<span class="pill tested" data-tip="uoc">UOC · TR &lt; ATR</span>`
            : `<span class="pill neutral" data-tip="trAtr">TR ≥ ATR</span>`}`;
  };
  chart.subscribeCrosshairMove((p) => show(p && p.time !== undefined ? byTime.get(p.time) : last));
  show(last);
}

// Lightweight Charts 4.x has no API to set the price range, so vertical zoom/pan is done by
// stretching (zoom) and moving (shift) the auto-scaled candle range.
function applyVerticalView() {
  const v = state.view;
  state.candles.applyOptions({
    autoscaleInfoProvider: (original) => {
      const base = original();
      if (!base || !base.priceRange) return base;
      const { minValue, maxValue } = base.priceRange;
      const center = (minValue + maxValue) / 2 + v.shift;
      const half = ((maxValue - minValue) / 2 || 1) * v.zoom;
      v.range = half * 2;
      return { ...base, priceRange: { minValue: center - half, maxValue: center + half } };
    },
  });
}

function bindVerticalZoom(el) {
  if (el.dataset.vzoom) return;   // the #chart element is reused across redraws
  el.dataset.vzoom = "1";
  const axisWidth = () => state.chart.priceScale("right").width();
  const paneHeight = () => el.clientHeight - state.chart.timeScale().height();

  // Wheel over the price axis, or Ctrl + wheel anywhere on the chart -> vertical zoom.
  el.addEventListener("wheel", (e) => {
    const r = el.getBoundingClientRect();
    const onAxis = e.clientX - r.left >= el.clientWidth - axisWidth();
    if (!onAxis && !e.ctrlKey) return;
    e.preventDefault();
    e.stopPropagation();
    const v = state.view;
    v.zoom = Math.min(20, Math.max(0.05, v.zoom * (e.deltaY > 0 ? 1.1 : 1 / 1.1)));
    applyVerticalView();
  }, { capture: true, passive: false });

  // Drag on the chart -> vertical pan (horizontal pan stays with the library).
  let lastY = null;
  el.addEventListener("mousedown", (e) => {
    const r = el.getBoundingClientRect();
    const inPane = e.clientX - r.left < el.clientWidth - axisWidth() && e.clientY - r.top < paneHeight();
    lastY = e.button === 0 && inPane ? e.clientY : null;
  });
  window.addEventListener("mousemove", (e) => {
    if (lastY === null || !(e.buttons & 1) || !state.view.range) return;
    state.view.shift += (e.clientY - lastY) * state.view.range / paneHeight();
    lastY = e.clientY;
    applyVerticalView();
  });
  window.addEventListener("mouseup", () => { lastY = null; });

  // Double-click -> reset to the original view.
  el.addEventListener("dblclick", () => {
    state.view.zoom = 1;
    state.view.shift = 0;
    applyVerticalView();
    state.chart.timeScale().fitContent();
  });
}

function hexToRgba(color, a) {
  if (!color.startsWith("#") || a === 1) return color;
  const n = parseInt(color.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function renderZoneTable(zones) {
  const rows = [...zones].reverse();
  const yes = (b) => b ? "✓" : "✗";
  $("#zoneTable tbody").innerHTML = rows.map((z) => `<tr>
    <td>${pill(z.kind, z.pattern)}</td>
    <td>${fmtTime(z.base_start)}</td>
    <td>${fmt(z.proximal)}</td><td>${fmt(z.distal)}</td>
    <td>${z.boring_count} · ${z.boring_grade}</td>
    <td>${z.legin_filled && z.legout_filled ? pill("pos", "1-2-4 ✓") : ""}
      <span class="small">in ${fmt(z.legin_x, 1)}× ${yes(z.legin_filled)} · out ${fmt(z.legout_x, 1)}× ${yes(z.legout_filled)}</span></td>
    <td>${yes(z.legout_gap)}</td>
    <td>${z.tests}</td>
    <td>${z.broken ? '<span class="small">broken</span>' : z.fresh ? pill(z.kind, "fresh") : pill("tested", "tested")}</td>
    <td><b>${z.grade}</b> <span class="small">${z.score}/14</span></td></tr>`).join("")
    || `<tr><td colspan="10" class="small">No zones found.</td></tr>`;
}

// ---------------- init ----------------
async function init() {
  state.settings = await api("/api/settings");
  $("#capital").value = state.settings.capital;
  $("#risk").value = state.settings.risk_pct;
  $("#rr").value = state.settings.reward_ratio;
  $("#provider").textContent = `data: ${state.settings.provider} · ${state.settings.watchlist.length} stocks`;
  $("#controls").addEventListener("submit", scan);
  $("#filter").addEventListener("change", () => { state.pg.page = 1; renderTable(); });
  $("#closeDetail").addEventListener("click", () => {
    $("#detailPane").hidden = true; state.selected = null;
    document.querySelector("main").classList.remove("split"); renderTable();
  });
  document.querySelectorAll("#tfButtons button").forEach((b) =>
    b.addEventListener("click", () => { state.tf = b.dataset.tf; loadChart(); }));
  $("#showBroken").addEventListener("change", loadChart);
  $("#showTested").addEventListener("change", loadChart);
}
init().catch((e) => { $("#empty").innerHTML = `<span class="err">${e.message}</span>`; });
