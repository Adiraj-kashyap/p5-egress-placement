# `review/` — terminal screens for the live review

Double-click any file, or run `RUN_ALL.bat` in the repo root to go through all of them in
order and finish in the browser walkthrough. Every screen starts with a box saying **what it
does** and **what to look for**, then waits for a key so you can talk.

Nothing here touches a cloud account, and nothing overwrites committed results: the scripts
that write output are pointed at `logs/review_runs/` (git-ignored). The terminal views
(`python -m demo.show ...`) use the same loaders and solvers as the browser app, so the two
always show the same numbers.

| File | Shows | Time |
|---|---|---|
| `01_environment.bat` | Python, solver, a tiny CBC solve where ignoring egress costs 19 % | 2 s |
| `02_pricing.bat` | AWS / Azure / GCP compute, egress rules R1-R3, storage, 10/10 validation checks | 2 s |
| `03_workloads.bat` | T1-T3 component graphs and the bytes measured on the testbed | 2 s |
| `04_live_solve.bat [T1\|T2\|T3] [s]` | Live solve: ILP vs SA vs greedy vs B1/B2, placement and bill per method | 2-5 s |
| `05_traffic_sweep.bat [T1\|T2\|T3]` | ILP vs B1 for s = 0.01 ... 100: optimum stays on one provider (H3) | 3 s |
| `06_experiment_scripts.bat` | The real baseline, exact-ILP and heuristic experiment scripts | 5 s |
| `07_experiment_runner.bat` | The resumable experiment runner on the smoke grid | 20 s |
| `08_results_and_verdicts.bat` | Replication guard, verdicts/tables regenerate identically, H1-H3 verdicts | 12 s |
| `09_testbed_live.bat` | 60 s locust run on the kind cluster; falls back to the saved measurement | 75 s |
| `testbed_up.bat` | Creates / deploys the kind cluster (Docker Desktop must be running) | 3 min |
| `10_tests.bat [args]` | Full pytest suite | 4 min |
| `11_frontend.bat` | The 11-chapter browser walkthrough at http://localhost:8501 | - |

Numbers to expect (they come from the committed price snapshot of 2026-09-21):

- `04_live_solve.bat T1 1`: ILP USD 481.18/month (proven optimal), B1 USD 497.58, B1 pays 3.41 % more.
- `04_live_solve.bat T2 1`: ILP USD 1,028.79, B1 USD 1,303.65, 26.72 % more.
- `05_traffic_sweep.bat T2`: at s = 100 the ILP is still USD 1,028.79 on one provider; B1 is
  USD 28,511.82, a 2,671 % penalty.

`_env.bat` and `_pause.bat` are helpers the others call; they do nothing on their own.
