// Backtest tab: runs /api/backtest/{symbol} for each stock and summarises the trades here.
const bt = { trades: [], meta: [], pg: { page: 1, size: 25 }, symPg: { page: 1, size: 25 }, chart: null, rr: 5 };

Object.assign(TIPS, {
  rmult: "<b>R = risk unit.</b> 1R is what you lose if the stop loss hits (e.g. ₹50). A target hit at 1:5 = +5R. Comparing in R makes stocks of any price comparable.",
  btCost: "<b>Round-trip costs</b> as % of the trade value: brokerage, STT, exchange fees, stamp duty, GST. About 0.2–0.25% for delivery trades in India. Deducted from every trade.",
  winRate: "Share of closed trades that made money. With a 1:R reward you only need to win more than 1 ÷ (1 + R) of trades to break even, e.g. 16.7% at 1:5.",
  totalR: "Sum of all trade results in R after costs. +40R with ₹50 risk per trade ≈ ₹2,000 profit.",
  avgR: "<b>Expectancy</b>: average R per trade after costs. Above 0 = the rules made money on average; this is the key number.",
  pf: "<b>Profit factor</b> = total won ÷ total lost. Above 1 is profitable; 1.5+ is good.",
  dd: "<b>Max drawdown</b>: the biggest drop from a peak in the equity curve, in R. Tells you the worst losing streak you had to sit through.",
});

const sumR = (ts) => ts.reduce((a, t) => a + t.r_net, 0);

function btStats(trades) {
  const closed = trades.filter((t) => t.result !== "open").sort((a, b) => a.exit_time.localeCompare(b.exit_time));
  const wins = closed.filter((t) => t.r_net > 0);
  const won = sumR(wins), lost = -sumR(closed.filter((t) => t.r_net <= 0));
  let eq = 0, peak = 0, dd = 0;
  closed.forEach((t) => { eq += t.r_net; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); });
  return {
    n: closed.length, open: trades.length - closed.length, wins: wins.length,
    winRate: closed.length ? 100 * wins.length / closed.length : 0,
    total: eq, avg: closed.length ? eq / closed.length : 0,
    pf: lost > 0 ? won / lost : null, dd,
    pnl: closed.reduce((a, t) => a + t.pnl, 0),
  };
}

const signed = (v, d = 2) => `<span class="${v > 0 ? "pos-t" : v < 0 ? "neg-t" : ""}">${v > 0 ? "+" : ""}${fmt(v, d)}</span>`;

function renderBtCards() {
  const s = btStats(bt.trades);
  const be = 100 / (1 + bt.rr);
  const from = bt.meta.map((m) => m.from).sort()[0], to = bt.meta.map((m) => m.to).sort().slice(-1)[0];
  const card = (title, big, sub = "", cls = "") =>
    `<div class="card"><h4>${title}</h4><div class="big ${cls}">${big}</div><div class="small">${sub}</div></div>`;
  $("#btCards").innerHTML =
    card("Trades", s.n, `${s.wins} won · ${s.n - s.wins} lost${s.open ? ` · ${s.open} still open` : ""}`) +
    card(tip("winRate", "Win rate"), fmt(s.winRate, 1) + "%", `break-even at 1:${bt.rr} = ${fmt(be, 1)}%`,
         s.winRate > be ? "pos-t" : "neg-t") +
    card(tip("avgR", "Avg R / trade"), signed(s.avg, 3), "after costs") +
    card(tip("totalR", "Total R"), signed(s.total), `₹${fmt(s.pnl, 0)} with your capital & risk`) +
    card(tip("pf", "Profit factor"), s.pf === null ? "–" : fmt(s.pf, 2), "won ÷ lost", s.pf > 1 ? "pos-t" : "neg-t") +
    card(tip("dd", "Max drawdown"), fmt(s.dd, 1) + "R", "worst peak-to-low drop") +
    card("Period", from ? `${from.slice(0, 10)}` : "–", to ? `to ${to.slice(0, 10)} · ${bt.meta.length} stocks` : "");
}

