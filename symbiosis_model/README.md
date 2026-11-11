# Industrial Symbiosis Optimiser (real-data model)

Replaces the synthetic prototype. State-level exchange network for India built only from the project datasets in `data/`.

## Run
```bash
cd symbiosis_model
pip install -r requirements.txt
python scripts/precompute.py        # optional: regenerates results/ (about 1-2 min)
python app.py                       # http://localhost:5000
python -m pytest tests -q          # includes tests/test_advise.py for user mode
```

## Two modes (switch at the top right; the choice is remembered, `#dev` opens Developer directly)
**User mode** is for plant managers. Pick plant type (sugar mill, steel plant, cement plant, distillery), by-product, state, and optionally tonnes per year. There is no priority to choose: every possible partner gets a 0-100 match score built like the original prototype's (technical fit 30%, economics 25%, CO2 25%, use of waste 20%, each shown as its own factor), and the national plan is the single combined optimum of money, waste reused, haul distance and CO2. It returns the best destination or source, per-tonne economics with a low/high cost range, CO2, distance and road/rail, a map, what the national plan does with the state's material, questions to ask the other plant, and a confidence badge that lists the unsourced assumptions behind the result. The URL holds the selections, so a result can be shared. Code: `core/advise.py`, `static/user.js`, endpoints `/api/user/options` and `/api/user/advice`.

**Pin to pin (Maharashtra pilot)** is a second tab in User mode. Drop a pin on the exporter and one on the importer (drag to adjust); no plant register is needed. For that exact pair it returns road/rail distance (a routed road distance from the public OSRM service when the browser can reach it, otherwise straight line x 1.3), per-tonne net with a low/high range, CO2, the same four-factor match score, the break-even distance, a net-versus-distance curve, and the assumptions. Pins must fall inside an approximate Maharashtra bounding box. Code: `core/pin.py`, `static/pin.js`, endpoints `/api/pin/meta` and `/api/pin/analyse`; tests in `tests/test_pin.py`.

**Developer mode** is the original view: scenario controls, method comparison, Pareto front, flows, lanes, sensitivity, parameters, forecasting. It loads only when opened.

User mode needs no pymoo (it uses the exact LP plan); only live NSGA-II runs in Developer mode do.

## What it models
Three lanes (22 hub-state nodes, hub-to-hub road distances):
1. Steelmaking (LD/EAF) slag to cement plants as a raw-meal CaO source (compatibility 0.54, from step 1).
2. Bagasse fly ash to cement plants as a pozzolan (0.70).
3. Molasses to fuel-ethanol distilleries (0.94). The price is a transfer, so it counts as zero system benefit.

Objectives: net economic benefit, waste utilised, transport work (t-km), net CO2 avoided. Constraints: source supply, receiver absorption, minimum compatibility (default 0.50). Road or rail is chosen per arc from the parameter table.

## Methods compared
Nearest feasible, rule-based, economic-only (LP), weighted-sum (LP), NSGA-II (pymoo). Every objective is linear in the flows, so each LP solution is exactly optimal for its weights and serves as a benchmark for NSGA-II (hypervolume ratio reported per scenario).

## Not modelled yet (and why)
Press mud (no receiver demand data), blast-furnace slag (no state supply data; over 90% already used by cement), bagasse to cogeneration (in-plant use). Forecasting is a tested backtest harness (`core/forecast.py`) that refuses to run until `data/history_*.csv` hold at least 10 seasons.

## Read before presenting
All results are pipeline tests. In `data/model_parameters.csv`, every row marked `PLACEHOLDER` has no source (receiver absorption shares, slag and ash prices, processing costs, rail first/last mile, exchange rate). The sensitivity table shows `steel_slag_cement_share` moves utilisation more than any other parameter, so sourcing it is the highest-value next step. Region-to-state mappings are in `core/data.py`. Distances are straight-line hub estimates x 1.3.
