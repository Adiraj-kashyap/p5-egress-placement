"""Chapter 4 — O3: every method solved live on the same instance (the M20 Optimise tab)."""

import pandas as pd
import streamlit as st

from demo import core, ui

FILE = "chapters/04_solvers.py"
ui.page_header(FILE)

ui.what("Two baselines that the assignment names, and three optimisers built in this "
        "project. All of them are run now, on this laptop, and every answer is scored by "
        "the same cost function from chapter 3.")

with st.expander("How each method works", expanded=True):
    st.markdown(
        "- **B1 — cheapest per vCPU (egress-blind).** Each component independently goes "
        "to the location with the lowest compute price per vCPU. Egress is ignored when "
        "choosing but charged when scoring: this is common practice.\n"
        "- **B2-best — single provider.** Everything on one provider's cheapest region; "
        "the best of the three providers is reported.\n"
        "- **ILP (exact).** The whole placement as one integer linear program solved by "
        "CBC. It returns a *proven* optimum.\n"
        "- **Greedy + 1-opt.** Places the components with the most traffic first, each at "
        "its cheapest location given the components already placed, then moves single "
        "components while that lowers the bill.\n"
        "- **Simulated annealing.** Starts from greedy and makes random moves, sometimes "
        "accepting uphill ones early on to escape local optima.")

c1, c2, c3 = st.columns([2, 1, 2])
workload = c1.selectbox("Workload", list(core.TOPOLOGIES) + ["Synthetic"])
location_set = c2.radio("Locations", ["core", "ext"], horizontal=True,
                        help="core = 12 locations (4 regions x 3 providers); ext = 24")
scale_exp = c3.slider("Traffic scale s (log10)", -2.0, 2.0, 0.0, 0.25,
                      help="Multiplies inter-component volumes only; internet egress is "
                           "unchanged, exactly as in the M15 sweep.")
traffic_scale = float(10.0 ** scale_exp)
syn_n = syn_seed = None
if workload == "Synthetic":
    s1, s2 = st.columns(2)
    syn_n = s1.slider("Components n", 4, 30, 12)
    syn_seed = s2.number_input("Generator seed", 1, 999, 1)
m1, m2 = st.columns([4, 1])
methods = m1.multiselect("Methods", list(core.METHODS), default=list(core.DEFAULT_METHODS),
                         format_func=lambda m: core.METHODS[m])
sa_seed = m2.number_input("SA seed", 0, 99, 0)
st.caption(f"s = {traffic_scale:g}x the stated traffic")

if st.button("Solve now", type="primary"):
    if not methods:
        st.warning("Select at least one method.")
    else:
        with st.spinner("Solving…"):
            if workload == "Synthetic":
                inst = core.synthetic_instance(int(syn_n), location_set, int(syn_seed),
                                               traffic_scale)
            else:
                inst = core.build_instance(core.TOPOLOGIES[workload], location_set,
                                           traffic_scale)
            st.session_state["outcome"] = core.run_methods(
                inst, methods, sa_seed=int(sa_seed), traffic_scale=traffic_scale)

outcome = st.session_state.get("outcome")
if outcome is None:
    st.info("Pick a workload and press **Solve now**.")
else:
    inst, results = outcome.instance, outcome.results
    st.caption(f"{inst.instance_id} · {inst.n_components} components · "
               f"{inst.n_locations} locations · {len(inst.edges)} directed edges · "
               f"s = {outcome.traffic_scale:g}")

    cols = st.columns(min(4, len(results)))
    for i, r in enumerate(results):
        pen = outcome.penalty_pct(r.method) or 0.0
        col = cols[i % len(cols)]
        col.metric(r.label, f"${r.total:,.2f}/mo",
                   f"{pen:+.2f}% vs best" if pen else "best", delta_color="inverse")
        col.caption(f"{r.runtime_s * 1000:,.0f} ms" + (f" · {r.note}" if r.note else ""))

    st.subheader("Where each method put each component")
    ui.provider_legend()
    rows = core.placement_rows(inst, results)
    header = "".join(f"<th style='text-align:left;padding:4px 10px'>{k}</th>" for k in rows[0])
    body = "".join(
        "<tr>" + "".join(
            f"<td style='padding:3px 10px'>"
            f"{ui.provider_badge(v) if isinstance(v, str) and ':' in v else v}</td>"
            for v in row.values()) + "</tr>"
        for row in rows)
    st.markdown(f"<div style='overflow-x:auto'><table><thead><tr>{header}</tr></thead>"
                f"<tbody>{body}</tbody></table></div>", unsafe_allow_html=True)

    st.subheader("What each bill is made of")
    crows = core.cost_rows(outcome)
    st.altair_chart(ui.stacked_cost(crows),
                    width="stretch")
    ui.data_table(pd.DataFrame([{k: (round(v, 3) if isinstance(v, float) else v)
                                 for k, v in r.items()} for r in crows]))
    st.caption("This is one live solve per method, for illustration. The replicated "
               "results with confidence intervals are in chapters 5–7.")

ui.how_to_read("Green delta = the cheapest answer in this run; red = how much more a method "
               "costs. Watch B1 split components across providers to save on compute, then "
               "pay for it in the red egress segment. Push the traffic slider to 100x and "
               "solve again to see that gap grow.")
ui.takeaway("The exact ILP proves the optimum on every real workload in the time shown "
            "under its result. The heuristics match it or come very close, and the "
            "egress-blind baseline is the one that pays for ignoring traffic.")
ui.sources([f"cost_model/{core.SNAPSHOT_DATE}/*.csv", *core.TOPOLOGIES.values(),
            "placement/{ilp,greedy,annealing,baselines,cost}.py"])
ui.nav(FILE)
