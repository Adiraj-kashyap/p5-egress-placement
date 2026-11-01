"""Chapter 1 — O1: the unified price model (compute, storage, internet, inter-location egress)."""

import altair as alt
import pandas as pd
import streamlit as st

from demo import core, explain, ui

FILE = "chapters/01_pricing.py"
ui.page_header(FILE)

ui.what("Real list prices pulled from the AWS Price List API, the Azure Retail Prices API "
        f"and Google's public pricing pages, frozen as one snapshot ({core.SNAPSHOT_DATE}) "
        "so every experiment uses identical prices. Linux, on-demand, shared tenancy.")

loc_set = st.radio("Locations", ["core", "ext"], horizontal=True,
                   format_func=lambda s: {"core": "core (4 regions per provider)",
                                          "ext": "ext (8 regions per provider)"}[s])
ui.provider_legend()

# ---- compute
st.subheader("Compute: price per vCPU-hour")
comp = pd.DataFrame(explain.compute_prices(loc_set))
cheapest = comp["usd_per_vcpu_hour"].min()
chart = alt.Chart(comp).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
    y=alt.Y("location:N", sort="x", title=None),
    x=alt.X("usd_per_vcpu_hour:Q", title="USD per vCPU-hour", scale=alt.Scale(zero=False)),
    color=alt.Color("provider:N", scale=ui.colour_scale(core.PROVIDER_COLOURS,
                                                        list(core.PROVIDER_COLOURS)),
                    legend=None),
    tooltip=["location", "instance_type",
             alt.Tooltip("usd_per_vcpu_hour:Q", format="$.4f", title="USD / vCPU-hour"),
             alt.Tooltip("usd_per_month_small:Q", format="$,.2f", title="2-vCPU VM / month")],
).properties(height=30 * len(comp))
st.altair_chart(chart, width="stretch")
tied = comp[comp["usd_per_vcpu_hour"] == cheapest]["location"].tolist()
st.caption(f"Cheapest: USD {cheapest:.4f}/vCPU-hour at {', '.join(tied)}; most expensive "
           f"USD {comp['usd_per_vcpu_hour'].max():.4f} "
           f"({comp['usd_per_vcpu_hour'].max() / cheapest:.2f}x).")
ui.data_table(comp)

# ---- egress
st.subheader("Egress: price per GB sent from one location to another")
eg = pd.DataFrame(explain.egress_prices(loc_set))
order = explain.locations(loc_set)
heat = alt.Chart(eg).mark_rect(stroke="#fcfcfb", strokeWidth=1).encode(
    x=alt.X("to:N", sort=order, title="receiver"),
    y=alt.Y("from:N", sort=order, title="sender (pays)"),
    color=alt.Color("usd_per_gb:Q", title="USD/GB",
                    scale=alt.Scale(scheme="blues", domainMin=0)),
    tooltip=["from", "to", alt.Tooltip("usd_per_gb:Q", format="$.3f", title="USD / GB"),
             "rule", "meaning"],
).properties(height=max(360, 34 * len(order)))
st.altair_chart(heat, width="stretch")
rules = pd.DataFrame(explain.egress_rule_summary(loc_set))
st.dataframe(rules, width="stretch", hide_index=True,
             column_config={"min_usd_per_gb": st.column_config.NumberColumn(format="$%.3f"),
                            "max_usd_per_gb": st.column_config.NumberColumn(format="$%.3f")})
ui.how_to_read("Each cell is what the <b>sender</b> pays per GB. The diagonal is free (R1: "
               "same region). Inside one provider, traffic between regions costs a little "
               "(R2). Across providers the sender pays its full internet egress rate (R3), "
               "so the dark blocks off the diagonal are what makes splitting an app "
               "across clouds expensive. The matrix is not symmetric: price depends on "
               "who sends.")

# ---- internet & storage
st.subheader("Internet egress to end users, and storage")
ui.data_table(pd.DataFrame(explain.internet_storage_prices(loc_set)), "Show the table")

st.subheader("Validation of the price model")
result, checks = explain.validation_checks()
st.success(result)
ui.data_table(pd.DataFrame(checks), "Show all validation checks")

r3 = rules[rules["rule"] == "R3"].iloc[0]
r2 = rules[rules["rule"] == "R2"].iloc[0]
ui.takeaway(f"Compute prices differ by at most {comp['usd_per_vcpu_hour'].max() / cheapest:.2f}x "
            f"across locations, while one GB sent to another provider costs "
            f"${r3['min_usd_per_gb']:.3f}–${r3['max_usd_per_gb']:.3f}, against "
            f"${r2['min_usd_per_gb']:.2f}–${r2['max_usd_per_gb']:.2f} inside one provider "
            "and nothing inside one region. The saving from cheaper compute has to beat that.")
ui.sources([f"cost_model/{core.SNAPSHOT_DATE}/compute.csv",
            f"cost_model/{core.SNAPSHOT_DATE}/egress.csv",
            f"cost_model/{core.SNAPSHOT_DATE}/internet.csv",
            f"cost_model/{core.SNAPSHOT_DATE}/storage.csv", explain.VALIDATION,
            "cost_model/README.md (rules R1–R3)"])
ui.nav(FILE)
