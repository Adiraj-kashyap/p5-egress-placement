"""Shared Streamlit pieces for the walkthrough chapters (M22): page frame, callouts,
verdict chips, navigation and the chart helpers.

Colour slots come from the validated reference palette (dataviz skill, light mode):
methods and cost terms each have a fixed slot that never changes with filtering, and every
chart ships a legend plus a data table because three slots sit below 3:1 contrast.
Providers keep the demo's provider colours (`core.PROVIDER_COLOURS`).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from demo import core, explain

#: Method id -> colour. Fixed per entity, never by rank.
METHOD_COLOURS = {"ilp_tight": "#2a78d6", "b1": "#eb6834", "b2_best": "#1baf7a",
                  "greedy_1opt": "#eda100", "sa": "#e87ba4", "greedy": "#6250d6",
                  "b1_alt": "#52514e"}
#: Short method names for chart legends and axes (the long ones truncate).
METHOD_LABELS = {"ilp_tight": "ILP (exact)", "b1": "B1 egress-blind", "b2_best": "B2-best",
                 "greedy_1opt": "Greedy + 1-opt", "sa": "Annealing", "greedy": "Greedy",
                 "b1_alt": "B1-alt tie-break"}
LEGEND = dict(orient="top", symbolOpacity=1, labelLimit=0)

#: Cost term -> colour (validated order: compute, storage, egress, internet).
TERM_COLOURS = {"compute": "#1baf7a", "storage": "#6250d6", "egress": "#e34948",
                "internet": "#eda100"}

VERDICT_STYLE = {"SUPPORTED": ("#0f7b3f", "#e3f4ea", "check_circle"),
                 "REFUTED": ("#b42318", "#fdecea", "cancel"),
                 "INCONCLUSIVE": ("#8a5a00", "#fdf4e3", "help")}

TOPO_LABEL = {"t1_three_tier": "T1 three-tier", "t2_pipeline": "T2 pipeline",
              "t3_microservices": "T3 microservices"}

CSS = """
<style>
.p5-callout {border-left: 4px solid var(--c); background: var(--bg); padding: .7rem 1rem;
  border-radius: 6px; margin: .6rem 0 1rem 0; color: #0b0b0b;}
.p5-callout b.k {display:block; font-size:.75rem; letter-spacing:.06em; text-transform:uppercase;
  color: var(--c); margin-bottom:.2rem;}
.p5-chip {display:inline-block; padding:2px 10px; border-radius:999px; font-weight:600;
  font-size:.82rem; border:1px solid var(--c); color: var(--c); background: var(--bg);}
.p5-prov {color:#fff; padding:2px 8px; border-radius:10px; font-size:.85em; white-space:nowrap;}
.p5-step {color:#52514e; font-size:.85rem; letter-spacing:.04em;}
</style>
"""


# --------------------------------------------------------------------------- frame


def page_header(file: str) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    i = explain.chapter_index(file)
    ch = explain.CHAPTERS[i]
    if i:
        st.markdown(f"<span class='p5-step'>CHAPTER {i} OF {len(explain.CHAPTERS) - 1}</span>",
                    unsafe_allow_html=True)
    st.title(ch.title.split("· ")[-1])
    st.caption(ch.blurb)


def _callout(kind: str, colour: str, bg: str, body: str) -> None:
    st.markdown(f"<div class='p5-callout' style='--c:{colour};--bg:{bg}'>"
                f"<b class='k'>{kind}</b>{body}</div>", unsafe_allow_html=True)


def what(body: str) -> None:
    """'What you are looking at' — sets the scene for a chapter."""
    _callout("What you are looking at", "#2a78d6", "#eef3fb", body)


def how_to_read(body: str) -> None:
    _callout("How to read it", "#52514e", "#f3f2ef", body)


def takeaway(body: str) -> None:
    _callout("Takeaway", "#0f7b3f", "#e3f4ea", body)


def sources(paths: list[str]) -> None:
    with st.expander("Source files for every number on this page"):
        st.markdown("\n".join(f"- `{p}`" for p in paths))
        st.caption("Nothing on this page is typed in by hand: values are read from these "
                   "committed files at run time, or computed live by `placement.cost.evaluate`.")


def nav(file: str) -> None:
    """Previous / Next links at the foot of a chapter."""
    i = explain.chapter_index(file)
    st.divider()
    left, _, right = st.columns([2, 1, 2])
    if i > 0:
        prev = explain.CHAPTERS[i - 1]
        left.page_link(prev.file, label=f"← {prev.title}", icon=prev.icon)
    if i < len(explain.CHAPTERS) - 1:
        nxt = explain.CHAPTERS[i + 1]
        right.page_link(nxt.file, label=f"Next: {nxt.title} →", icon=nxt.icon)


def verdict_chip(verdict: str, prefix: str = "") -> str:
    colour, bg, _ = VERDICT_STYLE.get(verdict, ("#52514e", "#f3f2ef", ""))
    mark = {"SUPPORTED": "✓", "REFUTED": "✗"}.get(verdict, "?")
    return (f"<span class='p5-chip' style='--c:{colour};--bg:{bg}'>"
            f"{mark} {prefix}{verdict}</span>")


def verdict_banner(h: str) -> None:
    """Hypothesis statement, overall verdict and per-topology chips, all from source files."""
    v = explain.verdicts()[h]
    stmt = explain.hypotheses()[h]
    chips = " ".join(verdict_chip(x, f"{t} ") for t, x in v["per_topology"].items())
    st.markdown(f"**{h} (frozen before any result):** {stmt}")
    st.markdown(f"Verdict: {verdict_chip(v['verdict'])} &nbsp; {chips}", unsafe_allow_html=True)


def provider_badge(loc: str) -> str:
    return (f"<span class='p5-prov' style='background:{core.provider_colour(loc)}'>"
            f"{loc}</span>")


def provider_legend() -> None:
    st.markdown(" ".join(f"<span class='p5-prov' style='background:{c}'>{p}</span>"
                         for p, c in core.PROVIDER_COLOURS.items()), unsafe_allow_html=True)


def data_table(df: pd.DataFrame, label: str = "Show the data") -> None:
    with st.expander(label):
        st.dataframe(df, width="stretch", hide_index=True)


# --------------------------------------------------------------------------- data


@st.cache_data(show_spinner=False)
def cache_df(name: str) -> pd.DataFrame:
    """A cached figure CSV as a DataFrame with numeric columns parsed."""
    df = pd.DataFrame(core.load_cache_csv(name))
    for col in df.columns:
        conv = pd.to_numeric(df[col], errors="coerce")
        if conv.notna().sum() == df[col].replace("", pd.NA).notna().sum():
            df[col] = conv
    return df


@st.cache_resource(show_spinner=False)
def instance(label: str, location_set: str = "core", traffic_scale: float = 1.0):
    return core.build_instance(core.TOPOLOGIES[label], location_set, traffic_scale)


# --------------------------------------------------------------------------- charts


def _scale(log: bool):
    return alt.Scale(type="log") if log else alt.Scale(zero=False)


def colour_scale(mapping: dict[str, str], domain: list[str]) -> alt.Scale:
    return alt.Scale(domain=domain, range=[mapping[d] for d in domain])


def band_lines(df: pd.DataFrame, x: str, y: str, series: str, colours: dict[str, str],
               labels: dict[str, str], x_title: str, y_title: str,
               log_x: bool = False, log_y: bool = False, height: int = 320,
               extra: alt.Chart | None = None) -> alt.Chart:
    """Mean lines with their 95% CI band per series, crosshair tooltip on hover."""
    # ILP is drawn last so that where heuristics coincide with the optimum it stays visible.
    df = df.copy()
    present = [k for k in colours if k in set(df[series])]
    rank = {k: (1 if k == "ilp_tight" else 0) for k in present}
    df = df.sort_values(series, key=lambda c: c.map(rank), kind="stable")
    df["series_label"] = df[series].map(lambda s: labels.get(s, s))
    dom = [labels.get(k, k) for k in present]
    cmap = {labels.get(k, k): colours[k] for k in present}
    col = alt.Color("series_label:N", scale=colour_scale(cmap, dom), title=None,
                    legend=alt.Legend(**LEGEND, symbolType="stroke", symbolStrokeWidth=3))
    base = alt.Chart(df).encode(x=alt.X(f"{x}:Q", scale=_scale(log_x), title=x_title))
    band = base.mark_area(opacity=0.18).encode(
        y=alt.Y("ci_lo:Q", scale=_scale(log_y), title=y_title), y2="ci_hi:Q", color=col)
    line = base.mark_line(strokeWidth=2).encode(y=alt.Y(f"{y}:Q"), color=col)
    hover = alt.selection_point(fields=[x], nearest=True, on="pointerover", empty=False)
    pts = base.mark_circle(size=60).encode(
        y=f"{y}:Q", color=col,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("series_label:N", title="series"),
                 alt.Tooltip(f"{x}:Q", format=",.3g", title=x_title),
                 alt.Tooltip(f"{y}:Q", format=",.2f", title="mean"),
                 alt.Tooltip("ci_lo:Q", format=",.2f", title="95% CI low"),
                 alt.Tooltip("ci_hi:Q", format=",.2f", title="95% CI high"),
                 alt.Tooltip("n:Q", title="n")]).add_params(hover)
    rule = base.mark_rule(color="#a8a7a1").encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0))).transform_filter(hover)
    layers = [band, line, rule, pts] + ([extra] if extra is not None else [])
    return alt.layer(*layers).properties(height=height)


def dots_with_ci(df: pd.DataFrame, y: str, colour_key: str, colours: dict[str, str],
                 labels: dict[str, str], x_title: str, height: int | None = None) -> alt.Chart:
    """One row per series: mean dot with its 95% CI line, on an axis that does not start at
    zero (bars would have to, and would hide differences of a few percent)."""
    df = df.copy()
    present = [k for k in colours if k in set(df[colour_key])]
    df["label"] = df[colour_key].map(lambda s: labels.get(s, s))
    dom = [labels.get(k, k) for k in present]
    cmap = {labels.get(k, k): colours[k] for k in present}
    col = alt.Color("label:N", scale=colour_scale(cmap, dom), title=None, legend=None)
    base = alt.Chart(df).encode(y=alt.Y("label:N", sort=dom, title=None))
    ci = base.mark_rule(strokeWidth=3).encode(
        x=alt.X("ci_lo:Q", title=x_title, scale=alt.Scale(zero=False)), x2="ci_hi:Q", color=col)
    dot = base.mark_point(filled=True, size=140, opacity=1, stroke="#fcfcfb",
                          strokeWidth=2).encode(
        x=f"{y}:Q", color=col,
        tooltip=[alt.Tooltip("label:N", title="method"),
                 alt.Tooltip(f"{y}:Q", format=",.2f", title="mean"),
                 alt.Tooltip("ci_lo:Q", format=",.2f", title="95% CI low"),
                 alt.Tooltip("ci_hi:Q", format=",.2f", title="95% CI high"),
                 alt.Tooltip("n:Q", title="n")])
    text = base.mark_text(align="left", dx=10, color="#52514e", fontSize=11).encode(
        x="ci_hi:Q", text=alt.Text(f"{y}:Q", format="$,.2f"))
    return alt.layer(ci, dot, text).properties(height=height or 36 * len(present) + 40)


def stacked_cost(rows: list[dict], label_key: str = "method",
                 height: int | None = None) -> alt.Chart:
    """Stacked compute/storage/egress/internet bars per method (live, single solve each).
    Bar thickness is pinned: left to the theme, nominal bands collapse to hairlines."""
    height = height or 48 * len(rows) + 50
    long = [{"method": r[label_key], "term": t, "usd": r[t]} for r in rows for t in TERM_COLOURS]
    df = pd.DataFrame(long)
    order = list(TERM_COLOURS)
    return alt.Chart(df).mark_bar(stroke="#fcfcfb", strokeWidth=2, size=30).encode(
        y=alt.Y("method:N", title=None, sort=[r[label_key] for r in rows]),
        x=alt.X("usd:Q", title="USD per month", stack=True),
        color=alt.Color("term:N", scale=colour_scale(TERM_COLOURS, order),
                        sort=order, title=None, legend=alt.Legend(**LEGEND)),
        order=alt.Order("term_order:Q"),
        tooltip=[alt.Tooltip("method:N"), alt.Tooltip("term:N"),
                 alt.Tooltip("usd:Q", format="$,.2f", title="USD / month")],
    ).transform_calculate(
        term_order="indexof(" + str(order).replace("'", '"') + ", datum.term)"
    ).properties(height=height)
