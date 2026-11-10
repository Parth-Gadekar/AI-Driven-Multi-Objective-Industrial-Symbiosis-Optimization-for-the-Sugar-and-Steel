/* User mode: a plain-language "where can my by-product go" tool for plant managers, plus the User/Developer switch.
   Talks to /api/user/options and /api/user/advice. Independent of app.js (developer mode), which starts lazily. */
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
  const FACTORS = [["compatibility", "Technical fit"], ["economic", "Economics"], ["co2", "CO\u2082"], ["utilization", "Use of waste"]];
  const chipsFor = (o) => FACTORS.map(([k, label]) => { const v = o.factors[k];
    return v === null ? `<span class="score-chip na" title="Not counted for this material">${label} <b>\u2013</b></span>` : `<span class="score-chip">${label} <b>${num(v * 100, 0)}</b></span>`; }).join("");
  const PRODUCER = { STEEL_RAW: "steel plants", ASH_POZ: "sugar mills", MOL_DIST: "sugar mills" };
  const STATUS = { PLACEHOLDER: ["Assumed", "PLACEHOLDER"], derived_estimate: ["Estimated", "derived_estimate"], assumption: ["Assumed", "PLACEHOLDER"] };
  const statusTag = (st) => { const [t, c] = STATUS[st] || ["Sourced", st]; return `<span class="tag ${esc(c)}">${t}</span>`; };

  let OPT = null, S = { role: null, material: null, state: null, tonnes: null, season: "2024-25", case: "base" };
  let DATA = null, seq = 0, timer = null, umap = null, ulayer = null, showAll = false;

  /* ------------------------------ mode switch ------------------------------ */
  function setMode(m, persist = true) {
    document.body.dataset.mode = m;
    $("mode-user").setAttribute("aria-pressed", String(m === "user"));
    $("mode-dev").setAttribute("aria-pressed", String(m === "dev"));
    if (persist) { try { localStorage.setItem("symbiosis_mode", m); } catch (e) { /* storage may be blocked */ } }
    try { history.replaceState(null, "", location.pathname + location.search + (m === "dev" ? "#dev" : "")); } catch (e) { /* ignore */ }
    if (m === "dev") { window.DevMode.start(); setTimeout(() => window.DevMode.refresh(), 80); }
    else if (umap) setTimeout(() => umap.invalidateSize(), 80);
  }
  function initialMode() {
    if (location.hash === "#dev") return "dev";
    try { const m = localStorage.getItem("symbiosis_mode"); if (m === "dev" || m === "user") return m; } catch (e) { /* ignore */ }
    return "user";
  }

  /* ------------------------------ form ------------------------------ */
  const role = () => OPT.roles[S.role];
  const mats = () => (S.role ? role().materials : []);
  const mat = () => mats().find((m) => m.id === S.material);

  function renderRoles() {
    $("u-roles").innerHTML = Object.entries(OPT.roles).map(([id, r]) =>
      `<button type="button" class="rolecard" data-id="${id}" aria-pressed="${S.role === id}"><b>${esc(r.label)}</b><span>${esc(r.blurb)}</span></button>`).join("");
    $("u-roles").querySelectorAll("button").forEach((b) => (b.onclick = () => pickRole(b.dataset.id)));
  }
  function pickRole(id) {
    S.role = id;
    const ms = mats();
    if (!ms.some((m) => m.id === S.material)) S.material = ms.length === 1 ? ms[0].id : null;
    S.state = null;
    refresh();
  }
  function renderMaterials() {
    const ms = mats(), show = ms.length > 1;
    $("u-mat-step").hidden = !show;
    if (!show) return;
    $("u-mat-q").textContent = role().direction === "out" ? "Which by-product do you want to place?" : "Which by-product do you want to use?";
    $("u-materials").innerHTML = ms.map((m) => `<button type="button" class="chip" data-id="${m.id}" aria-pressed="${S.material === m.id}">${esc(m.name)}</button>`).join("");
    $("u-materials").querySelectorAll("button").forEach((b) => (b.onclick = () => { S.material = b.dataset.id; S.state = null; refresh(); }));
  }
  function renderStates() {
    const m = mat(), wrap = $("u-state-step");
    wrap.hidden = !m;
    if (!m) return;
    const sel = $("u-state");
    sel.innerHTML = '<option value="">Select your state…</option>' + m.states.map((s) => `<option value="${esc(s)}"${s === S.state ? " selected" : ""}>${esc(s)}</option>`).join("");
    const out = role().direction === "out";
    $("u-state-note").textContent = ((m.notes || {})[S.state] ? m.notes[S.state] + " " : "") +
      `Only states with modelled ${out ? "supply of" : "demand for"} ${m.name.toLowerCase()} are listed.`;
  }
  function renderRest() {
    const has = !!(S.role && S.material && S.state);
    $("u-tonnes-step").hidden = !has;
    $("u-more").hidden = !has;
    if (!has) return;
    $("u-tonnes-step").querySelector(".steph").firstChild.textContent = role().direction === "out" ? "How many tonnes do you produce a year? " : "How many tonnes do you need a year? ";
  }
  function refresh() {
    renderRoles(); renderMaterials(); renderStates(); renderRest();
    syncUrl();
    if (S.role && S.material && S.state) advise();
    else { $("u-result").hidden = true; $("u-empty").hidden = false; }
  }
  function syncUrl() {
    const p = new URLSearchParams();
    ["role", "material", "state", "tonnes", "season", "case"].forEach((k) => { if (S[k]) p.set(k, S[k]); });
    try { history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : "") + location.hash); } catch (e) { /* ignore */ }
  }
  function readUrl() {
    const p = new URLSearchParams(location.search);
    if (p.get("role") && OPT.roles[p.get("role")]) S.role = p.get("role");
    if (S.role) {
      const ms = mats(), m = p.get("material");
      S.material = ms.some((x) => x.id === m) ? m : ms.length === 1 ? ms[0].id : null;
      const st = p.get("state");
      if (mat() && mat().states.includes(st)) S.state = st;
    }
    if (p.get("tonnes") && +p.get("tonnes") > 0) S.tonnes = +p.get("tonnes");
    if (OPT.seasons.includes(p.get("season"))) S.season = p.get("season");
    if (OPT.cases.includes(p.get("case"))) S.case = p.get("case");
  }

  /* ------------------------------ advice ------------------------------ */
  async function advise() {
    const my = ++seq;
    const q = new URLSearchParams({ role: S.role, material: S.material, state: S.state, season: S.season, case: S.case });
    if (S.tonnes) q.set("tonnes", S.tonnes);
    $("u-result").style.opacity = ".55";
    try {
      const r = await fetch("/api/user/advice?" + q);
      const j = await r.json();
      if (my !== seq) return;
      if (!r.ok) throw new Error(j.error || "Something went wrong");
      DATA = j; render(); $("u-empty").hidden = true; $("u-result").hidden = false;
      drawMap();
    } catch (e) {
      if (my !== seq) return;
      $("u-result").hidden = false;
      $("u-hero").innerHTML = `<h2>No result</h2><p class="lead">${esc(e.message)}</p>`;
      ["u-callout-wrap", "u-plan-panel"].forEach((id) => ($(id).hidden = true));
    } finally { if (my === seq) $("u-result").style.opacity = ""; }
  }

  const distPhrase = (o) => (o.same_state ? "within your own state (about " + num(o.km) + " km, road)" : `${num(o.km)} km by ${o.mode}`);

  function render() {
    const D = DATA, m = D.material, s = D.summary, out = D.direction === "out", top = D.options[0], cost = m.cost_only;
    const partner = out ? m.partner : PRODUCER[m.id];
    const planPhrase = s.placed_t > 0;

    // ---- hero ----
    const title = out ? (top.same_state ? `Keep it in ${D.you.state}` : `Send it to ${top.state}`)
                      : (top.same_state ? `Source it within ${D.you.state}` : `Source it from ${top.state}`);
    const net = top.net_inr_t;
    const econ = cost ? `moving it costs about ${inr(-net)} per tonne`
      : net >= 0 ? `about ${inr(net)} per tonne after hauling`
      : `it costs about ${inr(-net)} more per tonne than it earns once hauling is counted`;
    const lead = `${cap(partner)} ${top.same_state ? "in your own state" : "in " + top.state} have the highest match score (${num(top.score, 0)} / 100): ${distPhrase(top)}, ${econ}. ` +
      `Here ${esc(m.name.toLowerCase())} is used as ${esc(m.use)}.`;

    const ann = s.annual;
    const per = planPhrase ? { net: s.avg_net_inr_t, lo: s.avg_net_inr_t_range[0], hi: s.avg_net_inr_t_range[1], co2: s.avg_co2_t_per_t, km: s.avg_km }
                           : { net: top.net_inr_t, lo: top.net_inr_t_range[0], hi: top.net_inr_t_range[1], co2: top.co2_t_per_t, km: top.km };
    const sgn = cost ? -1 : 1;
    const range = (lo, hi) => { const a = sgn * lo, b = sgn * hi; return `${inr(Math.min(a, b))} to ${inr(Math.max(a, b))}`; };
    const k1 = ann && planPhrase
      ? [cost ? "Estimated moving cost" : "Estimated net value", inr(sgn * ann.net_inr), `a year under the national plan${out && ann.moved_t < ann.tonnes * 0.995 ? " for the " + tons(ann.moved_t) + " the plan places" : ""} · range ${range(ann.net_inr_range[0], ann.net_inr_range[1])}`]
      : [cost ? "Moving cost" : "Net value", inr(sgn * per.net) + " /t", `per tonne, ${planPhrase ? "national plan average" : "top option"} · range ${range(per.lo, per.hi)}`];
    const yr = !!(ann && planPhrase), co2v = yr ? ann.co2_t : per.co2, co2u = yr ? "a year" : "per tonne";
    const k2 = co2v < 0 ? ["CO₂ added by hauling", num(-co2v, yr ? 0 : 2) + " t", co2u + "; no CO₂ saving is counted for this material"]
                        : ["CO₂ avoided", num(co2v, yr ? 0 : 2) + " t", co2u + ", after transport emissions"];
    const k3 = ["Typical haul", num(per.km) + " km", planPhrase ? "tonne-weighted, national plan" : "to the top option"];
    const k4 = out ? ["Placed by national plan", num(s.placed_pct, 0) + "%", `of ${esc(D.you.state)}'s ${esc(m.short)} (${tons(s.placed_t)} a year)`]
                   : ["Reaches your state", tons(s.placed_t), `a year under the plan; modelled capacity ${tons(s.own_total_t)}`];
    const kpis = [k1, k2, k3, k4].map((k) => `<div class="kpi"><span>${k[0]}</span><b>${k[1]}</b><small>${k[2]}</small></div>`).join("");

    const c = D.confidence, lvl = c.level;
    const conf = `<span class="badge ${lvl}">Confidence: <b>${cap(lvl)}</b></span> ` +
      `<span class="muted">${c.placeholders ? c.placeholders + " key input" + (c.placeholders > 1 ? "s are" : " is") + " assumed" : "inputs are mostly sourced"}</span> ` +
      `<button type="button" class="linkbtn" id="u-why">see why</button>` +
      ` <span class="badge high" title="Weighted score from four factors (see How is it chosen?)">Match score <b>${num(top.score, 0)} / 100</b></span> <span class="badge" title="How well the material suits this use: chemistry, standards, processing readiness and evidence">Technical fit ${D.compatibility.toFixed(2)} / 1</span>` +
      ` <span class="badge">State-level estimate</span>`;
    $("u-hero").innerHTML = `<p class="eyebrow">Best match for your ${esc(m.short)}</p><h2>${esc(title)}</h2><p class="lead">${lead}</p>` +
      `<p class="how muted"><b>One score, four factors.</b> Technical fit, economics, CO\u2082 and use of the waste are scored and combined into a single match score. <button type="button" class="linkbtn" id="u-how">How is it chosen?</button></p>` +
      `<div class="kpis">${kpis}</div>${m.value_note ? `<p class="muted">${esc(m.value_note)}</p>` : ""}<div class="badges">${conf}</div>`;
    $("u-how").onclick = () => { const d = $("u-basis"); d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); };
    $("u-why").onclick = () => { const d = $("u-basis"); d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); };

    // ---- callout ----
    let call = "";
    if (out && s.placed_pct < 90) {
      call = s.placed_t <= 0
        ? `The combined national plan does not move any of ${esc(D.you.state)}'s ${esc(m.short)}. The options below still show what each destination would cost you.`
        : `The national plan places only <b>${num(s.placed_pct, 0)}%</b> of ${esc(D.you.state)}'s ${esc(m.short)} (about ${tons(s.placed_t)} a year). The rest has no modelled home: receivers close by fill up, and farther ones cost more to reach than the material is worth. This depends heavily on the assumed limits under “What these numbers are based on”.`;
    } else if (!out && ann && ann.shortfall_t > 0) {
      call = `You asked for ${tons(ann.tonnes)}, but only about <b>${tons(s.placed_t)}</b> a year of ${esc(m.short)} reaches ${esc(D.you.state)} under the plan. About ${tons(ann.shortfall_t)} would have to come from elsewhere. Little is produced nearby, and hauling it from far away costs more than it saves.`;
    } else if (!out && s.placed_t <= 0) {
      call = `The combined national plan delivers no ${esc(m.short)} to ${esc(D.you.state)}. The options below still show what each source would cost.`;
    }
    if (!call && D.plan.length && top.plan_t <= 0) {
      const pt = D.plan[0];
      call = `${esc(top.state)} has the highest match score, but the combined national plan ${out ? "places" : "sources"} ${esc(D.you.state)}'s ${esc(m.short)} ${out ? "in" : "from"} <b>${esc(pt.state)}</b> instead (${tons(pt.plan_t)} a year). Receiver room is shared between every producer, and ${esc(top.state)}'s room goes to others.`;
    }
    $("u-callout-wrap").hidden = !call;
    $("u-callout-wrap").innerHTML = call ? `<div class="callout" role="note">${call}</div>` : "";

    // ---- option cards + table ----
    $("u-opts-h").textContent = out ? `Where your ${m.short} can go` : `Where your ${m.short} can come from`;
    const money = (o) => {
      const v = cost ? -o.net_inr_t : o.net_inr_t, lo = cost ? -o.net_inr_t_range[1] : o.net_inr_t_range[0], hi = cost ? -o.net_inr_t_range[0] : o.net_inr_t_range[1];
      return { v, lo, hi, neg: !cost && v < 0 };
    };
    const capLabel = out ? "Can absorb" : "Produces";
    $("u-top").innerHTML = D.options.slice(0, 3).map((o) => {
      const mo = money(o);
      const pill = o.plan_t > 0 ? '<span class="pill">In national plan</span>' : o.same_state ? '<span class="pill">Your state</span>' : "";
      return `<article class="opt-card ${o.rank === 1 ? "first" : ""}"><h3><span class="rank">${o.rank}</span>${esc(o.state)}${pill}</h3>
        <span class="muted">${esc(o.hub_city)} hub · ${distPhrase(o)}</span>
        <div class="big ${mo.neg ? "neg" : ""}">${inr(mo.v)} <span class="muted">/ tonne</span></div>
        <span class="muted">${cost ? "Haul cost" : mo.neg ? "Net loss after hauling" : "Net after hauling"} · range ${inr(mo.lo)} to ${inr(mo.hi)}</span>
        <div class="scorehead"><b>${num(o.score, 0)}</b><span>/ 100 match score</span></div><div class="score-row">${chipsFor(o)}</div>
        <dl><dt>CO₂ avoided</dt><dd>${num(o.co2_t_per_t, 2)} t per tonne</dd>
        <dt>${capLabel}</dt><dd>${tons(o.partner_size_t)} a year</dd>
        <dt>National plan</dt><dd>${o.plan_t > 0 ? num(o.plan_share_of_moved_pct, 0) + "% of moved tonnes" : "not used"}</dd></dl></article>`;
    }).join("");
    $("u-all").innerHTML = `<thead><tr><th class="l">#</th><th class="l">State</th><th>Score</th><th>Fit</th><th>Econ.</th><th>CO\u2082</th><th>Use</th><th>Distance</th><th>Mode</th><th>${cost ? "Haul cost /t" : "Net /t"}</th><th>Range /t</th><th>CO₂ /t</th><th>${capLabel}</th><th>Plan share</th></tr></thead><tbody>` +
      D.options.map((o) => { const mo = money(o); return `<tr class="${o.plan_t > 0 ? "plan" : ""}"><td class="l">${o.rank}</td><td class="l">${esc(o.state)}</td><td><b>${num(o.score, 0)}</b></td>${FACTORS.map(([k]) => `<td>${o.factors[k] === null ? "\u2013" : num(o.factors[k] * 100, 0)}</td>`).join("")}<td>${num(o.km)} km</td><td>${o.mode}</td>
        <td class="${mo.neg ? "neg" : ""}">${inr(mo.v)}</td><td>${inr(mo.lo)} to ${inr(mo.hi)}</td><td>${num(o.co2_t_per_t, 2)} t</td><td>${tons(o.partner_size_t)}</td><td>${o.plan_t > 0 ? num(o.plan_share_of_moved_pct, 0) + "%" : "–"}</td></tr>`; }).join("") + "</tbody>";
    $("u-all-wrap").hidden = !showAll;
    $("u-toggle-all").textContent = showAll ? "Hide the full list" : `Show all ${D.options.length} states`;

    // ---- national plan ----
    const rows = D.plan.map((o) => `<div class="bar-row"><span>${esc(o.state)}</span><span class="bar"><i style="width:${Math.min(100, o.plan_share_of_own_pct).toFixed(1)}%"></i></span><span>${tons(o.plan_t)} (${num(o.plan_share_of_own_pct, 0)}%)</span></div>`);
    const rest = 100 - s.placed_pct;
    if (rest > 0.5) rows.push(`<div class="bar-row none"><span>${out ? "Not placed" : "Capacity left unfilled"}</span><span class="bar"><i style="width:${rest.toFixed(1)}%"></i></span><span>${num(rest, 0)}%</span></div>`);
    let split = "";
    if (ann && planPhrase) split = `<p><b>Of your ${tons(ann.tonnes)} a year,</b> ` + (ann.split.length === 1
      ? `the plan ${out ? "sends" : "supplies"} ${tons(ann.moved_t)} ${out ? "to" : "from"} ${esc(ann.split[0].state)}.`
      : `${out ? "the plan would place about " + tons(ann.moved_t) : "about " + tons(ann.moved_t) + " can be supplied"}: ` +
        ann.split.map((x) => `${tons(x.tonnes)} ${out ? "to" : "from"} ${esc(x.state)}`).join(", ") + ".") + "</p>";
    $("u-plan-panel").innerHTML = `<h2>${out ? `What the national plan does with ${esc(D.you.state)}'s ${esc(m.short)}` : `Where the plan sources ${esc(D.you.state)}'s ${esc(m.short)} from`}</h2>
      <div class="bars">${rows.join("") || '<p class="muted">The combined plan moves nothing here.</p>'}</div>${split}
      <p class="muted">The plan is the best arrangement for the whole country at once. Receivers have limited room, so it can differ from the single best option for one plant.</p>`;

    // ---- questions + basis ----
    $("u-questions").innerHTML = D.questions.map((q) => `<li>${esc(q)}</li>`).join("");
    const as = c.assumptions.map((a) => `<tr><td class="l">${esc(a.label)}</td><td>${num(a.value, 2)} ${esc(a.unit)}</td><td>${num(a.range[0], 2)} to ${num(a.range[1], 2)}</td><td>${statusTag(a.status)}</td></tr>`).join("");
    const cb = D.combined, nat = cb.national;
    const how = `<h3 class="inh">How the match score works</h3>
      <p>Every possible partner gets a score from 0 to 100, built from four factors (each 0 to 100) with fixed weights. The highest score is your best match.</p>
      <div class="tablewrap"><table><thead><tr><th class="l">Factor</th><th>Weight</th><th class="l">What it measures</th></tr></thead><tbody>
      <tr><td class="l">Technical fit</td><td>30%</td><td class="l">How well the material suits this use: chemistry, standards, processing readiness, evidence. The same for every partner on one route.</td></tr>
      <tr><td class="l">Economics</td><td>25%</td><td class="l">Value left after handling and hauling, as a share of the material's value. A long haul that eats the value scores 0.</td></tr>
      <tr><td class="l">CO\u2082</td><td>25%</td><td class="l">Share of the CO\u2082 saving left after hauling emissions. Not counted for molasses (no saving is modelled), so the other weights scale up.</td></tr>
      <tr><td class="l">Use of waste</td><td>20%</td><td class="l">Share of ${esc(D.you.state)}'s material the combined national plan sends to this partner, weighted by technical fit.</td></tr></tbody></table></div>
      <p class="muted">Same four factors and weights as the project's first prototype. Routes with technical fit under 0.50 are removed before scoring.</p>
      <p>The <b>national plan</b> behind the last factor looks at many possible arrangements for the whole country and takes the one closest to the best achievable on money, waste reused, haul distance and CO\u2082 at once (found by ${cb.method === "NSGA-II" ? "NSGA-II, a multi-objective search" : "linear programming over many weightings"}). It moves ${tons(nat.utilised_t)} a year, avoids ${num(nat.net_co2_t / 1e6, 2)} million t of CO\u2082 and averages a ${num(nat.mean_haul_km)} km haul.</p>
      <h3 class="inh">What it rests on</h3>`;
    $("u-basis-body").innerHTML = how + `<p class="assump">${cap(lvl)} confidence: ${c.placeholders} of ${c.assumptions.length} key inputs for ${esc(m.name.toLowerCase())} have no source yet and are assumptions. Replace them with your own plant's numbers before relying on any figure.</p>
      <div class="tablewrap"><table><thead><tr><th class="l">Input</th><th>Value used</th><th>Range tested</th><th>Status</th></tr></thead><tbody>${as}</tbody></table></div>
      <dl class="gloss"><dt>Net per tonne</dt><dd>What the material is worth to the receiver, minus handling cost, minus transport cost. The range comes from low and high cost assumptions for prices and freight.</dd>
      <dt>Technical fit</dt><dd>A 0–1 score for how well the material suits the receiver (chemistry, standards, processing, evidence). Routes below 0.50 are left out.</dd>
      <dt>CO₂ avoided</dt><dd>Emissions saved by replacing cement or limestone, minus the emissions of hauling it.</dd>
      <dt>National plan</dt><dd>One arrangement for every producer and receiver in the country, chosen by weighing money, waste reused, haul distance and CO\u2082 together (see \u201CHow the match score works\u201D).</dd>
      <dt>State-level</dt><dd>Distances run from one hub city per state to another, not from plant to plant, and a haul inside a state is assumed to be 50 km.</dd></dl>`;
  }

  /* ------------------------------ map ------------------------------ */
  function drawMap() {
    const D = DATA, out = D.direction === "out";
    if (!umap) { umap = L.map("umap", { scrollWheelZoom: false }).setView([22.5, 79], 5); L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(umap); }
    if (ulayer) ulayer.remove();
    ulayer = L.layerGroup().addTo(umap);
    const css = getComputedStyle(document.body), acc = css.getPropertyValue("--acc").trim() || "#1f6f5c";
    const you = D.you.ll, pts = [you], maxT = Math.max(...D.plan.map((r) => r.plan_t), 1);
    const shown = D.options.slice(0, 5).concat(D.plan.filter((p) => p.rank > 5));
    shown.forEach((o) => {
      if (o.same_state) return;
      pts.push(o.ll);
      const inPlan = o.plan_t > 0;
      L.polyline(out ? [you, o.ll] : [o.ll, you], { color: inPlan ? acc : "#888", weight: inPlan ? 2 + 5 * Math.sqrt(o.plan_t / maxT) : 2, dashArray: inPlan ? null : "5 6", opacity: 0.85 })
        .bindTooltip(`#${o.rank} ${o.state}: ${num(o.km)} km by ${o.mode}${inPlan ? ", in national plan" : ""}`).addTo(ulayer);
      L.circleMarker(o.ll, { radius: o.rank === 1 ? 8 : 5, color: "#fff", weight: 1.5, fillColor: o.rank === 1 ? acc : "#666", fillOpacity: 1 })
        .bindTooltip(`#${o.rank} ${o.state}`).addTo(ulayer);
    });
    if (D.options.some((o) => o.same_state)) L.circle(you, { radius: 60000, color: acc, weight: 2, fillOpacity: 0.12 }).bindTooltip("Receivers inside your own state").addTo(ulayer);
    L.circleMarker(you, { radius: 9, color: "#fff", weight: 2, fillColor: acc, fillOpacity: 1 }).bindTooltip(`You (${D.you.hub_city}, ${D.you.state})`, { permanent: true, direction: "top" }).addTo(ulayer);
    setTimeout(() => { umap.invalidateSize(); if (pts.length > 1) umap.fitBounds(L.latLngBounds(pts).pad(0.25)); else umap.setView(you, 6); }, 60);
  }

  /* ------------------------------ init ------------------------------ */
  async function init() {
    $("mode-user").onclick = () => setMode("user");
    $("mode-dev").onclick = () => setMode("dev");
    setMode(initialMode(), false);
    try { OPT = await (await fetch("/api/user/options")).json(); } catch (e) { $("u-empty").innerHTML = "<h2>Could not load</h2><p class='muted'>The server did not respond. Please refresh.</p>"; return; }
    $("u-season").innerHTML = OPT.seasons.map((s) => `<option${s === S.season ? " selected" : ""}>${s}</option>`).join("");
    readUrl();
    $("u-case").value = S.case; $("u-season").value = S.season;
    if (S.tonnes) $("u-tonnes").value = S.tonnes;
    $("u-state").onchange = () => { S.state = $("u-state").value || null; refresh(); };
    $("u-tonnes").oninput = () => { clearTimeout(timer); timer = setTimeout(() => { const v = parseFloat($("u-tonnes").value); S.tonnes = v > 0 ? v : null; refresh(); }, 450); };
    $("u-season").onchange = () => { S.season = $("u-season").value; refresh(); };
    $("u-case").onchange = () => { S.case = $("u-case").value; refresh(); };
    $("u-toggle-all").onclick = () => { showAll = !showAll; if (DATA) render(); };
    refresh();
  }
  init();
})();
