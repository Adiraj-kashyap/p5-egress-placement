# Egress-Aware Cost-Optimal Placement Across AWS, Azure and GCP

Decide which cloud provider and region each component of an application should run in, so
that the **total monthly bill is minimal**. That bill includes compute, storage *and* the
per-GB egress charged when components talk across providers or regions. Egress couples the
decisions together, so the cheapest region per component is not the cheapest placement.

The project:
1. pulls the real public price lists of AWS, Azure and GCP into a unified cost model,
2. measures real inter-component traffic from a three-tier app running on a local `kind` cluster,
3. compares an exact **ILP** (PuLP + CBC) with an egress-aware **greedy** heuristic,
   **simulated annealing**, and single-provider baselines,
4. tests three pre-registered hypotheses with replicated experiments.

> No cloud resources are ever created. Only public price lists are read, and the testbed runs locally.

## Requirements

- Windows 10/11 (the launchers are `.bat`/`.ps1`; the Python code also runs on Linux/macOS)
- Python **3.12**
- *Optional, only for the live testbed:* Docker Desktop. `kind`/`kubectl` are expected in `.tools/bin/`.

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate                    # Linux/macOS: source .venv/bin/activate
pip install -r requirements.lock.txt      # exact versions used for all committed results
python verify_env.py                      # must end with "ENVIRONMENT OK"
```

Optional: copy `.env.example` to `.env` and set `GCP_API_KEY`. You only need it to re-pull
GCP prices; every committed result uses the snapshots already in `snapshots/`.

## Run

| Goal | Command | Time |
|---|---|---|
| Interactive walkthrough (browser, http://localhost:8501) | `run_demo.bat`  *(or `.\run_demo.ps1`)* | ~10 s to start |
| Every terminal demo screen in order, then the walkthrough | `RUN_ALL.bat`  *(`RUN_ALL.bat nopause` to run straight through)* | ~3 min |
| One live solve: ILP vs SA vs greedy vs baselines | `review\04_live_solve.bat T2 1` | ~5 s |
| Tests, offline subset (same as CI) | `pytest -q -m "not live and not testbed"` | ~4 min |
| Regenerate figures, tables and verdicts | `python -m analysis.figures`, `python -m analysis.tables --latex`, `python -m analysis.verdicts` | ~1 min |
| Re-run an experiment grid | `python -m experiments.runner smoke --out logs/smoke` | ~20 s |
| Bring up the local testbed (Docker running) | `review\testbed_up.bat`, then `review\09_testbed_live.bat` | ~3 min |

See [`review/README.md`](review/README.md) for every demo screen, [`demo/README.md`](demo/README.md)
for the walkthrough app, and [`testbed/README.md`](testbed/README.md) to reproduce the traffic measurements.

## Results (price snapshot 2026-09-21)

| Hypothesis | Verdict | In short |
|---|---|---|
| H1: the egress-aware ILP cuts cost ≥ 20 % vs B1 (cheapest-per-vCPU, egress ignored) | **Refuted** | Only T2 clears it (22.6 %); T1 3.3 %, T3 1.8 % |
| H2: SA stays within 5 % of the optimum while running ≥ 10× faster than the ILP | **Refuted** | Gap 0.10 % ✓, but speed-up 0.63× ✗ |
| H3: a traffic-scale crossover (10⁻² to 10²) exists where the optimum switches to a single provider | **Refuted** | No crossover: the optimum is single-provider at every scale |

Full statistics are in [`docs/report/verdicts.md`](docs/report/verdicts.md), with tables in `docs/report/tables/`.
The thresholds were frozen before any result existed ([`docs/methodology/`](docs/methodology/)).

## Repository layout

| Path | Contents |
|---|---|
| `pricing/` | price-list pullers (AWS, Azure, GCP) and the cost-model builder |
| `snapshots/<date>/` | raw pulled price JSON: the provenance of every price |
| `cost_model/<date>/` | unified `compute.csv`, `storage.csv`, `egress.csv`, `internet.csv` |
| `topologies/` | application graphs T1–T3 (components, directed edges, GB/month) |
| `testbed/` | local three-tier app, k8s manifests, locust load, byte counters |
| `placement/` | cost evaluator, baselines, ILP, greedy, simulated annealing |
| `experiments/` | instance generator and resumable experiment runners |
| `results/<exp_id>/` | `runs.csv` + `config.json` for every experiment |
| `analysis/`, `figures/` | statistics, verdicts, tables; each `F*.png` with its source `F*.csv` |
| `demo/`, `review/` | Streamlit walkthrough and terminal demo screens |
| `paper/` | LaTeX paper (`main.tex`, generated `numbers.tex` and tables) |
| `docs/` | report, review packs, methodology, design decisions (`D-xxx` ids cited in code) |
| `evidence/` | screenshots and console logs backing the reported numbers |

## Conventions

- Money in USD per month; a month is **730 h**; traffic in **GB/month**.
- A location is `"<provider>:<region>"`, e.g. `aws:us-east-1`.
- Edges are directed and egress is charged to the sender.
- `placement/cost.py::evaluate` is the **only** cost function, so every method is scored identically.
