# Review-3 evidence index (M23 step 5)

Every path below exists in the repository unless marked **missing**.

| Rubric component | Marks | Evidence |
|---|---|---|
| All objectives evidenced (multiple workloads, ≥ 3 runs, mean and variance) | 3 | `docs/review3/objective_evidence.md`; `docs/review3/statistical_soundness.md`; `experiments/check_replication.py` (PASS, min n 30/30/10/5/3) |
| Statistical soundness (CIs / error bars) | 2 | `analysis/stats.py`; `figures/*.csv` (mean, sd, ci_lo, ci_hi, n); `figures/R2-1_cost_vs_scale.png`, `F1`–`F7`; `docs/report/verdicts.md` |
| Live demonstration | 2 | `demo/app.py`, `demo/preflight.py`, `run_demo.ps1`, `docs/review3/demo_runbook.md`, `docs/review3/walkthrough.md`; rehearsal `docs/review3/demo_rehearsal.md` — **missing (H-16)** |
| Documentation (6–8 page paper + demo) | 3 | `paper/main.tex`, `paper/numbers.tex`, `paper/refs.bib`, `paper/figures/`; `paper/main.pdf` — **missing (H-17)**; walkthrough in place of the video (MIG-003, D-087) |
| Presentation | – | `docs/review3/P5_Review3_Evaluation_and_Documentation.pptx`, `docs/review3/slides_outline.md` |

## Review 3 readiness

Not yet: the deck and pack are complete, but A3 needs `paper/main.pdf` (H-17) and
`docs/review3/demo_rehearsal.md` (H-16). The `review3` tag waits on both.
