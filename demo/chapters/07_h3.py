"""Chapter 7 — H3: the traffic sweep and the (absent) crossover (R2-1, F2, F3; the M20
Crossover tab). Wording follows D-085: there is no crossover, and the page says so."""

import altair as alt
import pandas as pd
import streamlit as st

from demo import core, explain, ui

FILE = "chapters/07_h3.py"
ui.page_header(FILE)

ui.what("The headline hypothesis: as traffic between components grows, egress should "
        "eventually dominate and push the optimum onto a <b>single provider</b>, while "
        "the egress-blind B1 stays split. Traffic was scaled from 0.01x to 100x of the "
        "stated volumes, on 30 traffic draws per point.")
ui.verdict_banner("H3")

topo = st.radio("Topology", list(ui.TOPO_LABEL), horizontal=True,
                format_func=ui.TOPO_LABEL.get, key="h3_topo")
label = next(k for k in core.TOPOLOGIES if k.startswith(ui.TOPO_LABEL[topo].split()[0]))

# ---- live point
st.subheader("Solve it yourself at any traffic level")
s_exp = st.slider("Traffic scale s (log10)", -2.0, 2.0, 2.0, 0.25, key="h3_s")
s = float(10 ** s_exp)


with st.spinner("Solving ILP and B1…"):  # live, never cached (§S13)
    out = core.run_methods(core.build_instance(core.TOPOLOGIES[label], "core", s),
                           ("ilp_tight", "b1"), traffic_scale=s)
ilp = next(r for r in out.results if r.method == "ilp_tight")
b1 = next(r for r in out.results if r.method == "b1")
c1, c2, c3 = st.columns(3)
c1.metric(f"ILP optimum at s = {s:g}", f"${ilp.total:,.2f}/mo")
c1.caption(f"uses {ilp.cost.providers_used} provider(s)")
c2.metric("B1 (egress-blind)", f"${b1.total:,.2f}/mo")
c2.caption(f"uses {b1.cost.providers_used} provider(s)")
c3.metric("B1 penalty", f"{100 * (b1.total - ilp.total) / ilp.total:,.2f}%")
st.markdown("ILP places: " + " ".join(f"{ui.provider_badge(ilp.assignment[c])} {c}"
                                      for c in out.instance.components),
            unsafe_allow_html=True)

# ---- R2-1
st.subheader("Cost vs traffic scale, all methods")
r21 = ui.cache_df("R2-1_cost_vs_scale.csv")
sel = r21[r21["topology_id"] == topo]
pt = alt.Chart(pd.DataFrame({"traffic_scale": [s], "mean": [ilp.total],
                             "what": [f"your live ILP solve, s = {s:g}"]})).mark_point(
    shape="diamond", size=220, filled=True, color="#0b0b0b").encode(
    x="traffic_scale:Q", y="mean:Q", tooltip=["what:N", alt.Tooltip("mean:Q", format="$,.2f")])
st.altair_chart(ui.band_lines(sel, "traffic_scale", "mean", "method", ui.METHOD_COLOURS,
                              ui.METHOD_LABELS, "traffic scale s (log)",
                              "USD per month (log)", log_x=True, log_y=True, height=360,
                              extra=pt), width="stretch")
st.caption(f"Mean over n = {int(sel['n'].min())} draws per point; band = 95% bootstrap CI. "
           "Black diamond = the live solve above. Where B2-best, greedy and annealing "
           "equal the optimum, their lines lie under the blue ILP line.")
ui.data_table(sel)

left, right = st.columns(2)
with left:
    st.subheader("Penalty of the baselines")
    f2 = ui.cache_df("F2_egress_penalty.csv")
    f2s = f2[(f2["topology_id"] == topo) & (f2["location_set"] == "core")]
    st.altair_chart(ui.band_lines(f2s, "traffic_scale", "mean", "method", ui.METHOD_COLOURS,
                                  ui.METHOD_LABELS, "traffic scale s (log)",
                                  "% above the ILP optimum", log_x=True),
                    width="stretch")
with right:
    st.subheader("Providers used")
    f3 = ui.cache_df("F3_providers_used.csv")
    f3s = f3[(f3["topology_id"] == topo) & (f3["panel"] == "providers_used")]
    st.altair_chart(ui.band_lines(f3s, "traffic_scale", "mean", "method", ui.METHOD_COLOURS,
                                  ui.METHOD_LABELS, "traffic scale s (log)",
                                  "distinct providers in the placement", log_x=True),
                    width="stretch")
ui.how_to_read("A crossover would show as the blue ILP line in <i>Providers used</i> "
               "stepping from 2+ down to 1 at some s. It never steps: it is flat at one "
               "provider across the whole range, so there is no threshold to find. "
               "Meanwhile B1's penalty grows with traffic, because it keeps splitting.")

st.subheader("Why there is no crossover")
for b in explain.verdict_bullets("H3"):
    st.markdown(f"- {b}")
sec = explain.verdicts()["H3"]["section"]
why = next((p for p in sec.split("\n\n") if p.startswith("Why this is structural")), "")
st.info(why)

ui.takeaway("H3 is refuted, and structurally rather than by chance. In this price "
            "snapshot one location is cheapest for every component on its own, so the "
            "optimum never needs a second provider at any traffic level. The practical "
            "lesson survives: the egress-blind baseline's penalty grows without bound as "
            "traffic grows (move the slider to 100x above).")
ui.sources(["figures/R2-1_cost_vs_scale.csv", "figures/F2_egress_penalty.csv",
            "figures/F3_providers_used.csv", "results/sweep/crossover.csv",
            explain.VERDICTS, "docs/design_decisions.md (D-085)"])
ui.nav(FILE)
