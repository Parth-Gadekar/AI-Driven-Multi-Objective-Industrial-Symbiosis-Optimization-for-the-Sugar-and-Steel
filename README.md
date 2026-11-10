# AI Driven Multi-Objective Industrial Symbiosis Optimization for the Sugar and Steel
The project of EDI for the 3rd semester 

An intelligent decision-support platform that identifies and recommends efficient exchange pathways for industrial by-products between the sugar, steel, and cement industries — turning one industry's waste into another's raw material.

Overview

Industrial processes generate large volumes of by-products — bagasse, press mud, bagasse ash, steel slag, blast furnace slag, fly ash — that are often underutilized or disposed of, despite having viable reuse potential in other industries. This project builds a platform that:

Analyzes industrial by-products and matches them with industries that can reuse them
Recommends matches based on material compatibility, quantity, transportation distance, market demand, economic feasibility, and environmental impact
Optimizes recommendations across multiple objectives — maximizing profit while minimizing transportation cost and carbon emissions
Visualizes matches and logistics on an interactive map

The goal is to make circular-economy collaboration between industries practical and data-driven, rather than something that relies on informal networks or chance.

## Code

`symbiosis_model/` holds the working model and website (Flask + plain JS). Run it with:

```bash
cd symbiosis_model
pip install -r requirements.txt
python app.py          # http://localhost:5000
python -m pytest tests -q
```

The site has two modes, switched at the top right:

- **User mode** is for plant managers. Choose plant type, by-product and state (tonnes per year optional) and get one best match. Every option has a 0-100 match score built from technical fit (30%), economics (25%), CO2 (25%) and use of waste (20%), each shown as its own factor, plus a map, per-tonne economics with a low/high range, questions to ask the other plant, and a confidence note listing the assumed inputs.
- **Developer mode** is the full analysis view: NSGA-II against four baselines, Pareto front, flows, sensitivity, parameters and the forecasting harness.

All results are planning-stage estimates at state level. Inputs marked `PLACEHOLDER` in `symbiosis_model/data/model_parameters.csv` are unsourced assumptions.
