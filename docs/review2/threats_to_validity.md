# Threats to validity

Review-2 rubric line: *"Threats to validity" (1 mark)*. Structure: the four standard categories
(Wohlin et al.), as required by `06_SKILLS_V2.md §S16`. Each threat states the **direction of
bias** — whether it makes the method look better (over-states the gain) or worse — the
**mitigation** actually done, and the **residual risk** that remains.

Checked by `python -m analysis.check_threats` (acceptance check A3): the four categories must be
present, every row must be complete, and every waiver and limitation recorded in
`state/AUDIT_LOG.md` and `docs/design_decisions.md` must appear on this page (mapping at the bottom).

## Construct validity — do the metrics measure what we claim?

| # | Threat | Direction | Mitigation | Residual risk |
|---|---|---|---|---|
| C1 | **List price ≠ invoice.** All costs are public list prices (D-003). Sustained-use discounts (automatic on GCP N2), committed-use discounts, savings plans, reservations and enterprise agreements are not modelled. | Unknown per term, but discounts apply mostly to **compute**, which is the term the method does *not* change; discounting compute raises egress's share and would **under-state** our gain. | Every price carries its SKU/page and date; the model is one snapshot (2026-09-21) reproducible from `snapshots/`. | A real bill could differ by tens of percent in absolute terms. The *relative* comparison is on the same price basis for all methods. |
| C2 | **Free egress allowances ignored** (100 GB/month on some providers; tiering flattened to the first paid tier, D-007, D-018). | **Over-states** the gain at small volumes: a workload under the free allowance pays no egress at all. | The flattening rule is explicit and applied identically to every method; the sweep goes down to s = 0.01, where the penalty is visibly small (0.43 % on T1). | Below roughly 100 GB/month, the reported penalty is an upper bound on the true one. |
| C3 | **Payload bytes vs billed wire bytes.** T1's measured volumes count TCP-payload bytes at the application socket, not the IP bytes a provider meters (D-037, D-038). | **Under-states** cost slightly for every method (headers and retransmissions are unbilled here); ratios in `testbed/README.md`. | Two independent counters (per-edge socket counters and pod `eth0` statistics) were compared; app/interface ratio 0.649–0.942. | A 6–35 % undercount of billable bytes on T1, applied equally to all methods. |
| C4 | **Month = 730 hours; always-on components.** Hourly prices × 730; no autoscaling, no spot/preemptible, no idle shutdown. | Neutral between methods; **over-states** absolute cost for bursty services. | Stated in `cost_model/README.md`; the same factor multiplies every method. | Results apply to always-on services only — that is the declared scope. |
| C5 | **`egress_share` counts inter-component traffic only**; internet egress is reported separately (D-040). | Neutral, but a reader could misread the metric. | Defined in D-040, and both terms are shown separately in F1. | On T3 the entire gain is internet egress, so a reader who only looks at `egress_share` would conclude the method does nothing there. |
| C6 | **Cross-zone, load-balancer, NAT and request-count charges are not modelled.** | **Under-states** absolute cost; direction on the *gain* is unknown, since cross-zone charges would penalise splitting further. | Scope stated in `cost_model/README.md`. | If included, they would most likely increase the cost of distributed placements and help the method. |

## Internal validity — could something else explain the result?

