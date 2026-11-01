# Review 1 — Evidence index

Each Review-1 rubric line (from `docs/methodology/project_brief.md §7`) is mapped to files in this
repository. All paths are relative to the repo root. Commit hashes are the ones that closed
each module (`state/STATE.md`). Pricing snapshot in use: **2026-09-21**.

Screenshot status: ✅ present · ❌ **MISSING**. All 8 Review-1 screenshots are present (H-13 done 2026-09-22).
The rubric says "slides alone = 0" for the testbed line, so the screenshots matter.

---

## R1 — Literature survey (12–15 papers ≥ 2021, gap table) · 3 marks · M01 (commit `d07839d`)

| Evidence | Path | What it shows |
|---|---|---|
| Gap table (14 verified rows) | `docs/review1/gap_table.md` | Papers, year, venue, what each prices, limitation, `verified=yes` |
| Verification record | `docs/review1/lit_verification.csv` | URL fetched, title and year confirmed for every row |
| Closest prior work | `docs/review1/closest_prior_work.md` | SkyPilot (NSDI 2023) and why P5's claim is narrower |
| Acceptance output | `logs/M01_acceptance_checks.txt` | Row count, year and verification checks |
| Decisions | `docs/design_decisions.md` D-013 to D-016 | Seed errors found and corrected, two rows dropped |

## R2 — Problem statement + falsifiable hypothesis · 2 marks · M09

| Evidence | Path | What it shows |
|---|---|---|
| Problem statement | `docs/review1/problem_statement.md` | Problem in our words, O1–O4, scope |
| Hypotheses | `docs/review1/hypotheses.md` | H1–H3 frozen text, standard form, falsification test, experiment |
| Frozen source | `docs/methodology/project_brief.md §4` | Thresholds fixed before any result |

## R3 — Testbed / environment evidence (screenshots, logs) · 3 marks · M00, M02–M05, M07

### Environment (M00, commit `3c76e41`)

| Evidence | Path | Status |
|---|---|---|
| Screenshot: `verify_env.py` output | `evidence/screenshots/M00_verify_env.png` | ✅ present (H-01 done 2026-09-22) |
| Console log: `verify_env.py` | `evidence/logs/M00_verify_env.txt` | ✅ |
| Machine spec | `evidence/logs/machine.txt` | ✅ |
| Pinned dependencies | `requirements.lock.txt` | ✅ |

### Pricing pulls and cost model (M02 `49144f3`, M03 `89e6907`, M04 `c96d388`, M05 `7580fb0`)

| Evidence | Path | Status |
|---|---|---|
| Screenshot: Azure pull | `evidence/screenshots/M02_azure_pull.png` | ✅ present (H-04 done 2026-09-22) |
| Screenshot: AWS pull | `evidence/screenshots/M03_aws_pull.png` | ✅ present (H-04 done 2026-09-22) |
| Screenshot: GCP pull | `evidence/screenshots/M04_gcp_pull.png` | ✅ present (H-04 done 2026-09-22) |
| Screenshot: cost-model validation | `evidence/screenshots/M05_cost_model.png` | ✅ present (H-04 done 2026-09-22) |
| Console log: Azure Retail Prices API pull | `evidence/logs/M02_azure_pull.txt` | ✅ |
| Console log: AWS Price List bulk pull | `evidence/logs/M03_aws_pull.txt` | ✅ |
| Console log: GCP public pricing pages | `evidence/logs/M04_gcp_pull.txt`, `evidence/logs/M04_acceptance.txt` | ✅ |
| Console log: cost-model build + validation | `evidence/logs/M05_cost_model.txt` | ✅ |
| Raw snapshots (dated) | `snapshots/2026-09-21/{aws,azure,gcp}_{compute,egress,storage}.json`, `gcp_manual.csv` | ✅ |
| Unified cost model | `cost_model/2026-09-21/{compute,egress,internet,storage}.csv` | ✅ |
| Validation report (V1–V10 PASS) | `cost_model/2026-09-21/validation.md` | ✅ |
| Method notes | `cost_model/README.md`, `pricing/README.md` | ✅ |
| Waiver: GCP from public pages, no API key | `docs/design_decisions.md` D-026, `state/AUDIT_LOG.md` M04 | ✅ |

### Testbed and measured traffic (M07, commit `dc365ec`)

| Evidence | Path | Status |
|---|---|---|
| Screenshot: `kubectl get nodes` / `get pods` | `evidence/screenshots/M07_kubectl.png` | ✅ present (H-06 done 2026-09-22) |
| Screenshot: locust load-test summary | `evidence/screenshots/M07_load_test.png` | ✅ present (H-06 done 2026-09-22) |
| Console log: cluster, pods, seed job | `evidence/logs/M07_kubectl.txt` | ✅ |
| Console log: tool versions | `evidence/logs/M07_versions.txt` | ✅ |
| Console log: three 10-min measurement runs | `evidence/logs/M07_measurement.txt`, `logs/M07_measurement_r{1,2,3}.txt` | ✅ |
| Locust raw output | `logs/M07_locust/r{1,2,3}_{locust.txt,stats.csv,stats_history.csv,failures.csv}` | ✅ |
| Per-edge byte counts and summary | `testbed/measurements/{runs,runs_interface,summary,summary_interface}.csv` | ✅ |
| Testbed code and manifests | `testbed/app/`, `testbed/k8s/`, `testbed/load/locustfile.py`, `testbed/README.md` | ✅ |
| Measured volumes used in T1 | `topologies/t1_three_tier.json`, `topologies/README.md` | ✅ |

## R4 — Baseline reproduced with numbers · 2 marks · M08 (commit `d51adf8` for results, `e0460f7` close)

| Evidence | Path | Status |
|---|---|---|
| Screenshot: baseline run, T1–T3 tables | `evidence/screenshots/M08_baselines.png` | ✅ present (H-07 done 2026-09-22) |
| Console log: baseline run | `evidence/logs/M08_baselines.txt` | ✅ |
| Result rows (15 = 3 topologies × 5 methods) | `results/baselines/runs.csv` | ✅ |
| Run config (commit, snapshot, input hashes) | `results/baselines/config.json` | ✅ |
| Run log incl. B1 tie-break sensitivity | `results/baselines/run.log` | ✅ |
| Generated tables for the pack | `docs/review1/baseline_results.md` (by `analysis/review1_tables.py`) | ✅ |
| Cost function and baselines | `placement/cost.py`, `placement/baselines.py`, `placement/instance.py` | ✅ |
| Tests (hand-computed toy, directed egress) | `tests/test_placement_baselines.py`, `tests/test_review1_tables.py` | ✅ |
| Acceptance output | `logs/M08_acceptance_checks.txt` | ✅ |

---

## Missing screenshots (8 of 8)

| File to save in `evidence/screenshots/` | Human action |
|---|---|
| `M00_verify_env.png` | H-01 |
| `M02_azure_pull.png`, `M03_aws_pull.png`, `M04_gcp_pull.png`, `M05_cost_model.png` | H-04 |
| `M07_kubectl.png`, `M07_load_test.png` | H-06 |
| `M08_baselines.png` | H-07 |

## How to reproduce the numbers

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:P5_SNAPSHOT_DATE='2026-09-21'; .\.venv\Scripts\python.exe -m pricing.build_cost_model; .\.venv\Scripts\python.exe -m pricing.validate_cost_model
.\.venv\Scripts\python.exe -m experiments.run_baselines
.\.venv\Scripts\python.exe -m analysis.review1_tables --check
```
