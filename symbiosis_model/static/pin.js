/* Pin-to-pin tab (Maharashtra pilot): drop an exporter pin and an importer pin on a map and get the analysis for that pair.
   Talks to /api/pin/meta and /api/pin/analyse. The browser may refine the road distance with a public routing service
   (OSRM); if that fails, the server's straight-line x 1.3 estimate is used. Independent of user.js and app.js. */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0) => Number(v).toLocaleString("en-IN", { maximumFractionDigits: d });
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const inr = (v) => {
    const a = Math.abs(v), sg = v < 0 ? "−" : "";
    if (a >= 1e7) return sg + "₹" + num(a / 1e7, a >= 1e8 ? 0 : 1) + " crore";
    if (a >= 1e5) return sg + "₹" + num(a / 1e5, a >= 1e6 ? 0 : 1) + " lakh";
    return sg + "₹" + num(a);
  };
  const tons = (v) => (v >= 1e6 ? num(v / 1e6, 2) + " million t" : num(v) + " t");
  const FACTORS = [["compatibility", "Technical fit"], ["economic", "Economics"], ["co2", "CO₂"], ["utilization", "Use of waste"]];
  const STATUS = { PLACEHOLDER: ["Assumed", "PLACEHOLDER"], derived_estimate: ["Estimated", "derived_estimate"], assumption: ["Assumed", "PLACEHOLDER"] };
  const statusTag = (st) => { const [t, c] = STATUS[st] || ["Sourced", st]; return `<span class="tag ${esc(c)}">${t}</span>`; };
  const TITLES = {
    pay: { pays: "This exchange pays for itself", marginal: "This exchange only just pays", loses: "This exchange costs more than it earns" },
    cost: { pays: "Moving it this far is a small cost", marginal: "Moving it this far is a noticeable cost", loses: "Moving it this far is a large cost" },
  };

  const S = { material: "ASH_POZ", exp: null, imp: null, active: "exp", tonnes: null, cap: null };
  let META = null, map = null, markers = {}, line = null, chart = null, seq = 0, timer = null, data = null;
  const routed = new Map();     // "lat,lon;lat,lon" -> road km (or null when routing failed)

  /* ------------------------------ tabs ------------------------------ */
  function showTab(which) {
    const pin = which === "pin";
    $("tab-state").setAttribute("aria-selected", String(!pin));
    $("tab-pin").setAttribute("aria-selected", String(pin));
    $("u-state-flow").hidden = pin;
    $("u-pin-flow").hidden = !pin;
    if (pin) { initMap(); setTimeout(() => map && map.invalidateSize(), 60); }
  }

  /* ------------------------------ map ------------------------------ */
  function initMap() {
    if (map || !META) return;
    const [la0, la1, lo0, lo1] = META.bbox;
    map = L.map("pmap", { scrollWheelZoom: false, maxBounds: [[la0 - 1, lo0 - 1], [la1 + 1, lo1 + 1]], minZoom: 5 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(map);
    map.fitBounds([[la0, lo0], [la1, lo1]]);
    L.rectangle([[la0, lo0], [la1, lo1]], { color: "#888", weight: 1, dashArray: "4 6", fill: false, interactive: false }).addTo(map);
    map.on("click", (e) => place(S.active, [e.latlng.lat, e.latlng.lng]));
    drawPins();
  }
  const inBox = (p) => { const [la0, la1, lo0, lo1] = META.bbox; return p[0] >= la0 && p[0] <= la1 && p[1] >= lo0 && p[1] <= lo1; };
  function place(which, p) {
    if (!inBox(p)) { $("p-coords").textContent = "That spot is outside the Maharashtra pilot area. Drop the pin inside the dashed box."; return; }
    S[which] = [+p[0].toFixed(5), +p[1].toFixed(5)];
    if (which === "exp" && !S.imp) setActive("imp"); else if (which === "imp" && !S.exp) setActive("exp");
    drawPins(); run();
  }
  function setActive(w) { S.active = w; $("p-set-exp").setAttribute("aria-pressed", String(w === "exp")); $("p-set-imp").setAttribute("aria-pressed", String(w === "imp")); }
  function drawPins() {
    if (!map) return;
    for (const w of ["exp", "imp"]) {
      if (S[w]) {
        if (!markers[w]) {
          markers[w] = L.marker(S[w], { draggable: true, icon: L.divIcon({ className: "", html: `<span class="pinicon ${w}"></span>`, iconSize: [24, 24], iconAnchor: [12, 12] }) }).addTo(map);
          markers[w].bindTooltip(w === "exp" ? "Your plant" : "Receiving plant", { permanent: true, direction: "top", offset: [0, -12] });
          markers[w].on("dragend", () => { const ll = markers[w].getLatLng(); const p = [ll.lat, ll.lng]; if (!inBox(p)) { markers[w].setLatLng(S[w]); return; } S[w] = [+p[0].toFixed(5), +p[1].toFixed(5)]; drawPins(); run(); });
        } else markers[w].setLatLng(S[w]);
      } else if (markers[w]) { markers[w].remove(); markers[w] = null; }
    }
    if (line) { line.remove(); line = null; }
    if (S.exp && S.imp) {
      line = L.polyline([S.exp, S.imp], { color: "#1f6f5c", weight: 3, dashArray: "6 6" }).addTo(map);
      map.fitBounds(L.latLngBounds([S.exp, S.imp]).pad(0.5), { maxZoom: 10 });
    }
    const f = (p) => (p ? `${p[0].toFixed(4)}, ${p[1].toFixed(4)}` : "not placed yet");
    $("p-coords").textContent = `Your plant: ${f(S.exp)}  ·  Receiving plant: ${f(S.imp)}`;
  }

  /* ------------------------------ analysis ------------------------------ */
  async function osrm(a, b) {
    const key = a.join(",") + ";" + b.join(",");
    if (routed.has(key)) return routed.get(key);
    let km = null;
    try {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 5000);
      const r = await fetch(`https://router.project-osrm.org/route/v1/driving/${a[1]},${a[0]};${b[1]},${b[0]}?overview=false`, { signal: ctl.signal });
      clearTimeout(t);
      const j = await r.json();
      if (j && j.code === "Ok" && j.routes && j.routes[0] && j.routes[0].distance > 0) km = j.routes[0].distance / 1000;
    } catch (e) { km = null; }
    routed.set(key, km);
    return km;
  }
  function query(roadKm) {
    const q = new URLSearchParams({ material: S.material, exp_lat: S.exp[0], exp_lon: S.exp[1], imp_lat: S.imp[0], imp_lon: S.imp[1] });
    if (S.tonnes) q.set("tonnes", S.tonnes);
    if (S.cap) q.set("capacity", S.cap);
    if (roadKm) q.set("road_km", roadKm);
    return "/api/pin/analyse?" + q;
  }
  async function fetchAnalysis(roadKm) {
    const r = await fetch(query(roadKm)); const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Something went wrong");
    return j;
  }
  async function run() {
    if (!(S.exp && S.imp)) { $("p-result").hidden = true; $("p-empty").hidden = false; return; }
    const my = ++seq;
    $("p-result").style.opacity = ".55";
    try {
      data = await fetchAnalysis(null);
      if (my !== seq) return;
      render(); $("p-empty").hidden = true; $("p-result").hidden = false;
      const key = S.exp.join(",") + ";" + S.imp.join(",");
      const km = routed.has(key) ? routed.get(key) : await osrm(S.exp, S.imp);
      if (my !== seq) return;
      if (km) { const d2 = await fetchAnalysis(km); if (my !== seq) return; if (d2.distance.source === "routed") { data = d2; render(); } }
    } catch (e) {
      if (my !== seq) return;
      $("p-empty").hidden = true; $("p-result").hidden = false;
      $("p-hero").innerHTML = `<h2>No result</h2><p class="lead">${esc(e.message)}</p>`;
    } finally { if (my === seq) $("p-result").style.opacity = ""; }
  }

  function render() {
    const D = data, m = D.material, pt = D.per_tonne, dist = D.distance, cost = m.cost_only;
    const srcTxt = dist.source === "routed" ? "road distance from a routing service" : "estimated: straight line × 1.3";
    const t = TITLES[cost ? "cost" : "pay"][D.verdict];
    let econ;
    if (cost) econ = `Hauling costs about <b>${inr(pt.transport_inr)}</b> per tonne, ${num(100 * pt.transport_inr / pt.gross_value_inr, 1)}% of the molasses price.`;
    else if (pt.net_inr >= 0) econ = `After handling and hauling you keep about <b>${inr(pt.net_inr)}</b> per tonne.`;
    else econ = `After handling and hauling you lose about <b>${inr(-pt.net_inr)}</b> per tonne.`;
    const be = !cost && D.break_even_km != null
      ? ` At the assumed prices this exchange stops paying beyond about <b>${num(D.break_even_km)} km</b>; your pair is ${num(dist.km)} km.` : "";
    const lead = `${num(dist.km)} km by ${dist.mode} (${srcTxt}). ${econ}${be}`;

    const sg = cost ? -1 : 1, rg = pt.net_inr_range;
    const rangeTxt = `range ${inr(Math.min(sg * rg[0], sg * rg[1]))} to ${inr(Math.max(sg * rg[0], sg * rg[1]))}`;
    const co2 = pt.co2_net_t;
    const k = [
      [cost ? "Haul cost" : "Net per tonne", inr(sg * pt.net_inr) + " /t", rangeTxt],
      co2 < 0 ? ["CO₂ added by hauling", num(-co2, 2) + " t/t", "no CO₂ saving is counted for this material"] : ["CO₂ avoided", num(co2, 2) + " t/t", "after hauling emissions"],
      ["Distance", num(dist.km) + " km", `by ${dist.mode}`],
      D.annual ? [cost ? "Haul cost per year" : "Net per year", inr(sg * D.annual.net_inr), `for ${tons(D.annual.tonnes)} · range ${inr(Math.min(sg * D.annual.net_inr_range[0], sg * D.annual.net_inr_range[1]))} to ${inr(Math.max(sg * D.annual.net_inr_range[0], sg * D.annual.net_inr_range[1]))}`]
               : [cost ? "Share of price" : "Break-even distance", cost ? num(100 * pt.transport_inr / pt.gross_value_inr, 1) + "%" : (D.break_even_km != null ? num(D.break_even_km) + " km" : "n/a"), cost ? "haul cost over molasses price" : "beyond this it loses money"],
    ].map((x) => `<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b><small>${x[2]}</small></div>`).join("");

    const chips = FACTORS.map(([key, label]) => { const v = D.factors[key];
      return v === null ? `<span class="score-chip na" title="Not counted: ${key === "utilization" ? "enter both tonnes and the receiver's capacity" : "no saving for this material"}">${label} <b>–</b></span>` : `<span class="score-chip">${label} <b>${num(v * 100, 0)}</b></span>`; }).join("");
    const c = D.confidence;
    const mh = D.maharashtra;
    let fit = "";
    if (D.annual && D.annual.fits_capacity !== null) fit = `<p class="muted">${D.annual.fits_capacity ? "The receiver's stated capacity covers your tonnage." : "The receiver's stated capacity is below your tonnage, so only part of it could go there."}</p>`;
    $("p-hero").innerHTML = `<p class="eyebrow">Pin to pin · ${esc(m.exporter)} to ${esc(m.importer)} · ${esc(m.name)}</p><h2>${esc(t)}</h2><p class="lead">${lead}</p>
      <div class="kpis">${k}</div>${m.value_note ? `<p class="muted">${esc(m.value_note)}</p>` : ""}${fit}
      <div class="badges"><span class="badge high" title="Weighted score from four factors">Match score <b>${num(D.score, 0)} / 100</b></span>${chips}
      <span class="badge ${c.level}">Confidence: <b>${cap(c.level)}</b></span><button type="button" class="linkbtn" id="p-why">see why</button></div>
      <p class="muted">Maharashtra context from the state-level model: about ${tons(mh.supply_t)} a year of ${esc(m.short)} is produced and receivers across the state can absorb about ${tons(mh.receiver_capacity_t)} a year.</p>`;
    $("p-why").onclick = () => { const d = $("p-basis"); d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); };

    // chart
    const ctx = $("p-chart");
    if (chart) chart.destroy();
    const ylab = cost ? "Haul cost (₹ per tonne)" : "Net value (₹ per tonne)";
    chart = new Chart(ctx, { type: "line", data: { datasets: [
      { label: ylab, data: D.curve.map((p) => ({ x: p.km, y: p.value })), borderColor: "#1f6f5c", backgroundColor: "#1f6f5c", pointRadius: 0, borderWidth: 2, tension: 0 },
      { label: "Your pair", data: [{ x: dist.km, y: cost ? pt.transport_inr : pt.net_inr }], showLine: false, pointRadius: 7, pointHoverRadius: 8, backgroundColor: "#c2410c", borderColor: "#fff", borderWidth: 2 }] },
      options: { animation: false, responsive: true, maintainAspectRatio: false, parsing: false,
        scales: { x: { type: "linear", title: { display: true, text: "Haul distance (km)" } }, y: { title: { display: true, text: ylab } } },
        plugins: { legend: { position: "bottom" } } } });
    $("p-chart-note").textContent = cost
      ? "Molasses is paid for by the distillery at about ₹" + num(pt.gross_value_inr) + " per tonne; the line shows only the extra haul cost. The kink is where rail becomes cheaper than road."
      : "Above zero the exchange pays; below zero it loses money. The kink is where rail becomes cheaper than road. The line moves with the assumed prices (see confidence).";

    $("p-questions").innerHTML = D.questions.map((q) => `<li>${esc(q)}</li>`).join("");
    const as = c.assumptions.map((a) => `<tr><td class="l">${esc(a.label)}</td><td>${num(a.value, 2)} ${esc(a.unit)}</td><td>${num(a.range[0], 2)} to ${num(a.range[1], 2)}</td><td>${statusTag(a.status)}</td></tr>`).join("");
    $("p-basis-body").innerHTML = `<p class="assump">${cap(c.level)} confidence: ${c.placeholders} of ${c.assumptions.length} key inputs for ${esc(m.name.toLowerCase())} have no source yet and are assumptions. Replace them with your own prices before relying on any figure.</p>
      <div class="tablewrap"><table><thead><tr><th class="l">Input</th><th>Value used</th><th>Range tested</th><th>Status</th></tr></thead><tbody>${as}</tbody></table></div>
      <p>Haul cost uses the project's freight rates (road, or rail when the haul is 500 km or more and rail is cheaper). The match score uses the same four factors and weights as the state-level view: technical fit 30%, economics 25%, CO₂ 25%, use of waste 20%. Use of waste needs both your tonnes and the receiver's capacity; without them it is left out and the other weights scale up.</p>
      <p class="muted">Distance is ${dist.source === "routed" ? "a routed road distance" : "an estimate: straight line (" + num(dist.straight_km, 1) + " km) × 1.3"}. The pilot area is Maharashtra's bounding box, not its exact border. Pins are your own locations; no plant register is used.</p>`;
  }

  /* ------------------------------ form ------------------------------ */
  function renderMaterials() {
    $("p-materials").innerHTML = META.materials.map((m) => `<button type="button" class="chip" data-id="${m.id}" aria-pressed="${S.material === m.id}">${esc(m.name)}</button>`).join("");
    $("p-materials").querySelectorAll("button").forEach((b) => (b.onclick = () => { S.material = b.dataset.id; renderMaterials(); run(); }));
    const m = META.materials.find((x) => x.id === S.material);
    $("p-mat-note").textContent = `Sent by a ${m.exporter.toLowerCase()}, received by a ${m.importer.toLowerCase()}.`;
  }
  async function init() {
    $("tab-state").onclick = () => showTab("state");
    $("tab-pin").onclick = () => showTab("pin");
    try { META = await (await fetch("/api/pin/meta")).json(); } catch (e) { $("tab-pin").disabled = true; return; }
    renderMaterials();
    $("p-set-exp").onclick = () => setActive("exp");
    $("p-set-imp").onclick = () => setActive("imp");
    $("p-clear").onclick = () => { S.exp = S.imp = null; setActive("exp"); drawPins(); run(); if (map) map.fitBounds([[META.bbox[0], META.bbox[2]], [META.bbox[1], META.bbox[3]]]); };
    $("p-example").onclick = () => { initMap(); S.exp = [19.095, 74.749]; S.imp = [18.52, 73.86]; setActive("exp"); drawPins(); run(); };
    const numIn = (id, key) => ($(id).oninput = () => { clearTimeout(timer); timer = setTimeout(() => { const v = parseFloat($(id).value); S[key] = v > 0 ? v : null; run(); }, 450); });
    numIn("p-tonnes", "tonnes"); numIn("p-cap", "cap");
    $("mode-user").addEventListener("click", () => setTimeout(() => map && map.invalidateSize(), 100));
  }
  init();
})();
