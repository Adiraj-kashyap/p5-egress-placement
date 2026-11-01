# `demo/` — the explanatory walkthrough and live demonstration (M20, M22)

A local Streamlit app in 11 chapters that explains the whole project — problem, prices,
workloads, cost model, solvers, the three hypothesis verdicts with their statistics, the
ablation, the testbed and the limits — while still solving placements live and running the
measure → optimise loop against the kind testbed. It makes **no
network calls**: prices come from the committed `cost_model/2026-09-21/`, topologies from
`topologies/`, and the replicated results from `demo/cache/` (copies of the M18 figure CSVs).

## Run it

One command (cache check, offline preflight, then the app on http://localhost:8501):

```
.\run_demo.ps1          # add -Full to include the Docker/kind checks
```

or double-click `run_demo.bat` (`run_demo.bat full` for the Docker/kind checks).

Or step by step:

```
.\.venv\Scripts\python.exe -m demo.build_cache        # once, or after any results change
.\.venv\Scripts\python.exe -m demo.preflight          # --offline to skip Docker/kind
.\.venv\Scripts\streamlit.exe run demo/app.py
```

The chapter map is [`docs/review3/walkthrough.md`](../docs/review3/walkthrough.md); the runbook
for the day, with the 5-minute script and the fallbacks, is
[`docs/review3/demo_runbook.md`](../docs/review3/demo_runbook.md).

## Files

| File | What it does |
|---|---|
| `app.py` | Entry point: `st.navigation` over the chapters, in reading order. |
| `chapters/` | One script per chapter (`00_start.py` … `10_conclusion.py`). Not named `pages/`: that name switches on Streamlit's legacy auto-discovery, which serves pages without running `app.py` (a test guards this). |
| `ui.py` | Shared page frame (callouts, verdict chips, Next links) and the chart helpers with the validated colour slots. |
| `explain.py` | Loaders for prices, topologies, verdicts, tables and threats — every number a chapter shows. No Streamlit. |
| `core.py` | Instances, solver calls, cost rows, cache reading. No Streamlit, no network. |
| `testbed.py` | `kubectl` / `locust` wrappers behind timeouts; they return messages, never raise. |
| `preflight.py` | The pre-demo check list; exit 1 if anything required fails. |
| `build_cache.py` | Copies the figure CSVs the chapters plot into `cache/` and writes `manifest.json`. |
| `cache/` | R2-1, F0–F7 figure CSVs and `manifest.json`. |

## Rules this code follows

- **Every cost shown is `placement.cost.evaluate`** (D-006). `core.run_methods` scores every
  method's assignment with it, including the baselines, so the demo can never disagree with
  the experiments. A test asserts this.
- **Solver calls are never cached** — it is a *live* demo. Only the cached CSVs use
  `st.cache_data`, and only built instances (prices, no solving) use `st.cache_resource`.
- **No number is typed into a chapter.** Text around the numbers is prose; the numbers are
  read from the files each chapter lists under *Source files*.
- **Restart Streamlit after editing any `demo/*.py`.** A running server re-runs the page
  scripts but keeps imported modules in memory.
- **No single-run values are plotted** (non-negotiable 8). Every cached curve carries `n`,
  a mean and a 95 % CI; a test rejects any cached row with `n < 3`.
- **The traffic slider means what the sweep means**: `s` multiplies inter-component edges
  only, internet egress unchanged, via `experiments.uncertainty.scale_edges`.
- **The ILP is capped at 30 s in the demo** (`core.DEMO_TIME_LIMIT_S`), not the 600 s the
  experiments use, and the app says whether the answer was proven optimal. T3 solves in
  about 0.15 s.
- **`locust` is never imported in-process** (D-084) — it monkey-patches gevent and fails once
  `ssl` has been imported. It is only ever run as a subprocess.

## When results change

Re-run `python -m demo.build_cache` after any change to `figures/`. `demo.build_cache --check`
(part of preflight and of `tests/test_demo.py`) fails if the cache has drifted from its sources.
