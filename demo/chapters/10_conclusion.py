"""Chapter 10 — what was shown, what was not, and the threats to validity."""

import pandas as pd
import streamlit as st

from demo import explain, ui

FILE = "chapters/10_conclusion.py"
ui.page_header(FILE)

ui.what("The project's claims side by side with their verdicts, followed by the known "
        "ways the evidence could mislead. These are written down so a reader can judge "
        "the results without taking them on trust.")

st.subheader("Objectives: delivered")
obj = explain.objectives()
where = {"O1": "chapters 1, 3", "O2": "chapters 3, 4", "O3": "chapters 4, 6",
         "O4": "chapters 5, 7, 8"}
st.dataframe(pd.DataFrame([{"objective": o["ID"], "what": o["Objective"],
                            "see": where.get(o["ID"], "")} for o in obj]),
             width="stretch", hide_index=True)

st.subheader("Hypotheses: verdicts")
v = explain.verdicts()
for h, stmt in explain.hypotheses().items():
    per = " ".join(ui.verdict_chip(x, f"{t} ") for t, x in v[h]["per_topology"].items())
    st.markdown(f"**{h}** {ui.verdict_chip(v[h]['verdict'])} {per}", unsafe_allow_html=True)
    st.caption(stmt)

st.subheader("What this means")
st.markdown(
    "- **Egress-aware placement is never worse, and is sometimes much better.** The exact "
    "optimiser beats the egress-blind baseline B1 on every workload, and ties it when B1's "
    "price ties happen to break toward one location (B1-alt). The saving clears 20% "
    "only where large volumes move between components that B1 would split (T2).\n"
    "- **Exact beats heuristic at realistic sizes.** CBC proves the optimum quickly, so "
    "annealing's accuracy is good but its speed advantage does not materialise.\n"
    "- **No crossover, for a structural reason.** At these list prices one location is "
    "cheapest for every component on its own, so the optimum is single-provider at every "
    "traffic level. A crossover would need workloads whose parts prefer different "
    "providers, for example a component pinned to one cloud.\n"
    "- **The gain comes from coupling.** Treating edges as joint decisions is what saves "
    "money (chapter 8), not a more complete price table.")

st.subheader("Threats to validity")
st.caption("From the review-2 threats document: each threat with its direction of bias, "
           "its mitigation and the residual risk.")
for cat, rows in explain.threats_by_category().items():
    with st.expander(f"{cat} — {len(rows)} threats"):
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

ui.takeaway("The method is sound and reproducible: real prices, a measured workload, "
            "proven optima and replicated statistics. Its headline claims were tested "
            "honestly and mostly refuted, and the walkthrough shows exactly why. That is "
            "the finding.")
ui.sources([explain.BRIEF, explain.VERDICTS, explain.THREATS, explain.ABLATION])
ui.nav(FILE)
