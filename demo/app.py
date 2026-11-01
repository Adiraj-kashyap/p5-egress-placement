"""P5 walkthrough — a guided, live, offline demo of the whole project (M20 + M22).

Eleven chapters, read in order with the Next links at the foot of each page: the problem,
the price data, the workloads, the cost model, the solvers run live, the three hypothesis
verdicts with their statistics, the ablation, the live Kubernetes testbed, and the limits.
The M20 tabs live on as chapters 4 (Optimise), 7 (Crossover) and 9 (Live testbed).

    streamlit run demo/app.py

Nothing here reaches the network: prices come from the committed `cost_model/2026-09-21/`,
replicated results from `demo/cache/`, prose numbers from generated `docs/report/` files.
Costs are always `placement.cost.evaluate` (D-006) — the app never computes a cost itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `streamlit run demo/app.py` does not put the repo on sys.path
    sys.path.insert(0, str(ROOT))

from demo import core, explain  # noqa: E402

st.set_page_config(page_title="P5 — egress-aware placement", page_icon=":material/cloud:",
                   layout="wide")

pages = [st.Page(c.file, title=c.title, icon=c.icon, default=(i == 0),
                 url_path=None if i == 0 else c.slug)
         for i, c in enumerate(explain.CHAPTERS)]
current = st.navigation({"Walkthrough": pages})

st.sidebar.caption(f"Prices: committed snapshot {core.SNAPSHOT_DATE} · runs offline")
manifest = core.cache_manifest()
st.sidebar.caption("Results cache built " + manifest.get(
    "built_utc", "— (run `python -m demo.build_cache`)"))

current.run()
