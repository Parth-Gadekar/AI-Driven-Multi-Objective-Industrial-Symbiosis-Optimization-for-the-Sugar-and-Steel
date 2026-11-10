/* Frontend for the Industrial Symbiosis Optimiser. Plain JS + Chart.js + Leaflet. */
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (v === null || v === undefined || isNaN(v)) ? "-" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d });
const cr = (inr) => (inr / 1e7);                         // INR -> crore
const AX = {
  net_economic_benefit_inr: { label: "Net economic benefit (INR crore/yr)", f: (v) => cr(v) },
  waste_utilised_t: { label: "Waste utilised (Mt/yr)", f: (v) => v / 1e6 },
  transport_work_tkm: { label: "Transport work (million t-km/yr)", f: (v) => v / 1e6 },
  net_co2_avoided_t: { label: "Net CO2 avoided (Mt/yr)", f: (v) => v / 1e6 },
};
const AXKEYS = Object.keys(AX);
const COLORS = { nearest_feasible: "#8a6d3b", rule_based: "#7a5ea8", economic_only: "#c2543a", weighted_sum: "#2b7bb9", nsga2_compromise: "#1f6f5c" };
let META = null, RES = null, pareto = null, map = null, layer = null;

function el(tag, attrs = {}, html = "") { const e = document.createElement(tag); Object.assign(e, attrs); e.innerHTML = html; return e; }
function setTable(id, head, rows, leftCols = 1) {
  const t = $(id);
  t.innerHTML = "<thead><tr>" + head.map((h, i) => `<th class="${i < leftCols ? "l" : ""}">${h}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map((r) => "<tr" + (r._cls ? ` class="${r._cls}"` : "") + ">" + r.cells.map((c, i) => `<td class="${i < leftCols ? "l" : ""}">${c}</td>`).join("") + "</tr>").join("") + "</tbody>";
}

async function init() {
  META = await (await fetch("/api/meta")).json();
  META.seasons.forEach((s) => $("season").add(new Option(s, s, false, s === "2024-25")));
  META.cases.forEach((c) => { $("case").add(new Option(c, c, false, c === "base")); $("cost_case").add(new Option(c, c, false, c === "base")); });
  AXKEYS.forEach((k) => { $("xaxis").add(new Option(AX[k].label, k, false, k === "transport_work_tkm")); $("yaxis").add(new Option(AX[k].label, k, false, k === "waste_utilised_t")); });
  META.methods.forEach((m) => $("method").add(new Option(META.labels[m], m, false, m === "nsga2_compromise")));
  document.querySelectorAll(".w").forEach((s) => { const o = s.parentElement.querySelector("output"); const u = () => (o.textContent = Number(s.value).toFixed(2)); s.oninput = u; u(); });
  $("threshold").oninput = () => ($("thr_out").textContent = Number($("threshold").value).toFixed(2));
  $("run").onclick = runLive; $("reset").onclick = loadPre;
  ["xaxis", "yaxis"].forEach((i) => ($(i).onchange = drawPareto));
  $("method").onchange = drawMatches;
  renderParams(); loadSens(); loadForecast();
  await loadPre();
}

async function loadPre() {
  $("status").textContent = "Loading precomputed result...";
  const r = await fetch(`/api/result?season=${$("season").value}&case=${$("case").value}`);
  if (!r.ok) { $("status").textContent = "No precomputed result for this selection. Press Run live."; return; }
  RES = await r.json(); $("status").textContent = `Precomputed (${RES.nsga2.pop} x ${RES.nsga2.gens} NSGA-II). Cost case, threshold and weights shown are the defaults.`; render();
}

async function runLive() {
  const btn = $("run"); btn.disabled = true; $("status").textContent = "Running baselines, LP front and NSGA-II...";
  const body = { season: $("season").value, case: $("case").value, cost_case: $("cost_case").value, steel_year: $("steel_year").value,
    threshold: Number($("threshold").value), weights: { economic: +$("w_economic").value, utilisation: +$("w_utilisation").value, transport_work: +$("w_transport_work").value, co2: +$("w_co2").value },
    nsga: true, pop: 100, gens: 100 };
  try {
    const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || "run failed");
    RES = j; $("status").textContent = `Live run done in ${j.runtime_s}s (NSGA-II ${j.nsga2.pop} x ${j.nsga2.gens}).`; render();
  } catch (e) { $("status").textContent = "Error: " + e.message; } finally { btn.disabled = false; }
}

function render() { renderCompare(); drawPareto(); drawMatches(); renderLanes(); }

function renderCompare() {
  const M = RES.methods, order = META.methods.filter((m) => M[m]);
  const best = (key, hi) => order.reduce((a, b) => ((hi ? M[b].summary[key] > M[a].summary[key] : M[b].summary[key] < M[a].summary[key]) ? b : a));
  const bu = best("utilised_pct_of_supply", true), bb = best("net_benefit_inr", true), bt = best("mean_haul_km", false), bc = best("net_co2_t", true);
  setTable("cmp", ["Method", "Utilised % of supply", "Waste utilised (Mt)", "Net benefit (INR crore)", "Mean haul (km)", "Transport work (M t-km)", "Net CO2 avoided (Mt)", "Feasible"],
    order.map((m) => { const s = M[m].summary; return { _cls: m === "nsga2_compromise" ? "best" : "", cells: [
      `<span style="color:${COLORS[m]}">&#9679;</span> ${M[m].label}`,
      fmt(s.utilised_pct_of_supply, 1) + (m === bu ? " *" : ""), fmt(s.utilised_t / 1e6, 2), fmt(cr(s.net_benefit_inr), 1) + (m === bb ? " *" : ""),
      fmt(s.mean_haul_km, 0) + (m === bt ? " *" : ""), fmt(s.transport_work_tkm / 1e6, 0), fmt(s.net_co2_t / 1e6, 2) + (m === bc ? " *" : ""), M[m].feasible ? "yes" : "NO"] }; }));
  const n = RES.nsga2, k = M.nsga2_compromise ? M.nsga2_compromise.summary : M.weighted_sum.summary;
  $("kpis").innerHTML = [["Utilised", fmt(k.utilised_pct_of_supply, 1) + "%", "of eligible supply"], ["Waste moved", fmt(k.utilised_t / 1e6, 2) + " Mt", "per year"],
    ["Net benefit", "INR " + fmt(cr(k.net_benefit_inr), 0) + " cr", "after transport"], ["Mean haul", fmt(k.mean_haul_km, 0) + " km", "tonne-weighted"], ["Net CO2 avoided", fmt(k.net_co2_t / 1e6, 2) + " Mt", "after transport"]]
    .map((x) => `<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b><span>${x[2]}</span></div>`).join("");
  $("nsga_note").textContent = (n ? `NSGA-II front: ${n.front_size} solutions; hypervolume ${(n.hv_ratio_vs_lp * 100).toFixed(0)}% of the LP weighted-sum reference (above 100% means NSGA-II covers gaps the coarse weight grid misses). ` : "") +
    "* = best of the five on that column. Highlighted row is the NSGA-II compromise (closest to the ideal point). All objectives are linear, so each LP solution is exactly optimal for its weights.";
}