| # | Threat | Direction | Mitigation | Residual risk |
|---|---|---|---|---|
| I1 | **B1 is tie-break sensitive** (D-039, D-044): AWS `us-east-1` and Azure `eastus` cost exactly the same per vCPU-hour, so the baseline's split — and therefore all of its egress — comes from the storage tie-break. Under the opposite tie-break (B1-alt) the ILP's saving is **0.00 % everywhere**. | This is the largest single threat: the reported 3.29 / 22.55 / 1.76 % could be called an artefact of one arbitrary rule. | Both variants are computed and reported in every table, figure and verdict; the tie-break was chosen before results were seen and was never re-tuned (D-045 records the same effect inside greedy). | The honest statement is: *against an egress-blind baseline that happens to split providers, the saving is as reported; against one that happens to colocate, it is zero.* |
| I2 | **Egress tiers flattened; Azure R2 rates assigned by continent pair** (D-007, D-018, D-034). | Unknown; affects all methods identically. | V8 shows **0 of 168 R2 cells use a fallback rate** — every same-provider cell has a real SKU. V9 shows 0 rule/endpoint mismatches. | Continent-pair assignment could misprice an unusual pair; none is used in the core set results. |
| I3 | **GCP prices come from public pricing pages, not the Billing API** (M04 waiver, D-021, D-026, D-027, D-028). N2 core/RAM rates are fitted from machine-type prices; GiB→GB conversion applied. | Unknown; V6 bounds the error (GCP composed vs AWS matched-region ratios 0.998–1.155). | Page SHA-256 and access time recorded; the API path is implemented but untested. | A page-layout change would break reproduction; the committed snapshot protects the results. |
| I4 | **Shape is fixed per component** (D-004): the optimiser chooses *where*, never *what size*. | Neutral for the comparison (all methods use the same shapes) but it removes a confound. | Deliberate scope decision, stated in the formulation. | A joint sizing+placement optimiser might find savings this study cannot see. |
| I5 | **Only one pricing snapshot date** (2026-09-21) and one shape family per provider (Dsv5 / m5 / N2, D-003). | Unknown. | The date is pinned in every runs.csv row; `pricing/` can re-pull. | Prices move; the F7 sensitivity axis (×0.5–×1.5) is the substitute for a second date. |
| I6 | **SA was tuned on a subset** (α sweep on T3 + two synthetic instances, D-047), and greedy's tie-break favours the smallest location id (D-044). | Would flatter the heuristics, not the ILP. | The ablations show SA's design choices are worth ≤ 0.2 %; the ILP, not SA, produces the headline number. | Negligible for the reported conclusions. |
| I7 | **Runtime measurements share one machine** (Ryzen 9 6900HS, threads = 1), and the M14 scaling run overlapped a parallel experiment tab (D-053). | Could distort H2's speed-up in either direction. | ILP and SA jobs were interleaved per instance, so both saw the same load; timing repeats (n = 3) were later re-run cleanly in `results/timing/`. | The H2 speed-up clause (0.63×) is far from its 10× threshold, so contention cannot explain the verdict. |
| I8 | **Six CBC jobs hung at 0 % CPU and were killed** (D-070); three more in M17. | None: a killed job writes **no row**. | Every killed job was re-solved on rerun and returned `optimal`; the watchdog only kills a cbc child with no CPU growth and a 0-byte log. | No reported number derives from a killed run. |
| I9 | **Runtime outlier kept** in M10 (T2 McCormick repeat 5: 10.05 s of wall clock for 0.02 s of solver work, D-043). | Would make McCormick look slower. | The row is kept and **medians** are reported, not means. | None material. |
| I10 | **Generated artefacts could drift from the data.** Every figure, table and verdict is produced by a script with a `--check` mode, and `tests/test_analysis.py` (33 tests) fails on any drift. | — | A3 (`analysis.check_numbers`) verifies that every number in the prose appears in a generated table. | A hand edit to a generated file is caught by the test suite, not by review. |

## External validity — does it generalise?

