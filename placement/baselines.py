"""Assignment-named baselines B1 and B2 (00_PROJECT_BRIEF §5).

Both choose locations without looking at transfer prices; both are scored by
`placement.cost.evaluate`, which does charge transfer. Tie-breaking is deterministic and
documented in D-039.
"""
from __future__ import annotations

from placement.cost import CostBreakdown, evaluate
from placement.instance import Instance, provider_of

PROVIDERS = ("aws", "azure", "gcp")

# Per-vCPU prices are rounded before comparison so equal list prices compare equal.
_PRICE_DIGITS = 9


def b1_key(instance: Instance, c: str, loc: str) -> tuple[float, float]:
    """B1 ranking key of `loc` for component `c`: (usd_per_hour / vcpu, compute+storage monthly).

    The first element is the brief's criterion; the second breaks exact price ties by the
    component's own (egress-blind) bill, so a stateful component prefers cheaper storage.
    """
    per_vcpu = round(instance.usd_per_hour[(instance.shape[c], loc)] / instance.vcpu[c], _PRICE_DIGITS)
    return per_vcpu, round(instance.k[(c, loc)], _PRICE_DIGITS)


def b1_tied_locations(instance: Instance, c: str) -> list[str]:
    """All allowed locations of `c` that share the best B1 key, in location-id order."""
    best = min(b1_key(instance, c, l) for l in instance.allowed[c])
    return sorted(l for l in instance.allowed[c] if b1_key(instance, c, l) == best)


def b1_cheapest_per_vcpu(instance: Instance) -> dict[str, str]:
    """B1: place each component independently at its cheapest location per vCPU.

    For each component, minimise usd_per_hour / vcpu of its fixed shape; ties go to the
    lower compute+storage monthly bill, then to the lexicographically smallest location id
    (D-039). Transfer prices are ignored when choosing.
    """
    return {c: b1_tied_locations(instance, c)[0] for c in instance.components}


def b2_single_provider(instance: Instance, provider: str) -> dict[str, str]:
    """B2-<provider>: put every component in the provider's cheapest single region.

    The region minimises the application's total compute + storage bill (sum of k[c, l]);
    ties go to the smallest location id. Raises ValueError if no region of `provider` is
    allowed for every component (e.g. a component pinned elsewhere).
    """
    regions = [l for l in instance.locations
               if provider_of(l) == provider and all(l in instance.allowed[c] for c in instance.components)]
    if not regions:
        raise ValueError(f"no {provider} region can host every component of {instance.instance_id}")
    best = min(regions, key=lambda l: (round(sum(instance.k[(c, l)] for c in instance.components),
                                              _PRICE_DIGITS), l))
    return {c: best for c in instance.components}


def b2_best(instance: Instance) -> tuple[str, dict[str, str], CostBreakdown]:
    """B2-best: the B2 provider with the lowest evaluated total cost.

    Returns (provider, assignment, breakdown). Ties go to the provider earlier in
    PROVIDERS order. Providers that cannot host every component (pins, D-049) are skipped;
    ValueError if none can.
    """
    scored = []
    for p in PROVIDERS:
        try:
            a = b2_single_provider(instance, p)
        except ValueError:
            continue
        scored.append((evaluate(instance, a), p, a))
    if not scored:
        raise ValueError(f"no single provider can host every component of {instance.instance_id}")
    cost, p, a = min(scored, key=lambda t: (round(t[0].total, _PRICE_DIGITS), PROVIDERS.index(t[1])))
    return p, a, cost
