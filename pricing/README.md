# P5 — Phase 0/1/2: Environment, Pricing Pullers, Unified Cost Model

Covers Objective **O1** and the Review-1 **testbed evidence** component (3 marks).
Nothing here costs money. No cloud resource is ever provisioned; only price lists are read.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git init && git add -A && git commit -m "P5 phase 1"
python verify_env.py          # <-- SCREENSHOT THIS
```

`verify_env.py` prints Python, platform, git commit, PuLP version, available solvers,
then builds and solves a 3-component egress-coupled ILP. It must end in
`ENVIRONMENT OK`. This is testbed evidence artefact #1.

## Running the pullers

```bash
export GCP_API_KEY=...        # only GCP needs this
./run_all.sh
```

Keep the terminal output. `logs/pull_<date>.log` records every HTTP status code and
row count — this is testbed evidence artefact #2.

### Provider notes

| Provider | Auth | Endpoint | Gotcha |
|---|---|---|---|
| Azure | none | `prices.azure.com/api/retail/prices` | 100 items/page, follow `NextPageLink`. Filter out Spot, Low Priority and Windows SKUs or your compute prices will be wrong. |
| AWS | none | `pricing.us-east-1.amazonaws.com/offers/v1.0/...` | The global EC2 index is several GB. We stream the per-region `index.csv` instead and filter rows as they arrive. The first 5 lines are metadata, the header is line 6. |
| GCP | free API key | `cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus` | **GCP does not price whole instances.** vCPU and RAM are separate SKUs, so an instance cost must be composed as `vcpu × cpu_rate + ram_gb × ram_rate`. AWS and Azure quote one per-instance rate. Comparing them without normalising is the single easiest way to get wrong answers. |

If the GCP key is blocked, fall back to transcribing
`cloud.google.com/vpc/network-pricing` into a dated CSV and record it as a limitation.
Do not let GCP block the rest of the pipeline.

## Outputs

```
snapshots/<date>/{aws,azure,gcp}_{compute,egress}.json   raw, with provenance metadata
cost_model/<date>/compute.csv                            48 rows: 12 locations x 4 shapes
cost_model/<date>/egress.csv                             144 rows: full 12x12 matrix
logs/pull_<date>.log                                     every HTTP call
```

**Commit the snapshots.** Your publication rationale is that reviewers can verify
your numbers from public pricing data. That only holds if the exact JSON you used
is in the repository with a date on it.

## The egress rules, stated explicitly

Put these in your report. They are the modelling assumptions a reviewer will attack.

| Rule | Condition | Rate |
|---|---|---|
| R1 | same provider, same region | $0.00/GB |
| R2 | same provider, different region | that provider's inter-region rate for the continent pair |
| R3 | different provider | the **source** provider's internet egress rate. Destination identity is irrelevant — leaving the network is leaving the network. |
| R4 | ingress | $0.00. All three providers bill egress only. |

Every cell in `egress.csv` carries a `rule` and a `source` column, so any number in
your results traces back to a line in a snapshot. Watch the log for
`FALLBACK internet rate used` — each occurrence is a cell you could not resolve from
a SKU and must declare as a limitation.

## Known simplifications (declare these)

1. **Tiered egress is flattened.** Egress is banded by monthly volume; we take the
   base tier. The true cost function is piecewise-linear. A full model needs binary
   tier-selection variables. State the traffic range where the base tier holds.
2. **Inter-region rates use published continent-pair values**, not per-SKU lookups,
   because the inter-region SKUs are named inconsistently across the three catalogs.
   This is the honest weak point of the cost model — say so before a reviewer does.
3. **Four shapes, four regions per provider.** Chosen to bound ILP size. The scaling
   experiment (Phase 6) varies this deliberately.
4. **Linux, on-demand, shared tenancy only.** No spot, no reserved, no Windows.

## `make_fixtures.py`

Generates synthetic snapshots so the cost model can be tested without network access.
**Never use fixture output for reported results.** Delete `snapshots/<date>/` and
re-run the real pullers before generating any number that goes in the report.

## Next

Phase 3 (topologies with measured traffic), Phase 4 (baselines), Phase 5 (ILP).
