"""Ablation variants: switch off one ingredient of the method at a time (06 §S12).

Every variant changes only the **objective or the feasible set used for choosing**. The
assignment it returns is always scored by the full, true `placement.cost.evaluate` in the
runner, so the reported cost of a crippled variant is what that choice really costs.

The trick throughout is that each variant is the ordinary tight ILP solved on a *modified*
`Instance` built with `dataclasses.replace`:

    ilp_no_edge_egress   edges = ()                     inter-component egress term dropped
    ilp_undirected       egress symmetrised to the mean of the two directions
    ilp_no_internet      internet_gb = {}               end-user egress dropped
    ilp_single_provider  allowed restricted to one provider (best of 3, by true cost)

`ilp_no_edge_egress` is the pivotal one: with the edge term gone the objective is a sum of
per-component terms, so its optimum **is** a per-component choice (asserted in the tests).
Any gain from `ilp_no_edge_egress` to `ilp_full` is therefore gain no independent
per-component method can reach, however good its price vector.

The sensitivity transforms (`scale_cross_provider_egress`, `restrict_locations_per_provider`)
are different in kind: they change the world, not the objective, so results under them are
scored under the modified prices and are not comparable with the s = 1 baseline row.
"""
from __future__ import annotations

from dataclasses import replace

from placement.baselines import _PRICE_DIGITS, PROVIDERS
from placement.cost import evaluate
from placement.ilp import solve_ilp
from placement.instance import Instance, provider_of

# The decomposition of the total gain G = C(B1) - C(ILP), in order (06 §S12).
# Each step is (from_method, to_method, what it buys). They telescope to G per draw.
DECOMPOSITION: tuple[tuple[str, str, str], ...] = (
    ("b1", "b1_storage", "pricing storage alongside compute"),
    ("b1_storage", "ilp_no_edge_egress", "also pricing user-facing internet egress"),
    ("ilp_no_edge_egress", "ilp_full", "modelling inter-component egress"),
)


# --------------------------------------------------------------------------- objective variants

def no_edge_egress(instance: Instance) -> Instance:
    """`instance` with every inter-component edge removed from the objective."""
    return replace(instance, edges=())


def no_internet(instance: Instance) -> Instance:
    """`instance` with all end-user (internet) egress volume removed from the objective."""
    return replace(instance, internet_gb={})


def undirected(instance: Instance) -> Instance:
    """`instance` with egress symmetrised: both directions priced at the mean of the two rates."""
    p = instance.egress
    return replace(instance, egress={(a, b): 0.5 * (p[(a, b)] + p[(b, a)])
                                     for a in instance.locations for b in instance.locations})


def single_provider(instance: Instance, provider: str) -> Instance:
    """`instance` with every component restricted to `provider`'s regions.

    Raises ValueError when some component has no allowed region of `provider` (a pin
    elsewhere), which is how `ilp_single_provider` knows to skip that provider (D-049).
    """
    allowed = {c: tuple(l for l in instance.allowed[c] if provider_of(l) == provider)
               for c in instance.components}
    empty = [c for c, ls in allowed.items() if not ls]
    if empty:
        raise ValueError(f"no {provider} region is allowed for {empty[:3]} in {instance.instance_id}")
    return replace(instance, allowed=allowed)


def per_component_argmin(instance: Instance) -> dict[str, str]:
    """Argmin of the separable cost (compute + storage + internet) per component, ties to the
    smallest location id.

    With the coupling term gone the objective separates, so `ilp_no_edge_egress` and this
    independent choice reach the same **cost**. They need not agree component by component:
    ties are frequent at these prices (D-039, D-045) and CBC breaks them arbitrarily, so the
    A2 separability test compares separable costs, not assignments.
    """
    out = {}
    for c in instance.components:
        q = instance.internet_gb.get(c, 0.0)
        out[c] = min(instance.allowed[c],
                     key=lambda l: (round(instance.k[(c, l)] + q * instance.r[l], _PRICE_DIGITS), l))
    return out