function renderBtChart() {
  const el = $("#btChart");
  if (bt.chart) bt.chart.remove();
  el.innerHTML = "";
  const byTime = new Map();
  bt.trades.filter((t) => t.result !== "open").forEach((t) => {
    const ts = Date.parse(t.exit_time + "Z") / 1000;        // naive IST shown as-is (same as the price chart)
    byTime.set(ts, (byTime.get(ts) || 0) + t.r_net);
  });
  let eq = 0;
  const pts = [...byTime.entries()].sort((a, b) => a[0] - b[0]).map(([time, r]) => ({ time, value: +(eq += r).toFixed(2) }));
  bt.chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: cssVar("--panel") }, textColor: cssVar("--muted") },
    grid: { vertLines: { color: cssVar("--line") }, horzLines: { color: cssVar("--line") } },
    rightPriceScale: { borderColor: cssVar("--line") },
  });
  const up = eq >= 0;
  const series = bt.chart.addAreaSeries({
    lineColor: cssVar(up ? "--green" : "--red"), lineWidth: 2,
    topColor: hexToRgba(cssVar(up ? "--green" : "--red"), 0.25), bottomColor: hexToRgba(cssVar(up ? "--green" : "--red"), 0.02),
    priceFormat: { type: "custom", formatter: (v) => v.toFixed(1) + "R" },
  });
  series.setData(pts);
  series.createPriceLine({ price: 0, color: cssVar("--muted"), lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed });
  bt.chart.timeScale().fitContent();
}

