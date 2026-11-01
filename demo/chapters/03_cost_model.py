"""Chapter 3 — O2: the cost model, and a sandbox to price a placement by hand."""

import pandas as pd
import streamlit as st

from demo import core, ui
from placement.cost import evaluate
from placement.instance import provider_of

FILE = "chapters/03_cost_model.py"
ui.page_header(FILE)

ui.what("The single cost function every method in this project is scored by. Its last two "
        "terms are why placement is hard: egress is charged on <b>pairs</b> of locations, "
        "so where one component should go depends on where its neighbours went.")

st.latex(r"""\begin{aligned}
C(a)={}&\underbrace{\sum_c \text{compute}[\text{shape}(c),a(c)]\cdot 730}_{\text{compute}}
+\underbrace{\sum_c \text{gb}_c\cdot\text{storage}[a(c)]}_{\text{storage}}\\
&+\underbrace{\sum_{u\to v}\text{gb}(u{\to}v)\cdot\text{egress}[a(u),a(v)]}_{\text{egress (sender pays)}}
+\underbrace{\sum_c \text{gb}(c{\to}\text{users})\cdot\text{internet}[a(c)]}_{\text{internet}}
\end{aligned}""")
st.caption("a(c) is the location chosen for component c. The exact solver minimises C over "
           "every possible a as an integer linear program (chapter 4); `docs/report/"
           "formulation.md` gives the linearisation.")

st.subheader("Try it: place the components yourself")
label = st.selectbox("Workload", list(core.TOPOLOGIES), key="cm_topo")
inst = ui.instance(label)


with st.spinner("Solving the reference placements…"):  # live, never cached (§S13)
    ref = core.run_methods(inst, ("ilp_tight", "b1"))
ilp = next(r for r in ref.results if r.method == "ilp_tight")
b1 = next(r for r in ref.results if r.method == "b1")


def load(assignment: dict) -> None:
    for c, loc in assignment.items():
        st.session_state[f"cm_{label}_{c}"] = loc


b_a, b_b, b_c = st.columns(3)
if b_a.button("Start from B1 (cheapest compute per component)", width="stretch"):
    load(b1.assignment)
if b_b.button("Show the ILP optimum", width="stretch"):
    load(ilp.assignment)
if b_c.button("Spread across providers", width="stretch"):
    load({c: next((l for l in inst.allowed[c]
                   if provider_of(l) == list(core.PROVIDER_COLOURS)[i % 3]), inst.allowed[c][0])
          for i, c in enumerate(inst.components)})

cols = st.columns(min(4, len(inst.components)))
assignment = {}
for i, c in enumerate(inst.components):
    key = f"cm_{label}_{c}"
    st.session_state.setdefault(key, b1.assignment[c])
    assignment[c] = cols[i % len(cols)].selectbox(
        f"{c} · {inst.vcpu[c]} vCPU", inst.allowed[c], key=key)

mine = evaluate(inst, assignment)
gap = 100 * (mine.total - ilp.total) / ilp.total
m1, m2, m3, m4 = st.columns(4)
m1.metric("Your monthly bill", f"${mine.total:,.2f}",
          f"{gap:+.2f}% vs optimum" if abs(gap) > 1e-9 else "= optimum",
          delta_color="inverse")
m2.metric("Egress between components", f"${mine.egress:,.2f}")
m2.caption(f"{100 * mine.egress_share:.1f}% of the bill")
m3.metric("Providers used", mine.providers_used)
m4.metric("ILP optimum", f"${ilp.total:,.2f}")
m4.caption("proven optimal" if ilp.proven_optimal else "best found, not proven")

rows = [{"method": name, **{t: getattr(cb, t) for t in ui.TERM_COLOURS}}
        for name, cb in (("Your placement", mine), ("B1 (egress-blind)", b1.cost),
                         ("ILP optimum", ilp.cost))]
st.altair_chart(ui.stacked_cost(rows), width="stretch")

st.markdown("**Every edge under your placement**")
edges = [{"from": u, "to": v, "GB/month": gb, "sender": assignment[u],
          "receiver": assignment[v],
          "price USD/GB": inst.egress[(assignment[u], assignment[v])],
          "crosses a provider": provider_of(assignment[u]) != provider_of(assignment[v])}
         for u, v, gb in inst.edges]
st.dataframe(pd.DataFrame(edges), width="stretch", hide_index=True,
             column_config={"price USD/GB": st.column_config.NumberColumn(format="$%.3f")})

ui.how_to_read("Change any dropdown and the bill is re-priced instantly by the same "
               "`evaluate` function the experiments use. Try moving one component of the "
               "optimum to another provider: its compute may get cheaper, but every edge "
               "touching it turns from free to billed.")
ui.takeaway(f"On {label.split(' (')[0]}, the egress-blind choice B1 costs "
            f"${b1.total:,.2f}/month against an optimum of ${ilp.total:,.2f} "
            f"({100 * (b1.total - ilp.total) / ilp.total:+.2f}%). The optimum is found by "
            "solving all components jointly, not one at a time.")
ui.sources([f"cost_model/{core.SNAPSHOT_DATE}/*.csv", core.TOPOLOGIES[label],
            "placement/cost.py (evaluate)", "docs/report/formulation.md"])
ui.nav(FILE)