function drawPareto() {
  const xk = $("xaxis").value, yk = $("yaxis").value, ix = AXKEYS.indexOf(xk), iy = AXKEYS.indexOf(yk);
  const pts = (arr) => arr.map((p) => ({ x: AX[xk].f(p[ix]), y: AX[yk].f(p[iy]) }));
  const ds = [{ label: "LP weighted-sum front", data: pts(RES.front.lp_natural), backgroundColor: "rgba(43,123,185,.45)", pointRadius: 4 }];
  if (RES.front.nsga2_natural) ds.unshift({ label: "NSGA-II front", data: pts(RES.front.nsga2_natural), backgroundColor: "rgba(31,111,92,.45)", pointRadius: 4 });
  const keyOf = { net_economic_benefit_inr: "net_benefit_inr", waste_utilised_t: "utilised_t", transport_work_tkm: "transport_work_tkm", net_co2_avoided_t: "net_co2_t" };
  META.methods.filter((m) => RES.methods[m]).forEach((m) => { const s = RES.methods[m].summary;
    ds.push({ label: RES.methods[m].label, data: [{ x: AX[xk].f(s[keyOf[xk]]), y: AX[yk].f(s[keyOf[yk]]) }], backgroundColor: COLORS[m], borderColor: "#fff", borderWidth: 1.5, pointRadius: 8, pointStyle: "rectRot" }); });
  if (pareto) pareto.destroy();
  pareto = new Chart($("pareto"), { type: "scatter", data: { datasets: ds }, options: { responsive: true, maintainAspectRatio: false, animation: false,
    scales: { x: { title: { display: true, text: AX[xk].label } }, y: { title: { display: true, text: AX[yk].label } } }, plugins: { legend: { position: "bottom" } } } });
}