function renderBtGroups() {
  const group = (title, keyFn, order) => {
    const m = new Map();
    bt.trades.forEach((t) => { const k = keyFn(t); m.set(k, [...(m.get(k) || []), t]); });
    const keys = [...m.keys()].sort((a, b) => (order ? order.indexOf(a) - order.indexOf(b) : String(a).localeCompare(b)));
    const rows = keys.map((k) => {
      const s = btStats(m.get(k));
      return `<tr><td>${k}</td><td>${s.n}</td><td>${fmt(s.winRate, 1)}%</td><td>${signed(s.total, 1)}</td>
        <td>${signed(s.avg, 3)}</td><td>${s.pf === null ? "–" : fmt(s.pf, 2)}</td></tr>`;
    }).join("");
    return `<div><h3>${title}</h3><table><thead><tr><th></th><th>Trades</th><th>Win %</th><th>Total R</th>
      <th>Avg R</th><th>PF</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  };
  $("#btGroups").innerHTML =
    group("By zone grade", (t) => "Grade " + t.grade, ["Grade A", "Grade B", "Grade C", "Grade D"]) +
    group(`By ${tip("htf", "HTF")} curve`, (t) => t.aligned ? "With HTF" : "Against HTF", ["With HTF", "Against HTF"]) +
    group("By side", (t) => t.side, ["BUY", "SELL"]) +
    group("By pattern", (t) => t.pattern, ["RBR", "DBR", "RBD", "DBD"]) +
    group("By action", (t) => t.action, null) +
    group("By zone tests", (t) => t.tests === 0 ? "Fresh" : "Tested once", ["Fresh", "Tested once"]);
}

function renderBtPerSym() {
  const rows = bt.meta.map((m) => ({ ...m, s: btStats(bt.trades.filter((t) => t.symbol === m.symbol)) }))
    .sort((a, b) => b.s.total - a.s.total);
  const first = pageStart(rows.length, bt.symPg);
  renderPager($("#btSymPager"), rows.length, bt.symPg, renderBtPerSym);
  $("#btPerSym tbody").innerHTML = rows.slice(first, first + bt.symPg.size).map((r, i) => r.error
    ? `<tr><td class="num">${first + i + 1}</td><td><b>${r.symbol}</b></td><td colspan="5" class="err">${r.error}</td></tr>`
    : `<tr><td class="num">${first + i + 1}</td><td><b>${r.symbol}</b></td><td>${r.s.n}</td><td>${fmt(r.s.winRate, 1)}%</td>
       <td>${signed(r.s.total, 1)}</td><td>${signed(r.s.avg, 3)}</td>
       <td class="small">${r.from.slice(0, 10)} → ${r.to.slice(0, 10)}</td></tr>`).join("");
}

function renderBtTrades() {
  const rows = [...bt.trades].sort((a, b) => b.fill_time.localeCompare(a.fill_time));
  const first = pageStart(rows.length, bt.pg);
  renderPager($("#btPager"), rows.length, bt.pg, renderBtTrades, $("#btTradesHead"));
  const res = { target: pill("pos", "target"), stop: pill("neg", "stop"), open: pill("warn", "open") };
  $("#btTrades tbody").innerHTML = rows.slice(first, first + bt.pg.size).map((t, i) => `<tr>
    <td class="num">${first + i + 1}</td><td><b>${t.symbol}</b></td><td>${pill(t.side, t.side)}</td>
    <td>${t.pattern} ${t.grade}${t.tests ? ' <span class="small">tested</span>' : ""}</td>
    <td>${t.aligned ? '<span class="small">with</span>' : `<span class="pill warn" data-tip="againstHtf">against</span>`}</td>
    <td class="small">${fmtTime(t.signal_time)}</td><td>${fmtTime(t.fill_time)}</td>
    <td>${fmt(t.fill)}</td><td>${fmt(t.stoploss)}</td><td>${fmt(t.target)}</td>
    <td>${fmtTime(t.exit_time)}</td><td>${fmt(t.exit)}</td><td>${res[t.result]}</td><td>${signed(t.r_net)}</td></tr>`).join("");
}

function renderBacktest(final) {
  $("#btResults").hidden = bt.meta.length === 0;
  renderBtCards();
  renderBtPerSym();
  if (final) {                        // heavier parts only once at the end
    renderBtChart();
    renderBtGroups();
    renderBtTrades();
  }
}

async function runBacktest(e) {
  e.preventDefault();
  const typed = $("#btSyms").value.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
  const symbols = typed.length ? typed : state.settings.watchlist;
  bt.trades = []; bt.meta = []; bt.pg.page = 1; bt.symPg.page = 1;
  bt.rr = Number($("#btRr").value) || 5;
  const q = new URLSearchParams({
    ltf: $("#btLtf").value, reward_ratio: $("#btRr").value, capital: $("#btCapital").value,
    risk_pct: $("#btRisk").value, min_grade: $("#btGrade").value, sides: $("#btSides").value,
    aligned_only: $("#btAligned").checked, cost_pct: $("#btCost").value || 0,
  });
  $("#btRun").disabled = true;
  let done = 0;
  const queue = [...symbols];
  const worker = async () => {
    while (queue.length) {
      const sym = queue.shift();
      try {
        const r = await api(`/api/backtest/${encodeURIComponent(sym)}?${q}`);
        bt.trades.push(...r.trades);
        bt.meta.push({ symbol: r.symbol, from: r.from, to: r.to });
      } catch (err) {
        const msg = err.message === "Not Found"
          ? "Backtest API not found: the server is running old code. Stop it (Ctrl+C) and start it again." : err.message;
        bt.meta.push({ symbol: sym, error: msg, from: "", to: "" });
      }
      done++;
      $("#btProgress").textContent = `${done} / ${symbols.length} stocks…`;
      renderBacktest(false);
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  renderBacktest(true);
  $("#btRun").disabled = false;
  $("#btProgress").textContent = `Done · ${bt.trades.length} trades`;
}

function showView(view) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  $("#scanView").hidden = view !== "scan";
  $("#controls").hidden = view !== "scan";
  $("#btView").hidden = view !== "backtest";
  $("#jnView").hidden = view !== "journal";
  if (view === "journal") loadJournal();
  if (view === "backtest" && !$("#btRr").value && state.settings) {
    $("#btRr").value = state.settings.reward_ratio;
    $("#btCapital").value = state.settings.capital;
    $("#btRisk").value = state.settings.risk_pct;
  }
  if (view === "backtest" && bt.chart) renderBtChart();     // re-size after being hidden
}

document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
$("#btForm").addEventListener("submit", runBacktest);
