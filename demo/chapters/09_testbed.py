"""Chapter 9 — the live kind testbed: measure, then re-optimise T1 (the M20 Live testbed tab).
Every failure path falls back to the committed M07 measurement (`demo.testbed` never raises)."""

import pandas as pd
import streamlit as st

from demo import core, explain, testbed, ui
from topologies.build import T1_RATE

FILE = "chapters/09_testbed.py"
ui.page_header(FILE)

ui.what("T1's traffic volumes were not guessed. T1 is a real three-tier app (web → api → "
        "cache, db) running on a local Kubernetes cluster (kind). A load generator (locust) "
        "drives it while each component counts the bytes it sends. Here you can repeat that "
        "measurement live and re-optimise from the fresh numbers.")

c1, c2 = st.columns([2, 3])
with c1:
    st.markdown("**1. Is the cluster up?**")
    if st.button("Check cluster"):
        st.session_state["tb_status"] = testbed.cluster_status()
    status = st.session_state.get("tb_status")
    if status is not None:
        (st.success if status.ready else st.warning)(status.message)
        if status.pods:
            st.dataframe(status.pods, width="stretch", hide_index=True)
with c2:
    st.markdown("**2. Measure**")
    duration = st.slider("Load duration (s)", 30, 120, 60, 10)
    b1, b2 = st.columns(2)
    if b1.button("Measure live", type="primary"):
        with st.spinner(f"Running locust for {duration} s…"):
            st.session_state["tb_meas"] = testbed.measure_or_cached(duration_s=duration)
    if b2.button("Use cached measurement"):
        st.session_state["tb_meas"] = testbed.cached()

meas = st.session_state.get("tb_meas")
if meas is None:
    st.info("Press **Measure live**, or **Use cached measurement** if the cluster is not "
            "running. The cached one is the committed 3-run measurement behind T1.")
else:
    (st.success if meas.source == "live" else st.info)(meas.message)
    st.markdown("**3. Measured bytes per request**")
    st.dataframe(pd.DataFrame([{"from": s, "to": d, "bytes_per_request": round(v, 1)}
                               for (s, d), v in meas.bytes_per_request.items()]),
                 width="stretch", hide_index=True)

    with st.spinner("Re-optimising T1…"):
        fresh = core.t1_from_bytes(meas.bytes_per_request, T1_RATE, meas.internet_bytes)
        new_inst = core.build_instance(fresh, "core")
        old_inst = core.build_instance(core.TOPOLOGIES["T1 three-tier (measured)"], "core")
        new_out = core.run_methods(new_inst, ("ilp_tight", "b1"))
        old_out = core.run_methods(old_inst, ("ilp_tight", "b1"))

    st.markdown("**4. Committed T1 vs T1 rebuilt from this measurement**")
    left, right = st.columns(2)
    for col, title, out in ((left, "Committed (M07)", old_out),
                            (right, f"This measurement ({meas.source})", new_out)):
        with col:
            st.markdown(f"*{title}*")
            ilp = next(r for r in out.results if r.method == "ilp_tight")
            b1r = next(r for r in out.results if r.method == "b1")
            st.metric("ILP optimum", f"${ilp.total:,.2f}/mo")
            st.caption(f"B1 (egress-blind) USD {b1r.total:,.2f}/mo · "
                       f"penalty {100 * (b1r.total - ilp.total) / ilp.total:.2f}%")
            st.markdown(" ".join(ui.provider_badge(ilp.assignment[c]) + f" {c}"
                                 for c in out.instance.components), unsafe_allow_html=True)
    delta = new_out.best.total - old_out.best.total
    st.caption(f"Difference in the optimum: USD {delta:+,.2f}/month "
               f"({100 * delta / old_out.best.total:+.2f}%).")

ui.how_to_read(f"Bytes per request × {T1_RATE:g} requests/s × seconds per month gives each "
               "edge's GB/month, the same conversion that built the committed T1. A small "
               "difference between the two sides means the measurement is reproducible.")
cv = max(r["cv_pct"] for r in explain.measurement_rows())
ui.takeaway(f"The workload model is grounded in measurement: T1's volumes come from real "
            f"traffic, with run-to-run variation of at most {cv:.2f}% in the committed runs, "
            "and the optimiser can be re-run from a fresh measurement in seconds.")
ui.sources([explain.MEASUREMENT, "testbed/README.md", "testbed/k8s/", "demo/testbed.py",
            "topologies/build.py"])
ui.nav(FILE)
