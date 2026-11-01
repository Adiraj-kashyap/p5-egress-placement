"""Chapter 2 — the three applications being placed (T1 measured, T2/T3 stated)."""

import pandas as pd
import streamlit as st

from demo import core, explain, ui

FILE = "chapters/02_workloads.py"
ui.page_header(FILE)

ui.what("An application is a set of components (each needing a fixed number of vCPUs, RAM "
        "and storage) plus the data each component sends to the others every month. The "
        "optimiser decides only <b>where</b> each component runs; its machine size is fixed "
        "in advance as the smallest shape that fits (D-004).")

label = st.radio("Workload", list(core.TOPOLOGIES), horizontal=True)
topo = explain.topology(label)
s = explain.topology_summary(topo)

st.markdown(f"**{topo['description']}**  \nVolumes are *{topo['provenance']}*"
            + (" on the Kubernetes testbed (chapter 9)." if topo["provenance"] == "measured"
               else " from the workload's documented assumptions."))
c1, c2, c3, c4 = st.columns(4)
c1.metric("Components", s["components"])
c2.metric("Directed edges", s["edges"])
c3.metric("Between components", f"{s['edge_gb_month']:,.0f} GB/mo")
c4.metric("To end users", f"{s['internet_gb_month']:,.0f} GB/mo")

st.graphviz_chart(explain.topology_dot(topo), width="stretch")
ui.how_to_read("Boxes are components (vCPU / RAM, and stored data if any). Arrows carry the "
               "GB sent per month in that direction; the sender pays. The dashed arrows go "
               "to end users and are billed at the sender's internet rate wherever it runs.")

left, right = st.columns(2)
with left:
    st.markdown("**Components**")
    st.dataframe(pd.DataFrame([{k: c.get(k) for k in ("id", "vcpu", "ram_gb", "storage_gb",
                                                       "rationale")}
                               for c in topo["components"]]),
                 width="stretch", hide_index=True)
with right:
    st.markdown("**Edges**")
    st.dataframe(pd.DataFrame([{"from": e["src"], "to": e["dst"],
                                "GB/month": e["gb_per_month"], "why": e["rationale"]}
                               for e in topo["edges"]]),
                 width="stretch", hide_index=True)

if topo["provenance"] == "measured":
    st.subheader("Where T1's numbers come from")
    meas = pd.DataFrame(explain.measurement_rows())
    st.dataframe(meas, width="stretch", hide_index=True,
                 column_config={"cv_pct": st.column_config.NumberColumn(
                     "CV %", format="%.3f", help="coefficient of variation over the runs")})
    rate = topo["assumptions"]["requests_per_s"]
    st.caption(f"Bytes per request measured over {int(meas['runs'].max())} load runs; "
               f"volumes = bytes × {rate:g} req/s × 2,592,000 s/month. "
               f"Largest run-to-run CV: {meas['cv_pct'].max():.2f}%.")

ui.takeaway(f"{label.split(' (')[0]} moves {s['edge_gb_month']:,.0f} GB/month between its "
            f"{s['components']} components. Whether that traffic stays free or becomes a "
            "bill depends entirely on where the components are placed relative to each other.")
ui.sources([core.TOPOLOGIES[label], "topologies/README.md", explain.MEASUREMENT])
ui.nav(FILE)
