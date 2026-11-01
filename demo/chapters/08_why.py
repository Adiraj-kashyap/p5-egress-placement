"""Chapter 8 — which ingredient causes the gain (F6 ablation) and how prices move it (F7)."""

import altair as alt
import streamlit as st

from demo import explain, ui

FILE = "chapters/08_why.py"
ui.page_header(FILE)

ui.what("An <b>ablation</b> adds the model's ingredients one at a time, from B1 to the full "
        "optimiser, and measures how much of the saving each step buys. Every step was run "
        "on the same 30 traffic draws, so the steps add up exactly to the total gain.")

f6 = ui.cache_df("F6_gain_decomposition.csv")
c1, c2 = st.columns(2)
topo = c1.radio("Topology", list(ui.TOPO_LABEL), horizontal=True,
                format_func=ui.TOPO_LABEL.get, key="why_topo")
scales = sorted(f6["traffic_scale"].unique())
scale = c2.radio("Traffic scale s", scales, horizontal=True, format_func=lambda v: f"{v:g}x",
                 key="why_s")
d = f6[(f6["topology_id"] == topo) & (f6["traffic_scale"] == scale)].sort_values("step").copy()
d["step_label"] = d.apply(lambda r: f"{int(r['step'])}. {r['buys']}", axis=1)
d["sign"] = d["mean"].map(lambda v: "saves money" if v > 0 else
                          ("no effect" if v == 0 else "costs money"))

st.subheader("Saving bought by each ingredient (USD per month)")
base = alt.Chart(d).encode(y=alt.Y("step_label:N", sort=None, title=None,
                                   axis=alt.Axis(labelLimit=320)))
chart = alt.layer(
    base.mark_bar(cornerRadius=4, size=28).encode(
        x=alt.X("mean:Q", title="USD per month saved (mean, 95% CI)"),
        color=alt.Color("sign:N", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=["saves money", "no effect", "costs money"],
                                        range=["#2a78d6", "#a8a7a1", "#eb6834"])),
        tooltip=["step_label", alt.Tooltip("mean:Q", format="$,.2f"),
                 alt.Tooltip("ci_lo:Q", format="$,.2f", title="CI low"),
                 alt.Tooltip("ci_hi:Q", format="$,.2f", title="CI high"), "n",
                 alt.Tooltip("share_of_gain_pct_mean:Q", format=".1f",
                             title="share of total gain %")]),
    base.mark_errorbar(ticks=True, color="#0b0b0b").encode(
        x=alt.X("ci_lo:Q", title="USD per month saved (mean, 95% CI)"), x2="ci_hi:Q"),
    alt.Chart(d.head(1)).mark_rule(color="#52514e").encode(x=alt.datum(0)),
).properties(height=200)
st.altair_chart(chart, width="stretch")
total = float(d["total_gain_usd_mean"].iloc[0])
st.caption(f"n = {int(d['n'].min())} draws; whiskers = 95% bootstrap CI. Total gain "
           f"B1 → full optimiser: USD {total:,.2f}/month (mean).")
ui.data_table(d[["step", "from_method", "to_method", "buys", "n", "mean", "ci_lo", "ci_hi",
                 "share_of_gain_pct_mean"]])

st.subheader("The answer, in five lines")
st.markdown(explain.md_section(explain.ABLATION, "The five-line answer"))

st.subheader("How the saving moves with prices")
f7 = ui.cache_df("F7_sensitivity.csv")
f7s = f7[f7["topology_id"] == topo]
heat = alt.Chart(f7s).mark_rect(stroke="#fcfcfb", strokeWidth=2).encode(
    x=alt.X("egress_mult:O", title="cross-provider egress price × multiplier"),
    y=alt.Y("locs_per_provider:O", title="regions per provider", sort="descending"),
    color=alt.Color("mean:Q", title="saving vs B1, %", scale=alt.Scale(scheme="blues")),
    tooltip=[alt.Tooltip("egress_mult:O", title="egress ×"),
             alt.Tooltip("locs_per_provider:O", title="regions / provider"),
             alt.Tooltip("mean:Q", format=".2f", title="mean saving %"),
             alt.Tooltip("ci_lo:Q", format=".2f", title="CI low"),
             alt.Tooltip("ci_hi:Q", format=".2f", title="CI high"), "n"],
)
labels = heat.mark_text(fontSize=11).encode(
    text=alt.Text("mean:Q", format=".1f"),
    color=alt.condition(alt.datum.mean > f7s["mean"].max() * 0.6, alt.value("#ffffff"),
                        alt.value("#0b0b0b")))
st.altair_chart((heat + labels).properties(height=240), width="stretch")
st.caption(f"Each cell: mean ILP saving over B1 across n = {int(f7s['n'].min())} draws "
           "(CI on hover).")
ui.data_table(f7s)

ui.takeaway("The gain comes from one thing: pricing the edges as <b>coupled</b> decisions. "
            "Better price tables alone do not help, and can even hurt. Where the saving is "
            "small, it is because cross-provider splitting rarely pays at today's prices. "
            "On T1 and T2 the saving grows steadily as egress gets pricier. On T3 it does "
            "not move at all: its small saving does not come from cross-provider traffic.")
ui.sources(["figures/F6_gain_decomposition.csv", "figures/F7_sensitivity.csv",
            explain.ABLATION, "results/ablation/", "results/sensitivity/"])
ui.nav(FILE)
