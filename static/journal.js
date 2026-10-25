// Journal tab: weekly forward test of the zones (see app/journal.py).
const jn = { data: null, pg: { page: 1, size: 25 }, poll: null };

Object.assign(TIPS, {
  jnWick: "<b>Touch stop</b>: the trade is stopped as soon as any wick touches the stop loss.",
  jnClose: "<b>Closing-basis stop</b>: the trade is stopped only when a 2h candle CLOSES beyond the stop loss (exit at that close, so a loss can be more than 1R).",
  jnBackfilled: "Saved after the week had already finished, so its result was not followed live. 'Live only' shows the honest forward-test numbers.",
});

const R = (v) => v === null || v === undefined ? "–" : signed(v, 2);

function jnResult(z, track) {
  const res = z[`${track}_result`];
  if (!res) return '<span class="small">–</span>';
  const r = z[`${track}_r`];
  const label = { target: pill("pos", "target"), stop: pill("neg", "stop"), open: pill("warn", "running") }[res];
  const when = z[`${track}_exit_time`] ? ` <span class="small">${fmtTime(z[`${track}_exit_time`]).slice(0, 10)}</span>` : "";
  return `${label} ${R(r)}${when}`;
}

function renderJnCards() {
  const d = jn.data, s = d.status;
  const card = (title, big, sub = "") => `<div class="card"><h4>${title}</h4><div class="big">${big}</div><div class="small">${sub}</div></div>`;
  const live = d.zones.filter((z) => !z.backfilled).length;
  $("#jnCards").innerHTML =
    card("Zones saved", d.zones.length, `${d.weeks.length} weeks · ${live} ${tip("jnBackfilled", "live")}`) +
    card("Waiting", s.waiting, "price not back at entry yet") +
    card("Filled · running", s.filled, "entry reached, trade open") +
    card("Finished", s.done, "target or stop hit (both rules)") +
    card("Broken", s.broken, "opened beyond the stop before filling") +
    card("Expired", s.expired, `not touched in ${d.settings.expiry_weeks} weeks`);
}

function renderJnGroups() {
  const cells = (t) => `<td>${t.trades}${t.running ? ` <span class="small">+${t.running} running</span>` : ""}</td>
    <td>${t.win_rate === null ? "–" : fmt(t.win_rate, 1) + "%"}</td><td>${R(t.avg_r)}</td><td>${R(t.total_r)}</td>`;
  $("#jnGroups tbody").innerHTML = jn.data.groups.map((g) =>
    `<tr><td><b>${g.name}</b></td><td>${g.zones}</td>${cells(g.close)}${cells(g.wick)}</tr>`).join("");
}

function jnFiltered() {
  const w = $("#jnFWeek").value, st = $("#jnFStatus").value;
  return jn.data.zones.filter((z) => (!w || z.found_week === w) && (!st || z.status === st)
    && (!$("#jnFSetup").checked || z.is_setup) && (!$("#jnFA").checked || z.grade === "A"));
}

function renderJnZones() {
  const rows = jnFiltered();
  const first = pageStart(rows.length, jn.pg);
  renderPager($("#jnPager"), rows.length, jn.pg, renderJnZones);
  const stCls = { waiting: "neutral", filled: "warn", done: "pos", broken: "neg", expired: "neutral" };
  $("#jnZones tbody").innerHTML = rows.slice(first, first + jn.pg.size).map((z, i) => `<tr>
    <td class="num">${first + i + 1}</td>
    <td class="small">${z.found_week}${z.backfilled ? ' <span data-tip="jnBackfilled">·bf</span>' : ""}</td>
    <td><a href="#" data-sym="${z.symbol}">${z.symbol}</a></td>
    <td>${pill(z.kind, z.pattern)}${z.is_setup ? ` ${pill(z.kind === "demand" ? "BUY" : "SELL", "setup")}` : ""}</td>
    <td><b>${z.grade}</b> <span class="small">${fmt(z.legin_x, 1)}× / ${fmt(z.legout_x, 1)}×</span></td>
    <td>${fmt(z.entry)}</td><td>${fmt(z.stoploss)}</td><td>${fmt(z.target)}</td>
    <td>${pill(stCls[z.status], z.status)}</td>
    <td class="small">${z.fill_time ? fmtTime(z.fill_time) : "–"}</td>
    <td>${jnResult(z, "close")}</td><td>${jnResult(z, "wick")}</td></tr>`).join("")
    || `<tr><td colspan="12" class="small">No zones match.</td></tr>`;
  document.querySelectorAll("#jnZones a[data-sym]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    showView("scan");
    openDetail(a.dataset.sym);
  }));
}

async function loadJournal() {
  try {
    jn.data = await api("/api/journal");
  } catch (e) {
    $("#jnProgress").innerHTML = `<span class="err">${e.message}</span>`;
    return;
  }
  $("#jnExpiry").textContent = jn.data.settings.expiry_weeks;
  $("#jnResults").hidden = jn.data.zones.length === 0;
  if (!jn.data.zones.length && !jn.data.job.running) {
    $("#jnProgress").textContent = "Journal is empty: press “Save & check now” to save last week's zones.";
  }
  const weeks = [...new Set(jn.data.zones.map((z) => z.found_week))];
  const sel = $("#jnFWeek"), cur = sel.value;
  sel.innerHTML = `<option value="">All</option>` + weeks.map((w) => `<option ${w === cur ? "selected" : ""}>${w}</option>`).join("");
  renderJnCards();
  renderJnGroups();
  renderJnZones();
  if (jn.data.job.running) pollJournal();
}

function pollJournal() {
  if (jn.poll) return;
  $("#jnRun").disabled = true;
  jn.poll = setInterval(async () => {
    const j = await api("/api/journal/status").catch(() => null);
    if (!j) return;
    $("#jnProgress").textContent = j.running ? `Working… ${j.done} / ${j.total} stocks (${j.message})`
      : j.error ? `Error: ${j.error}` : `Done ${j.finished ? "at " + j.finished.replace("T", " ") : ""}`;
    if (!j.running) {
      clearInterval(jn.poll);
      jn.poll = null;
      $("#jnRun").disabled = false;
      loadJournal();
    }
  }, 1500);
}

$("#jnRun").addEventListener("click", async () => {
  const w = $("#jnWeeks").value;
  await fetch(`/api/journal/run${w ? `?weeks=${w}` : ""}`, { method: "POST" });
  pollJournal();
});
["#jnFWeek", "#jnFStatus", "#jnFSetup", "#jnFA"].forEach((id) =>
  $(id).addEventListener("change", () => { jn.pg.page = 1; renderJnZones(); }));