function drawMatches() {
  const m = RES.methods[$("method").value] || RES.methods.weighted_sum, rows = m.flows;
  if (!map) { map = L.map("map", { scrollWheelZoom: false }).setView([22.5, 79], 5); L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(map); }
  if (layer) layer.remove(); layer = L.layerGroup().addTo(map);
  const col = { STEEL_RAW: "#c2543a", ASH_POZ: "#7a5ea8", MOL_DIST: "#1f6f5c" }, maxT = Math.max(...rows.map((r) => r.tonnes), 1);
  rows.filter((r) => r.from !== r.to).forEach((r) => L.polyline([r.from_ll, r.to_ll], { color: col[r.lane], weight: 1 + 5 * Math.sqrt(r.tonnes / maxT), opacity: .6 })
    .bindTooltip(`${r.material}: ${r.from} to ${r.to}<br>${fmt(r.tonnes)} t, ${fmt(r.km)} km (${r.mode})`).addTo(layer));
  const nodes = {}; rows.forEach((r) => { nodes[r.from] = r.from_ll; nodes[r.to] = r.to_ll; });
  Object.entries(nodes).forEach(([n, ll]) => L.circleMarker(ll, { radius: 4, color: "#333", weight: 1, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(n).addTo(layer));
  setTimeout(() => map.invalidateSize(), 50);
  setTable("flows", ["Material", "From", "To", "Tonnes/yr", "% of source", "km", "Mode", "Compat.", "Transport cost (INR lakh)", "Net benefit (INR lakh)", "CO2 avoided (t)", "CO2 transport (t)"],
    rows.slice(0, 40).map((r) => ({ cells: [r.material, r.from, r.to, fmt(r.tonnes), fmt(r.share_of_source_pct, 1), fmt(r.km), r.mode, r.compatibility, fmt(r.transport_cost_inr / 1e5, 1), fmt(r.net_benefit_inr / 1e5, 1), fmt(r.co2_avoided_t), fmt(r.co2_transport_t, 1)] })), 3);
  if (rows.length > 40) $("flows").appendChild(el("caption", {}, `Top 40 of ${rows.length} flows by tonnage.`));
}

function renderLanes() {
  setTable("lanes", ["Lane", "Receiver", "Compat.", "Eligible", "Supply (Mt)", "Receiver cap (Mt)", "Note"],
    RES.lanes.map((l) => ({ cells: [l.material, l.receiver, l.compat, l.eligible ? "yes" : "no (below threshold)", fmt(l.supply_t / 1e6, 2), fmt(l.cap_t / 1e6, 2), `<span class="muted">${l.note}</span>`] })), 2);
  $("notmod").innerHTML = RES.not_modelled.map((n) => `<li><b>${n.lane}:</b> ${n.reason}</li>`).join("");
}

function renderParams() {
  setTable("params", ["Parameter", "Base", "Low", "High", "Unit", "Status", "Basis"],
    META.params.map((p) => ({ cells: [p.parameter, p.base, p.low, p.high, p.unit, `<span class="tag ${p.status}">${p.status}</span>`, `<span class="muted">${p.basis}</span>`] })));
}

async function loadSens() {
  const rows = await (await fetch("/api/sensitivity")).json();
  if (!rows.length) { $("sens").innerHTML = "<caption>Run scripts/precompute.py to generate.</caption>"; return; }
  rows.sort((a, b) => Math.abs(b.d_util_pct) + Math.abs(b.d_benefit_inr) / 1e9 - Math.abs(a.d_util_pct) - Math.abs(a.d_benefit_inr) / 1e9);
  setTable("sens", ["Parameter", "Status", "Setting", "Value", "Change in utilised %", "Change in net benefit (INR crore)", "Change in net CO2 (Mt)"],
    rows.slice(0, 16).map((r) => ({ cells: [r.parameter, `<span class="tag ${r.status}">${r.status}</span>`, r.setting, r.value, fmt(r.d_util_pct, 1), fmt(cr(r.d_benefit_inr), 1), fmt(r.d_co2_t / 1e6, 3)] })), 2);
}

async function loadForecast() {
  const f = await (await fetch("/api/forecast")).json();
  $("forecast").innerHTML = f.map((s) => s.status === "ok"
    ? `<p><b>${s.series}</b>: model ${s.model_used} (beats naive on backtest: ${s.beats_naive}). Forecast: ${s.forecast.map((v) => fmt(v, 1)).join(", ")}</p>`
    : `<p><b>${s.series}</b>: <span class="tag PLACEHOLDER">${s.status}</span> ${s.n_points !== undefined ? `${s.n_points} points available, ${s.needed} needed for a backtest.` : ""} Add a longer series to <code>data/history_${s.series}.csv</code>.</p>`).join("");
}

window.DevMode = { started: false,
  start() { if (this.started) return; this.started = true; init(); },
  refresh() { if (map) map.invalidateSize(); if (pareto) pareto.resize(); } };
