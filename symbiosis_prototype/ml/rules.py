"""
rules.py — deterministic scoring engine for the Industrial Symbiosis prototype.

This is the ground truth for what a "good match" means. It's used two ways:
  1. Directly, at request time, by app.py to compute an explainable breakdown.
  2. Indirectly, by generate_training_data.py, which labels synthetic examples
     with this engine's output so the Random Forest has something to learn to
     approximate.

IMPORTANT — read before the review:
All ₹/tonne, kg-CO2/tonne and kg-CO2/tonne-km constants below are PLACEHOLDER
ASSUMPTIONS, not measured/quoted market data. They are set to plausible,
defensible orders of magnitude so the demo produces sensible-looking rankings.
Two are grounded in something real:
  - TRANSPORT_EMISSION_FACTOR_KG_CO2_PER_TONNE_KM is in the range reported by
    the UK Government GHG Conversion Factors for heavy goods vehicle freight.
  - The India grid emission factor is in the range reported by the CEA CO2
    Baseline Database for the Indian power sector (used only if you extend
    this to score power-avoidance for the cogeneration pathway).
Everything else (per-tonne market values, landfill cost) should be replaced
with cited numbers (ISMA / JPC / CPCB, etc.) before the final review.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# PLACEHOLDER CONSTANTS — replace with cited figures before the final review
# ---------------------------------------------------------------------------

# Approximate market/avoided-cost value of one tonne of each material to the
# *receiving* industry (₹/tonne). Rough, order-of-magnitude placeholders.
MATERIAL_VALUE_INR_PER_TONNE = {
    "bagasse": 2500,
    "press_mud": 800,
    "molasses": 9000,
    "bagasse_ash": 600,
    "blast_furnace_slag": 1800,
    "steel_slag": 900,
    "mill_scale": 3500,
    "fly_ash": 700,
    "bottom_ash": 400,
}

# CO2 avoided per tonne of material diverted from landfill/disposal and reused
# instead of the receiving industry using virgin raw material (kg CO2/tonne).
# Cement-substitution materials (slag, fly ash) get the highest values since
# they displace clinker, which is the most carbon-intensive input in cement.
CO2_AVOIDED_KG_PER_TONNE = {
    "bagasse": 350,
    "press_mud": 150,
    "molasses": 200,
    "bagasse_ash": 300,
    "blast_furnace_slag": 900,
    "steel_slag": 500,
    "mill_scale": 400,
    "fly_ash": 850,
    "bottom_ash": 300,
}

# Transport cost placeholder (₹ per tonne-km).
TRANSPORT_COST_INR_PER_TONNE_KM = 3.5

# Transport emission factor — grounded in UK Govt HGV freight conversion
# factor range (kg CO2 per tonne-km).
TRANSPORT_EMISSION_FACTOR_KG_CO2_PER_TONNE_KM = 0.10

# India grid emission factor placeholder, per CEA CO2 Baseline Database
# range (kg CO2/kWh) — kept here for future use (e.g. scoring cogeneration
# power-offset pathways), not currently used in the score below.
INDIA_GRID_EMISSION_FACTOR_KG_CO2_PER_KWH = 0.82

# Reference quantity (tonnes) used to normalize the utilization score, i.e.
# "what's a large enough exchange to count as fully utilizing the match".
UTILIZATION_REFERENCE_TONNES = 500

# Scoring weights — must sum to 1.0. Tunable; exposed here so both the rule
# engine and any UI "what matters most to you" control can share them.
DEFAULT_WEIGHTS = {
    "compatibility": 0.30,
    "economic": 0.25,
    "co2": 0.25,
    "utilization": 0.20,
}


@dataclass
class ScoreBreakdown:
    material_id: str
    industry: str
    quantity_tonnes: float
    distance_km: float
    compatibility_score: float
    economic_score: float
    co2_score: float
    utilization_score: float
    final_score: float
    revenue_inr: float
    transport_cost_inr: float
    net_value_inr: float
    co2_avoided_kg: float
    co2_transport_kg: float
    net_co2_avoided_kg: float
    reuse_type: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def economic_score(material_id: str, quantity: float, distance_km: float) -> tuple[float, float, float, float]:
    """Returns (normalized_score_0_1, revenue, transport_cost, net_value)."""
    value_per_tonne = MATERIAL_VALUE_INR_PER_TONNE.get(material_id, 0)
    revenue = quantity * value_per_tonne
    transport_cost = quantity * distance_km * TRANSPORT_COST_INR_PER_TONNE_KM
    net_value = revenue - transport_cost
    # Normalize: net value as a fraction of gross revenue, floored at 0.
    # A trip so long it eats all the value scores 0 rather than going negative.
    if revenue <= 0:
        return 0.0, revenue, transport_cost, net_value
    normalized = _clip01(net_value / revenue)
    return normalized, revenue, transport_cost, net_value


def co2_score(material_id: str, quantity: float, distance_km: float) -> tuple[float, float, float, float]:
    """Returns (normalized_score_0_1, co2_avoided, co2_from_transport, net_co2_avoided)."""
    avoided_per_tonne = CO2_AVOIDED_KG_PER_TONNE.get(material_id, 0)
    co2_avoided = quantity * avoided_per_tonne
    co2_transport = quantity * distance_km * TRANSPORT_EMISSION_FACTOR_KG_CO2_PER_TONNE_KM
    net_co2_avoided = co2_avoided - co2_transport
    if co2_avoided <= 0:
        return 0.0, co2_avoided, co2_transport, net_co2_avoided
    normalized = _clip01(net_co2_avoided / co2_avoided)
    return normalized, co2_avoided, co2_transport, net_co2_avoided


def utilization_score(quantity: float, compatibility_score: float) -> float:
    """
    How well this exchange 'uses up' the waste stream at meaningful scale,
    weighted by how compatible the pairing is in the first place (a huge
    quantity going to a poor-fit industry shouldn't score as fully utilized).
    """
    scale_fraction = _clip01(quantity / UTILIZATION_REFERENCE_TONNES)
    return _clip01(scale_fraction * compatibility_score + (1 - compatibility_score) * 0.1)


def compute_score(
    material_id: str,
    industry: str,
    compatibility_score: float,
    quantity: float,
    distance_km: float,
    reuse_type: str = "",
    weights: dict | None = None,
) -> ScoreBreakdown:
    weights = weights or DEFAULT_WEIGHTS

    econ_norm, revenue, transport_cost, net_value = economic_score(material_id, quantity, distance_km)
    co2_norm, co2_avoided, co2_transport, net_co2 = co2_score(material_id, quantity, distance_km)
    util = utilization_score(quantity, compatibility_score)

    final = (
        weights["compatibility"] * compatibility_score
        + weights["economic"] * econ_norm
        + weights["co2"] * co2_norm
        + weights["utilization"] * util
    )

    return ScoreBreakdown(
        material_id=material_id,
        industry=industry,
        quantity_tonnes=quantity,
        distance_km=distance_km,
        compatibility_score=round(compatibility_score, 4),
        economic_score=round(econ_norm, 4),
        co2_score=round(co2_norm, 4),
        utilization_score=round(util, 4),
        final_score=round(final, 4),
        revenue_inr=round(revenue, 2),
        transport_cost_inr=round(transport_cost, 2),
        net_value_inr=round(net_value, 2),
        co2_avoided_kg=round(co2_avoided, 2),
        co2_transport_kg=round(co2_transport, 2),
        net_co2_avoided_kg=round(net_co2, 2),
        reuse_type=reuse_type,
    )
