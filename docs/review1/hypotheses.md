# P5 — Hypotheses (frozen)

These are copied word for word from `docs/methodology/project_brief.md §4`. They were frozen before
any placement result existed. The thresholds will not be changed after results exist. Each
hypothesis will be reported as **SUPPORTED**, **REFUTED** or **INCONCLUSIVE**, with the
numbers.

---

## H1 (objective O4) — egress-aware placement pays off

> **Frozen text.** For T1–T3 at their stated traffic volumes (edges ≥ 500 GB/month in
> aggregate), the egress-aware ILP placement reduces total monthly cost by **≥ 20%**
> relative to baseline B1.

**Standard form.** Method **X = egress-aware ILP (CBC)** reduces metric **M = total monthly
cost C(a), USD** by **≥ N = 20%** relative to baseline **B = B1 (cheapest-per-vCPU,
per component)**, under condition **C = topologies T1, T2 and T3 at their stated volumes,
aggregate inter-component traffic ≥ 500 GB/month, core location set, snapshot 2026-09-21**.

Reduction = (C(B1) − C(ILP)) / C(B1).

**Falsified if** the reduction is below 20% on any of T1–T3. It is **SUPPORTED** only if all
three reach ≥ 20%.

**Tested by:** M10 (ILP optimum) and M15 (penalty experiment); verdict in M16.

**Precondition check (already met).** Aggregate inter-component traffic is T1 1,265.50,
T2 3,621.0 and T3 2,768.94 GB/month (`topologies/README.md`), so all three are above 500.

**Known sensitivity (D-039).** In the snapshot, aws:us-east-1 and azure:eastus have exactly
the same price per vCPU-hour, so B1 has a tie. How the tie is broken changes B1's total. We
will report H1 against **both** B1 variants: the reported B1 and the opposite tie-break
(which equals B2-azure). The 20% threshold is the same for both.

---

## H2 (objective O3) — the heuristic is near-optimal and much faster

> **Frozen text.** Simulated annealing stays within **5%** of the CBC optimum (median over
> seeds) while reducing wall-clock time by **≥ 10×**, at ≥ 15 components and ≥ 20 candidate
> locations, on instances where CBC proves optimality.

**Standard form.** Method **X = simulated annealing** keeps metric **M1 = optimality gap
(C(SA) − C(ILP)) / C(ILP)** at **≤ N1 = 5%** (median over seeds) and reduces **M2 =
wall-clock solve time** by a factor of **≥ N2 = 10×**, relative to baseline **B = CBC exact
solve**, under condition **C = synthetic instances with ≥ 15 components and ≥ 20 candidate
locations (ext set) on which CBC reports status Optimal**, same machine.

**Falsified if** the median gap is above 5%, **or** the median speed-up is below 10×, on the
qualifying instances. **INCONCLUSIVE** if CBC proves optimality on no qualifying instance
within the time limit.

**Tested by:** M12 (annealing), M13 (harness and generator), M14 (scaling and
optimality-gap experiment); verdict in M16.

---

## H3 (objective O4, the headline) — a traffic-scale crossover exists

> **Frozen text.** There exists a traffic scale threshold T such that above T the
> cost-optimal placement uses a single provider while B1 remains multi-provider; below T the
> ordering inverts. Falsified if no crossover appears anywhere in the swept range (scale
> factors 10⁻² to 10²).

**Standard form.** Scaling all edge volumes by a factor s, method **X = cost-optimal (ILP)
placement** shows a threshold **T** in metric **M = providers used**. For s > T the optimum
uses **1 provider** while baseline **B = B1** uses **> 1 provider**. For s < T the ordering
inverts. Condition **C = T1–T3, s swept over 10⁻² to 10², core set, snapshot 2026-09-21**.

**Falsified if** no such crossover appears anywhere in the swept range.

**Tested by:** M15 (traffic sweep, penalty, crossover); verdict in M16.

**Note for the reader.** B1 ignores traffic, so its placement is the same at every s. B1's
provider count depends on the D-039 tie-break: on T1 and T2 it is 2 as reported and 1 under
the opposite tie-break. On T3 it is 1 in both (all aws:us-east-1 as reported). So a crossover
against the reported B1 is only possible on T1 and T2. M16 will state which B1 variant each crossover claim uses.

---

## Baselines (from `00_PROJECT_BRIEF.md §5`)

- **B1: cheapest-per-vCPU, independent.** Each component is placed independently at the
  location with the lowest `usd_per_hour / vcpu` for its fixed shape. Egress is ignored when
  choosing but **charged** when evaluating.
- **B2: single provider.** For each provider, every component goes to that provider's
  single cheapest region for the application's compute and storage bill. We report B2-aws,
  B2-azure, B2-gcp and B2-best (the cheapest of the three).

All methods are scored by the same function, `placement/cost.py::evaluate` (D-006).
Current baseline numbers: `baseline_results.md`.