def b1_storage(instance: Instance) -> dict[str, str]:
    """B1 variant that ranks locations by the component's compute **+ storage** monthly bill.

    B1 proper ranks by usd_per_hour / vCPU and uses the compute+storage bill only to break
    exact ties (D-039); this variant promotes storage to the primary criterion. It still
    ignores every transfer price, so it separates "counting storage" from "egress awareness".
    """
    return {c: min(instance.allowed[c], key=lambda l: (round(instance.k[(c, l)], _PRICE_DIGITS), l))
            for c in instance.components}


def solve_best_single_provider(instance: Instance, time_limit: float | None = None,
                               log_path=None) -> tuple[str, object]:
    """Solve the full ILP once per provider and keep the (provider, Result) with the lowest true cost.

    Providers that cannot host every component are skipped (D-049); ValueError if none can.
    Ties go to the provider earlier in `PROVIDERS` order, as in `baselines.b2_best`.
    """
    scored = []
    for i, p in enumerate(PROVIDERS):
        try:
            restricted = single_provider(instance, p)
        except ValueError:
            continue
        res = solve_ilp(restricted, time_limit if time_limit is not None else 600,
                        "tight", log_path=None if log_path is None else f"{log_path}.{p}")
        if res.assignment is None:
            continue
        scored.append((round(evaluate(instance, res.assignment).total, _PRICE_DIGITS), i, p, res))
    if not scored:
        raise ValueError(f"no single provider yields a solution for {instance.instance_id}")
    _, _, provider, result = min(scored, key=lambda t: (t[0], t[1]))
    return provider, result


# --------------------------------------------------------------------------- sensitivity transforms

def scale_cross_provider_egress(instance: Instance, multiplier: float) -> Instance:
    """`instance` with every **cross-provider** egress rate multiplied by `multiplier`.

    Same-provider rates (including the zero diagonal and intra-provider inter-region transfer)
    and internet rates are untouched, so the knob is exactly "how much does leaving a provider
    cost" (06 §S12 price-ratio sweep). This changes the true cost model, so results are
    comparable only within one multiplier.
    """
    if multiplier < 0:
        raise ValueError(f"egress multiplier must be >= 0, got {multiplier}")
    p = instance.egress
    return replace(instance, egress={
        (a, b): p[(a, b)] * multiplier if provider_of(a) != provider_of(b) else p[(a, b)]
        for a in instance.locations for b in instance.locations})


def restrict_locations_per_provider(instance: Instance, k: int) -> Instance:
    """`instance` restricted to the first `k` regions of each provider, in the instance's own order.

    Used for the locations-per-provider sweep {1, 2, 4, 8} over the ext location set. The
    order is `pricing.common.LOCATIONS_EXT` declaration order, which lists each provider's
    four core regions before its four ext-only ones, so the grids nest exactly:
    k = 1 ⊂ k = 2 ⊂ k = 4 (= the core location set) ⊂ k = 8 (= ext). A component pinned
    entirely outside the subset raises ValueError rather than being silently dropped.
    """
    if k < 1:
        raise ValueError(f"locations per provider must be >= 1, got {k}")
    keep: list[str] = []
    for provider in PROVIDERS:
        keep.extend([l for l in instance.locations if provider_of(l) == provider][:k])
    kept = tuple(l for l in instance.locations if l in set(keep))  # keep the instance's own order
    if not kept:
        raise ValueError(f"locations_per_provider={k} kept no location of {instance.instance_id}")
    allowed = {c: tuple(l for l in instance.allowed[c] if l in set(kept)) for c in instance.components}
    empty = [c for c, ls in allowed.items() if not ls]
    if empty:
        raise ValueError(f"locations_per_provider={k} leaves {empty[:3]} with no allowed location")
    return replace(
        instance,
        locations=kept,
        allowed=allowed,
        usd_per_hour={key: v for key, v in instance.usd_per_hour.items() if key[1] in set(kept)},
        compute_month={key: v for key, v in instance.compute_month.items() if key[1] in set(kept)},
        storage_month={key: v for key, v in instance.storage_month.items() if key[1] in set(kept)},
        k={key: v for key, v in instance.k.items() if key[1] in set(kept)},
        r={l: v for l, v in instance.r.items() if l in set(kept)},
        egress={key: v for key, v in instance.egress.items() if key[0] in set(kept) and key[1] in set(kept)},
    )
