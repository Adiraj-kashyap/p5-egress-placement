"""The single cost evaluator (D-006). Every method, baseline and experiment is scored here.

C(a) = sum_c k[c, a(c)]                          # compute x 730 + storage
     + sum_(u->v) gb(u->v) * egress[a(u), a(v)]  # directed edges, sender pays
     + sum_c gb(c->internet) * r[a(c)]           # traffic to end users
(00_PROJECT_BRIEF §6)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from placement.instance import Instance, provider_of


@dataclass(frozen=True)
class CostBreakdown:
    """Monthly cost of one assignment, USD, split by term.

    `egress` is inter-component transfer only; `internet` is end-user egress.
    `egress_share` = egress / total (D-040). `providers_used` = distinct providers in the
    assignment.
    """

    total: float
    compute: float
    storage: float
    egress: float
    internet: float
    egress_share: float
    providers_used: int

    def as_dict(self) -> dict:
        """Plain dict of the fields, for CSV/JSON output."""
        return asdict(self)


def check_assignment(instance: Instance, assignment: Mapping[str, str]) -> None:
    """Raise ValueError unless `assignment` maps exactly the instance's components to allowed locations."""
    if set(assignment) != set(instance.components):
        missing = set(instance.components) - set(assignment)
        extra = set(assignment) - set(instance.components)
        raise ValueError(f"assignment mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    for c in instance.components:
        if assignment[c] not in instance.allowed[c]:
            raise ValueError(f"{c} -> {assignment[c]} is not an allowed location")


def evaluate(instance: Instance, assignment: Mapping[str, str]) -> CostBreakdown:
    """Return the monthly `CostBreakdown` of placing each component at `assignment[c]`.

    This is the only function in the project that computes a cost (01_CONVENTIONS §5).
    Terms are summed in the instance's fixed component and edge order, so the result does
    not depend on the iteration order of `assignment`.
    """
    check_assignment(instance, assignment)
    a = assignment
    compute = sum(instance.compute_month[(c, a[c])] for c in instance.components)
    storage = sum(instance.storage_month[(c, a[c])] for c in instance.components)
    egress = sum(gb * instance.egress[(a[u], a[v])] for u, v, gb in instance.edges)
    internet = sum(instance.internet_gb[c] * instance.r[a[c]]
                   for c in instance.components if c in instance.internet_gb)
    total = compute + storage + egress + internet
    return CostBreakdown(
        total=total,
        compute=compute,
        storage=storage,
        egress=egress,
        internet=internet,
        egress_share=egress / total if total > 0 else 0.0,
        providers_used=len({provider_of(a[c]) for c in instance.components}),
    )
