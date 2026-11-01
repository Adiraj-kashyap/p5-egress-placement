"""Chapter 6 — H2: heuristic optimality gap and speed (F5, F4, F0, T-H2)."""

import altair as alt
import pandas as pd
import streamlit as st

from analysis.thresholds import H2_MAX_GAP, H2_MIN_SPEEDUP
from demo import explain, ui

FILE = "chapters/06_h2.py"
ui.page_header(FILE)

ui.what("Exact solvers can become slow as problems grow, which is the usual case for "
        "heuristics. Here the heuristics were run on synthetic applications of 4–40 "
        "components and compared with the proven optimum, on two clauses: "
        "<b>accuracy</b> (gap) and <b>speed</b>.")
ui.verdict_banner("H2")

loc = st.radio("Location set", ["core", "ext"], horizontal=True, key="h2_loc",
               format_func=lambda s: {"core": "core (12 locations)",
                                      "ext": "ext (24 locations)"}[s])

st.subheader("Accuracy: how far above the optimum each heuristic lands")
f5 = ui.cache_df("F5_gap_boxplots.csv")
gap = f5[f5["location_set"] == loc]
st.altair_chart(ui.band_lines(gap, "n_components", "mean", "method", ui.METHOD_COLOURS,
                              ui.METHOD_LABELS, "components n",
                              "gap vs proven optimum, % (mean, 95% CI)",
                              extra=alt.Chart(pd.DataFrame({"y": [100 * H2_MAX_GAP]}))
                              .mark_rule(color="#b42318", strokeDash=[6, 4]).encode(y="y:Q")),
                width="stretch")
st.caption(f"Mean over n instances per point (n shown on hover); band = 95% CI. "
           f"Red dashed line = the H2 limit of {100 * H2_MAX_GAP:g}%.")
ui.data_table(gap)

st.subheader("Speed: wall-clock time per solve")
f4 = ui.cache_df("F4_runtime_vs_n.csv")
rt = f4[f4["location_set"] == loc]
st.altair_chart(ui.band_lines(rt, "n_components", "mean", "method", ui.METHOD_COLOURS,
                              ui.METHOD_LABELS, "components n",
                              "seconds per solve (mean, 95% CI, log scale)", log_y=True),
                width="stretch")
st.caption("Mean over instances × timing repeats (n on hover), same machine, one thread.")
ui.data_table(rt)
ui.how_to_read(f"For H2 the annealing line (pink) must stay under the red limit in the "
               f"top chart <b>and</b> sit at least {H2_MIN_SPEEDUP}x below the ILP line "
               "(blue) in this one. The first clause holds easily. The second does not: "
               "CBC solves these instances so fast that annealing is not faster at all.")

st.subheader("Inside one annealing run")
f0 = ui.cache_df("F0_sa_convergence.csv")
conv = f0[f0["series"].isin(["best_usd", "current_usd"])].copy()
conv["series_key"] = conv["series"]
opt = float(f0["ilp_optimum_usd"].iloc[0])
colours = {"best_usd": "#2a78d6", "current_usd": "#e87ba4"}
labels = {"best_usd": "best found so far", "current_usd": "current state"}
st.altair_chart(ui.band_lines(conv, "temp_step", "mean", "series_key", colours, labels,
                              "temperature step", "USD per month (mean over seeds, 95% CI)",
                              extra=alt.Chart(pd.DataFrame({"y": [opt]})).mark_rule(
                                  color="#0b0b0b", strokeDash=[4, 4]).encode(y="y:Q")),
                width="stretch")
st.caption(f"T3, mean over SA seeds (n per step on hover; steps with fewer than 3 seeds "
           f"still running are dropped). Dashed line = proven ILP optimum USD {opt:,.2f}/month.")

st.subheader("The verdict, clause by clause")
for b in explain.verdict_bullets("H2"):
    st.markdown(f"- {b}")
h2 = explain.md_table(explain.md_section(explain.H1_TABLE, "T-H2"))
st.dataframe(pd.DataFrame(h2), width="stretch", hide_index=True)

ui.takeaway("Simulated annealing is accurate: it finds the optimum or lands within a "
            "fraction of a percent. But at the sizes real applications have, the exact "
            "solver is already fast and <i>proves</i> its answer, so the heuristic buys "
            "nothing here. H2 is refuted on its speed clause, measured rather than assumed.")
ui.sources(["figures/F5_gap_boxplots.csv", "figures/F4_runtime_vs_n.csv",
            "figures/F0_sa_convergence.csv", explain.H1_TABLE, "results/scaling/runs.csv",
            "results/timing/summary.csv", explain.VERDICTS])
ui.nav(FILE)