| # | Threat | Direction | Mitigation | Residual risk |
|---|---|---|---|---|
| E1 | **Three topologies plus synthetic instances.** T1 three-tier (measured), T2 pipeline, T3 microservices (Online Boutique, 30 directed edges). | The conclusion is topology-dependent: H1 holds on exactly one of the three. | Synthetic instances up to n = 40 with seeded generation (D-050) widen the structural range. | A different application mix could give a very different headline number; we report per topology and never pool the three. |
| E2 | **The gain depends almost entirely on one ratio** — inter-component GB/month over total bill. | — | Both quantities are reported per topology; the sweep varies the ratio across four orders of magnitude. | Anyone applying the method must compute that ratio for their own workload first. |
| E3 | **Synthetic locust workload mix** on T1 (browse 6 / detail 3 / order 1, seeded), 60 s cache TTL, measured at ~19.6 req/s and scaled linearly to 50 req/s (D-037, D-038). | Unknown; linear scaling ignores caching non-linearities. | Three independent 10-minute runs, max CV 0.87 %; full protocol in `testbed/README.md`. | Real user mixes are not linear; T1's absolute volumes carry that assumption. |
| E4 | **24 locations, 3 providers, one snapshot.** Private interconnects (Direct Connect, ExpressRoute, Cloud Interconnect) and CDN egress are not modelled — they are the standard way to cut exactly this bill. | **Over-states** the value of placement optimisation for organisations that already have an interconnect. | Scope stated; F7 shows the saving is almost flat in the number of locations (≤ 0.10 pp from 1 to 8 per provider). | For a large enterprise the realistic alternative to this method is a private circuit, not a different placement. |
| E5 | **No latency, SLO, data-residency or availability constraints.** The cost-optimal placement is colocation, which may be operationally unacceptable. | **Over-states** the achievable saving: a placement forbidden by an SLO cannot be taken. | Provider pins (`pinned_to`, D-048) exist in the model and are tested, and `b2_best` skips infeasible providers (D-049), but no constrained experiment was run. | This is the single biggest gap between the result and practice, and the obvious next experiment (§ below). |
| E6 | **H3's refutation is snapshot-specific** (D-060): `azure:eastus` minimises every component's own cost on T1–T3, so colocation is optimal at every traffic scale and no crossover can exist. | Neutral — it is a finding, not a bias. | Stated with its mechanism in `verdicts.md`; `ilp_undirected` and `ilp_single_provider` cost 0.00 % for the same reason. | The multi-provider machinery is therefore **untested by these instances**, even though it is implemented and unit-tested. |

## Conclusion validity — are the statistics sound?

| # | Threat | Direction | Mitigation | Residual risk |
|---|---|---|---|---|
| S1 | **The uncertainty models are assumptions, not measurements**, for T2 and T3 (global × per-edge lognormal, σ = 0.3; 05 §3). Only T1 resamples real measured runs. | Widths of T2/T3 CIs are as arbitrary as σ. | σ was registered in 05 §3 before any draw; the same draws feed every method, so the *paired* comparison does not depend on σ. | T2's CI lower bound (20.52 %) clears the threshold by 0.5 pp; a larger σ could widen it below 20 %. **The T2 verdict is the most fragile number in the project.** |
| S2 | **R = 30 draws**, bootstrap B = 10,000, `default_rng(12345)` re-seeded per call (D-066). | — | All CIs computed by the single `analysis/stats.py`; n < 10 takes the wider of bootstrap and t; constant samples are labelled "degenerate" rather than hidden. | 30 draws is adequate for a paired difference, thin for a tail. |
| S3 | **SA seeds are collapsed to their median before a draw is formed** (D-068), so seed variation is not propagated into the reported CIs. | Slightly **narrows** SA's intervals. | Deliberate and documented: the replication unit is the draw, not the seed. | SA's true variability is larger than its plotted band; the ablations report it separately. |
| S4 | **Multiple comparisons.** Three topologies × three hypotheses, no family-wise correction. | Makes an isolated "supported" more likely by chance. | Verdicts are reported per topology and the overall rule is conjunctive (05 §4.1), which is conservative; T2's Wilcoxon p = 0.015 would not survive a strict Bonferroni at 0.05/9 = 0.0056. | **Stated explicitly wherever T2 is quoted.** |
| S5 | **H2's two clauses use different instance counts** (25 gap instances, 6 timing instances, D-077). | The speed-up CI is wide ([0.21, 1.04]×) because n = 6. | Both counts are printed in T-H2; the clause is refuted by a margin of an order of magnitude, so n does not change the verdict. | A larger timing grid would tighten, not move, the interval. |
| S6 | **Decision rules were fixed before the verdicts were computed** — but plan-v1 point estimates had already been seen when 05 §4 was adopted (D-063, D-065). | Honesty risk, not a bias in the data. | Recorded openly in D-063 and D-065; the v1 verdicts are marked provisional and the thresholds themselves come from `00_PROJECT_BRIEF.md §4` and were never changed (D-041, D-081). | A reviewer may still regard the interval rules as chosen with partial knowledge of the outcome. That disclosure is deliberate. |
| S7 | **Proportions use Wilson intervals** (crossover rate 0/30 → [0.00, 11.35] %). | — | Required by 05 §5 and implemented in `analysis/stats.py::wilson`. | With 30 draws, a crossover occurring in up to ~11 % of cases could not have been detected. |

