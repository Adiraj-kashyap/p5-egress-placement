"""Chapter 5 — H1: the egress penalty of the egress-blind baseline, replicated (F1, T-H1)."""

import re

import altair as alt
import pandas as pd
import streamlit as st

from analysis.thresholds import H1_MIN_REDUCTION
from demo import explain, ui

FILE = "chapters/05_h1.py"
ui.page_header(FILE)

ui.what("The real traffic of an application is uncertain, so every workload was re-solved "
        "on <b>30 random traffic draws</b> around its stated volumes. Each bar and interval "
        "below summarises those 30 paired runs: the same draw is priced under every method.")
ui.verdict_banner("H1")

# ---- reduction vs the threshold
rows = explain.md_table(explain.md_section(explain.H1_TABLE, "T-H1"))
red = []
for r in rows:
    lo, hi = (float(x) for x in re.findall(r"-?[\d.]+", r["95% CI %"])[:2])
    mean = float(r["reduction % (mean +/- sd)"].split("+/-")[0])
    red.append({"topology": r["topology"], "baseline": r["baseline"], "mean": mean,
                "ci_lo": lo, "ci_hi": hi, "n": int(r["draws"]), "wilcoxon_p": r["Wilcoxon p"]})
red = pd.DataFrame(red)
rep = red[red["baseline"].str.startswith("B1 (reported")]

st.subheader("Cost reduction of the exact optimum over B1")
thr = 100 * H1_MIN_REDUCTION
base = alt.Chart(rep).encode(y=alt.Y("topology:N", title=None))
chart = alt.layer(
    base.mark_rule(strokeWidth=3, color="#2a78d6").encode(
        x=alt.X("ci_lo:Q", title="reduction of monthly cost vs B1, % (95% CI)",
                scale=alt.Scale(domain=[0, max(thr, rep["ci_hi"].max()) * 1.15])),
        x2="ci_hi:Q"),
    base.mark_point(filled=True, size=120, color="#2a78d6").encode(
        x="mean:Q",
        tooltip=["topology", alt.Tooltip("mean:Q", format=".2f", title="mean %"),
                 alt.Tooltip("ci_lo:Q", format=".2f", title="CI low %"),
                 alt.Tooltip("ci_hi:Q", format=".2f", title="CI high %"),
                 "n", alt.Tooltip("wilcoxon_p:N", title="Wilcoxon p (rho > 20%)")]),
    alt.Chart(pd.DataFrame({"x": [thr]})).mark_rule(color="#b42318", strokeDash=[6, 4],
                                                     strokeWidth=2).encode(x="x:Q"),
    alt.Chart(pd.DataFrame({"x": [thr], "t": [f"H1 threshold {thr:g}%"]})).mark_text(
        align="left", dx=6, dy=-8, color="#b42318", fontWeight="bold").encode(
        x="x:Q", text="t:N", y=alt.value(0)),
).properties(height=180)
st.altair_chart(chart, width="stretch")
st.caption(f"Dot = mean over n = {int(rep['n'].min())} draws; line = 95% bootstrap CI. "
           "H1 needs the whole interval at or right of the red line.")
ui.how_to_read("The verdict rule is fixed: a topology supports H1 only if its whole "
               "interval clears the threshold, and H1 as a whole needs all three. T2's "
               "interval clears it; T1's and T3's sit far below it.")

# ---- totals with CI per method
st.subheader("Monthly cost by method, s = 1")
f1 = ui.cache_df("F1_cost_breakdown.csv")
topo = st.radio("Topology", list(ui.TOPO_LABEL), horizontal=True,
                format_func=ui.TOPO_LABEL.get, key="h1_topo")
tot = f1[(f1["topology_id"] == topo) & (f1["component"] == "total_usd")].copy()
tot = tot[tot["method"].isin(ui.METHOD_COLOURS)]
order = [m for m in ui.METHOD_COLOURS if m in set(tot["method"])]
tot["label"] = tot["method"].map(ui.METHOD_LABELS)
tot = tot.set_index("method").loc[order].reset_index()
st.altair_chart(ui.dots_with_ci(tot, "mean", "method", ui.METHOD_COLOURS, ui.METHOD_LABELS,
                                "USD per month (mean, 95% CI; axis does not start at 0)"),
                width="stretch")
st.caption(f"Dot = mean over n = {int(tot['n'].min())} traffic draws per method; line = 95% CI. "
           "Methods that reach the optimum sit on the same value as the ILP.")
parts = f1[(f1["topology_id"] == topo) & (f1["component"] != "total_usd")]
ui.data_table(parts.pivot_table(index="method", columns="component", values="mean")
              .round(2).reset_index(), "Show the breakdown by cost term (means)")

st.subheader("The full table and the verdict text")
st.markdown(explain.md_section(explain.H1_TABLE, "T-H1").split("\n\n", 1)[-1]
            .split("## T-H2")[0])
for b in explain.verdict_bullets("H1"):
    st.markdown(f"- {b}")

t2 = rep[rep["topology"] == "T2"].iloc[0]
ui.takeaway(f"Ignoring egress costs real money only when a workload moves a lot of data "
            f"between parts that B1 splits across providers. That is T2, at "
            f"{t2['mean']:.2f}% (CI {t2['ci_lo']:.2f}–{t2['ci_hi']:.2f}%). For the other "
            "two the penalty is a few percent, so H1 is refuted overall. The robustness "
            "row (B1-alt) shows the result does not hinge on how B1 breaks price ties in "
            "the method's favour.")
ui.sources([explain.H1_TABLE, "figures/F1_cost_breakdown.csv", "results/replicates/runs.csv",
            explain.VERDICTS, "analysis/thresholds.py"])
ui.nav(FILE)
