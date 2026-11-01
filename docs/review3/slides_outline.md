# Review-3 slides — outline (M23 step 3)

The deck is built: **`docs/review3/P5_Review3_Evaluation_and_Documentation.pptx`** (19 slides,
16:9, editable, speaker notes on every slide). Generator: `docs/review3/deck/build_review3.js`
(pptxgenjs; figures are the committed `figures/*.png`). Talk length is about 13 minutes plus the
5-minute demo. Every number is copied from a generated file named on its slide.

| # | Title (the takeaway) | Rubric | Show / source |
|---|---|---|---|
| 1 | Where should each component live when every gigabyte has a price? | – | title, team, guide |
| 2 | Three reviews, one question | recap | `docs/review1/problem_statement.md`, `hypotheses.md` |
| 3 | What Review 3 asks for, and where we answer it | agenda | `agent/04_REVIEWS_2_3.md §2` |
| 4 | Every objective has code, results, a figure and a paper section | Objectives 3m | `docs/review3/objective_evidence.md` |
| 5 | Four workloads, one of them measured on a real cluster | Objectives 3m | `topologies/`, `testbed/measurements/summary.csv` |
| 6 | Every configuration ran at least 3 times; most ran 30 | Objectives 3m | `python -m experiments.check_replication` |
| 7 | Every figure states its n and carries a 95 % interval | Statistics 2m | `docs/review3/statistical_soundness.md` |
| 8 | The cost of ignoring egress grows with traffic | Statistics 2m | `figures/R2-1_cost_vs_scale.png` |
| 9 | H1: only the data pipeline clears the 20 % bar | Statistics 2m | `docs/report/verdicts.md` (drawn as a CI plot) |
| 10 | H2: annealing is accurate, but not faster than the exact solver | Statistics 2m | `figures/F4_runtime_vs_n.png` |
| 11 | H3: no crossover, one region is cheapest for everything | Statistics 2m | `figures/F7_sensitivity.png`, verdicts H3 |
| 12 | The egress-coupling term does the work, not the heuristic | Statistics 2m | `figures/F6_gain_decomposition.png` |
| 13 | The scoreboard: one partial win, three refutations | Statistics 2m | `docs/report/verdicts.md` |
| 14 | Five minutes, live: solve, stress, measure, re-optimise | Demo 2m | `docs/review3/demo_runbook.md` |
| 15 | **Live demo** — the runbook takes over | Demo 2m | `.\run_demo.ps1` → http://localhost:8501 |
| 16 | Paper and walkthrough share the same generated numbers | Docs 3m | `paper/`, `docs/review3/walkthrough.md` |
| 17 | What our results do not say | Docs 3m | `docs/review2/threats_to_validity.md` |
| 18 | Check one ratio before you optimise placement | close | – |
| 19 | Thank you. Questions welcome | – | prepared answers in the notes |

Before the review, update slide 16's status line once `paper/main.pdf` exists (H-17) and state
its page count.