## What would most change these conclusions

1. A constrained experiment (latency/SLO/residency) — E5 — where colocation is forbidden.
2. A topology whose components have different own-cost minimisers — E6 — which is the only way H3
   could be tested rather than structurally excluded.
3. A second price snapshot at a later date — I5 — given how price-fragile the T2 result is (F7).

## Mapping: every recorded waiver and limitation appears above

Modules closed with a waiver: **M04 — DONE_WITH_WAIVER** (GCP public pages instead of the Billing
API) → I3. Every decision cited in an AUDIT_LOG "Waivers / limitations" section:

| Decision | Subject | Covered by |
|---|---|---|
| D-003 | Pricing basis: list prices, one shape family | C1, I5 |
| D-007 | Egress tiering flattened | C2, I2 |
| D-009 | Repository root is `p5-egress-placement/` | process only — no validity threat |
| D-010 | Native Windows Python instead of WSL2 Ubuntu | process only; CI re-runs the suite on ubuntu-latest, which is the mitigation |
| D-011 | Git borrowed from GitHub Desktop | process only (tracked as H-10) |
| D-013 | Two seed rows dropped from the gap table | related-work scope, see `docs/review1/gap_table.md`; narrows the novelty claim, not a result |
| D-014 | Seed limitation cells corrected after full-text check | as D-013 |
| D-015 | Negative claims rest on abstract + keyword search | as D-013 — residual risk: a prior system may price egress in a way we did not find |
| D-016 | Bot-blocked DOI verified via Crossref | as D-013 |
| D-017 | Ext location set (4 extra regions per provider) | E4 |
| D-018 | Azure base internet rate (~9 % above ISP-routed option) | C2, I2 |
| D-026 | GCP source = public pricing pages | I3 (and the M04 waiver) |
| D-027 | N2 core/RAM rates fitted; GiB→GB | I3 |
| D-028 | GCP egress priced by destination group | I3 |
| D-034 | Azure R2 by continent pair | I2 |
| D-037 | Measurement run protocol | C3, E3 |
| D-038 | T1 built from the measured summary | C3, E3 |
| D-039 | B1/B2 tie-breaking | **I1** |
| D-040 | Definition of `egress_share` | C5 |
| D-041 | How the frozen hypotheses are stated and tested | S6 |
| D-043 | Runtime outlier kept, medians used | I9 |
| D-044 | Greedy order and tie-break rules | I1, I6 |
| D-045 | Greedy's T1/T3 gap comes from the tie-break | I1, I6 |
| D-048 | `load_instance` accepts provider pins | E5, E6 (the untested capability) |
| D-049 | `b2_best` skips infeasible providers | E5 |
| D-050 | Synthetic generator model | E1 |
| D-053 | M14 launch mode; parallel-tab contention | I7 |
| D-060 | Why H3 cannot hold in this snapshot | **E6** |
| D-065 | Plan-v1 M16 reused; v1 verdicts provisional | S6 |
| D-068 | A draw is the replication unit; SA seeds collapse | S3 |
| D-070 | CBC hangs: watchdog + retry, no data change | I8 |
