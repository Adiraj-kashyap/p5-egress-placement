"""Chapter 0 — the question, objectives, hypotheses with verdicts, and the chapter map."""

import streamlit as st

from demo import core, explain, ui

FILE = "chapters/00_start.py"
ui.page_header(FILE)

st.markdown("### Where should each part of a cloud application run, when moving data "
            "*between* clouds costs money?")

counts = explain.price_row_counts()
runs = explain.run_counts()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Cloud providers", len(core.PROVIDER_COLOURS))
c2.metric("Priced locations", counts["compute"] // 4,
          help="compute.csv holds 4 shapes per location (validation V1)")
c3.metric("Published prices used", f"{sum(counts.values()):,}",
          help=", ".join(f"{k} {v}" for k, v in counts.items()))
c4.metric("Experiment runs", f"{sum(runs.values()):,}",
          help="; ".join(f"{explain.RUN_FILES[k]}: {v:,}" for k, v in runs.items()))

ui.what("A guided tour of project P5. Each chapter shows one part of the work, lets you "
        "interact with it, and ends with the takeaway. Read in order using the "
        "<b>Next</b> link at the bottom of each page, or jump around in the sidebar. "
        "The optimisers run live in chapters 3, 4 and 7, and chapter 9 measures a real "
        "Kubernetes testbed.")

st.subheader("The problem")
st.markdown(explain.problem_statement())

left, right = st.columns([1, 1])
with left:
    st.subheader("Four objectives")
    for o in explain.objectives():
        st.markdown(f"**{o['ID']}** — {o['Objective']}")
with right:
    st.subheader("Three hypotheses, fixed before any result")
    v = explain.verdicts()
    for h, stmt in explain.hypotheses().items():
        per = " ".join(ui.verdict_chip(x, f"{t} ") for t, x in v[h]["per_topology"].items())
        st.markdown(f"**{h}** {ui.verdict_chip(v[h]['verdict'])} {per}",
                    unsafe_allow_html=True)
        st.caption(stmt)

ui.how_to_read("A verdict is computed by a fixed rule on 95% confidence intervals over "
               "replicated runs, not on a single number. <b>Refuted</b> is a real finding "
               "here, not a failure: chapters 5–8 show exactly why each verdict came out "
               "as it did.")

st.subheader("Chapter map")
for ch in explain.CHAPTERS[1:]:
    a, b = st.columns([1.3, 3])
    a.page_link(ch.file, label=ch.title, icon=ch.icon)
    b.caption(ch.blurb)

ui.takeaway("Splitting an application across providers can save on compute, but every GB "
            "that then crosses a provider boundary is billed. This project prices that "
            "trade-off exactly and tests three claims about it.")
ui.sources([explain.BRIEF, explain.VERDICTS, f"cost_model/{core.SNAPSHOT_DATE}/*.csv",
            *explain.RUN_FILES])
ui.nav(FILE)
