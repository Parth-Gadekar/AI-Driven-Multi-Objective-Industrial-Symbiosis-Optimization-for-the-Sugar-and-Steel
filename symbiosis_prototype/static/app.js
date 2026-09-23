let materialsCache = [];
let rankChart = null;

async function loadMaterials() {
  const res = await fetch("/api/materials");
  materialsCache = await res.json();
}

function showMaterialInfo(materialId) {
  const box = document.getElementById("material-info");
  const m = materialsCache.find((x) => x.id === materialId);
  if (!m) {
    box.classList.add("hidden");
    return;
  }
  box.textContent = `${m.description} Typical ratio: ${m.typical_ratio}.`;
  box.classList.remove("hidden");
}

function fmtINR(n) {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

function fmtKg(n) {
  const rounded = Math.round(n);
  return rounded.toLocaleString("en-IN") + " kg";
}

function renderChart(recommendations) {
  const ctx = document.getElementById("rankChart");
  const labels = recommendations.map((r) => r.industry);
  const data = recommendations.map((r) => r.final_score);
  const mlData = recommendations.map((r) => r.ml_predicted_score);

  if (rankChart) rankChart.destroy();
  rankChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Rule-engine score",
          data,
          backgroundColor: "#1e6f5c",
          borderRadius: 4,
        },
        {
          label: "ML model prediction",
          data: mlData,
          backgroundColor: "#d98e04",
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true, max: 1, title: { display: true, text: "Score (0-1)" } },
      },
      plugins: {
        legend: { position: "bottom" },
        title: { display: true, text: "Ranked recommendations" },
      },
    },
  });
}

function renderCards(recommendations) {
  const container = document.getElementById("cards");
  container.innerHTML = "";

  recommendations.forEach((r) => {
    const card = document.createElement("div");
    card.className = "card" + (r.rank === 1 ? " rank-1" : "");

    const mlLine =
      r.ml_predicted_score === null || r.ml_predicted_score === undefined
        ? ""
        : `<p class="ml-note">ML model independently predicted ${r.ml_predicted_score.toFixed(
            3
          )} for this pairing (rule engine: ${r.final_score.toFixed(3)}).</p>`;

    card.innerHTML = `
      <div class="card-top">
        <h3>#${r.rank} ${r.industry}</h3>
        <span class="rank-badge">score ${r.final_score.toFixed(3)}</span>
      </div>
      <p class="reuse-type">${r.reuse_type || ""}</p>
      <div class="score-row">
        <span class="score-chip">Compatibility <b>${r.compatibility_score.toFixed(2)}</b></span>
        <span class="score-chip">Economic <b>${r.economic_score.toFixed(2)}</b></span>
        <span class="score-chip">CO₂ <b>${r.co2_score.toFixed(2)}</b></span>
        <span class="score-chip">Utilization <b>${r.utilization_score.toFixed(2)}</b></span>
      </div>
      <div class="detail-grid">
        <div>Revenue <span>${fmtINR(r.revenue_inr)}</span></div>
        <div>Transport cost <span>${fmtINR(r.transport_cost_inr)}</span></div>
        <div>Net value <span>${fmtINR(r.net_value_inr)}</span></div>
        <div>CO₂ avoided <span>${fmtKg(r.co2_avoided_kg)}</span></div>
        <div>CO₂ from transport <span>${fmtKg(r.co2_transport_kg)}</span></div>
        <div>Net CO₂ avoided <span>${fmtKg(r.net_co2_avoided_kg)}</span></div>
      </div>
      ${mlLine}
    `;
    container.appendChild(card);
  });
}

async function handleSubmit(e) {
  e.preventDefault();
  const material_id = document.getElementById("material").value;
  const quantity_tonnes = document.getElementById("quantity").value;
  const distance_km = document.getElementById("distance").value;

  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ material_id, quantity_tonnes, distance_km }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.error || "Something went wrong.");
    return;
  }

  const payload = await res.json();

  document.getElementById("results-empty").classList.add("hidden");
  document.getElementById("results-content").classList.remove("hidden");

  document.getElementById("model-status").textContent = payload.model_loaded
    ? "ML model: loaded and scoring alongside the rule engine."
    : "ML model: not found — run ml/train_model.py. Showing rule-engine scores only.";

  renderChart(payload.recommendations);
  renderCards(payload.recommendations);
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadMaterials();
  document.getElementById("material").addEventListener("change", (e) => {
    showMaterialInfo(e.target.value);
  });
  document.getElementById("recommend-form").addEventListener("submit", handleSubmit);
});
