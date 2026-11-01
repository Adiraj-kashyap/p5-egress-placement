# Walkthrough — the explanatory demo (M22)

The project's final showcase is a guided, live frontend rather than a recorded video
(MIG-003, D-087). Anyone can open it and follow the work from the question to the verdicts
without a presenter: each chapter says what is on screen, how to read it, and the takeaway,
and ends with a **Next** link. It still solves placements live and still measures the
Kubernetes testbed, so it doubles as the live demonstration for Review 3.

## Launch

From the repo root (Windows PowerShell):

```
.\.venv\Scripts\python.exe -m demo.preflight --offline   # every line OK
.\.venv\Scripts\streamlit.exe run demo/app.py            # opens http://localhost:8501
```

Drop `--offline` to also check Docker, the kind cluster and its pods (needed only for the
live measurement in chapter 9; without them chapter 9 uses the committed measurement and
says so). Each chapter has a stable address, e.g. `http://localhost:8501/h3`.

## Chapter map

| # | Chapter | Address | What it shows | Interactive |
|---|---|---|---|---|
| 0 | Start here | `/` | The question, objectives O1–O4, hypotheses H1–H3 with their verdicts, and the chapter map | links |
| 1 | Pricing data | `/pricing` | O1: compute price per vCPU-hour per location, the full egress price matrix (rules R1–R3), internet and storage prices, the 10/10 validation | core / ext switch, hover |
| 2 | Workloads | `/workloads` | T1–T3 as graphs with GB/month on every edge; where T1's measured volumes come from | workload switch |
| 3 | Cost model | `/cost_model` | O2: the cost formula, and a sandbox to place each component yourself, re-priced live by `evaluate`, against B1 and the proven optimum | every placement |
| 4 | Solvers, live | `/solvers` | O3: ILP, greedy + 1-opt, annealing, B1, B2-best solved live; placement and bill breakdown per method | workload, scale, methods, seed |
| 5 | H1 egress penalty | `/h1` | ILP reduction over B1 with 95 % CIs against the 20 % threshold; cost per method over 30 draws; T-H1 and the verdict text | topology |
| 6 | H2 heuristics | `/h2` | Optimality gap and runtime vs size, inside an annealing run; T-H2 and the clause-by-clause verdict | location set |
| 7 | H3 traffic sweep | `/h3` | A live ILP and B1 solve at any traffic scale; cost, penalty and providers used across s = 0.01–100 with CIs; why there is no crossover | topology, scale |
| 8 | Why: ablation | `/why` | Which ingredient causes the gain (F6) and how the saving moves with egress price and region count (F7), plus the five-line answer | topology, scale |
| 9 | Live testbed | `/testbed` | Cluster status, a live locust measurement (or the committed one), and T1 re-optimised from it | buttons |
| 10 | Limits and conclusion | `/conclusion` | Objectives, verdicts, what they mean, and all 29 threats to validity by category | expanders |

## Reading order on review day

Self-guided: start at chapter 0 and press **Next**. Presented (5 minutes): follow the script
in [`demo_runbook.md`](demo_runbook.md), which visits 0 → 4 → 5 → 7 → 9 and closes on 10.

## Where the numbers come from

No number is typed into a page. Each chapter's **Source files** box lists the committed files
it reads: `cost_model/2026-09-21/*.csv`, `topologies/*.json`, `testbed/measurements/summary.csv`,
the replicated figure CSVs (copied into `demo/cache/` with a sha256 manifest), and the
generated `docs/report/verdicts.md` and `docs/report/tables/h1_replicated.md`. Live numbers
come from the solvers and `placement.cost.evaluate`, the same function the experiments use.
Every plotted replicated value carries n and a 95 % CI.

## Checks

`tests/test_walkthrough.py` renders every chapter headless (Streamlit `AppTest`), clicks the
live solve, the sandbox and the testbed fallback, and checks that the verdicts, hypotheses and
prices shown match their source files.
