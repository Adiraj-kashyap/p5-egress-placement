# Repository and continuous integration

## GitHub

**Repository URL:** `<URL HERE>`

(Filled in by Adi when H-15 is done. The same URL replaces `OWNER/REPO` in the CI badge at the top
of `README.md`.)

Everything the panel needs is in this one repository: pricing pulls, cost model, testbed,
solvers, experiment harness, all `results/`, all figures and tables, the state files that record
how it was built, and this review pack.

## CI

`.github/workflows/tests.yml` — on every push and pull request:

| Step | What it does |
|---|---|
| `actions/checkout@v4` | checks the repo out |
| `actions/setup-python@v5` | Python 3.11 with pip caching |
| `pip install -r requirements.lock.txt` | the pinned dependency set (D-083) |
| `python -c "import pulp; print(...)"` | prints the CBC solver the run will use |
| `pytest -q -m "not live and not testbed"` | the CI subset of the suite |

The marker expression is the one from `06_SKILLS_V2.md §S15`. **No test is currently excluded by
it:** nothing in `tests/` needs network, Docker or a cluster (D-082), so CI runs all **407** tests.
The markers are registered in `pytest.ini` so a future live test can be excluded without touching
the workflow.

Local proof of the same command, at the M19 commit:

```
$ .\.venv\Scripts\python.exe -m pytest -q -m "not live and not testbed"
407 passed in 119.95s (0:01:59)
```

(full output: `logs/M19_pytest_ci_subset.txt`)

CI also re-runs the analysis tests, which compare every committed figure CSV, table, `.tex` file,
`verdicts.md` and `results.md` against what the generators produce — so a green run is evidence
that the reported numbers still follow from the committed data, not just that the code imports.

**Green-run screenshot:** `evidence/screenshots/M19_ci_green.png` (H-15).

## Reproducing the results from a clean clone

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m analysis.figures
.venv\Scripts\python.exe -m analysis.tables --latex
.venv\Scripts\python.exe -m analysis.verdicts
.venv\Scripts\python.exe -m analysis.results_text
.venv\Scripts\python.exe -m analysis.check_numbers docs/report/results.md docs/report/verdicts.md
```

The five generators must be run in that order — each reads the one before. Re-running the
experiments themselves (8,100 + 4,320 + 1,800 + 1,250 + 1,500 + 162 jobs) takes hours; the runs
are committed under `results/`, each row carrying its git commit, snapshot date and machine tag.
