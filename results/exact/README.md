# results/exact — exact ILP on T1–T3 (M10)

Produced by `python -m experiments.run_exact --tee evidence/logs/M10_exact.txt`. The run takes
under 10 s, uses one CBC thread, and reads cost model 2026-09-21 on the `core` location set.

- `runs.csv` is **append-only**. It has one row per (topology, formulation, repeat), and `run_utc`
  groups the rows of one invocation. `total_usd` and the cost terms come from
  `placement.cost.evaluate`. `cbc_objective`, `best_bound`, `gap` and `proven_optimal` come
  from CBC and its log. The script exits non-zero if `cbc_objective` and `total_usd` differ.
- `cbc/` holds every CBC log, named `<run stamp>_<topology>_<set>_<formulation>_r<repeat>.log`
  (the `cbc_log` column).
- `config.json` records the most recent invocation: git commit, snapshot, repeats, time limit
  and machine tag.
- `run.log` is the timestamped log of the most recent invocation, including one line per solve.

Repeats exist only to compare runtimes (acceptance check A4). The objectives are
deterministic. Compare runtimes using the median over repeats, and only between rows with the
same `machine_tag` (integrity rule I9). The formulation is described in
`docs/report/formulation.md`.
