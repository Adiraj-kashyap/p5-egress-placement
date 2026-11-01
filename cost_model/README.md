# Cost model (Objective O1)

Built by `python -m pricing.build_cost_model` and checked by `python -m pricing.validate_cost_model`
from one dated snapshot (`snapshots/<date>/`, currently **2026-09-21**, set with
`P5_SNAPSHOT_DATE`). Outputs live in `cost_model/<date>/`: `compute.csv`, `storage.csv`,
`egress.csv`, `internet.csv` and `validation.md`. Nothing here is edited by hand.

## Location set

24 locations: 8 regions per provider (the `ext` set in `pricing/common.py`), covering North
America, Europe, Asia and South America on every provider. A location id is `provider:region`.
The 12-location `core` set is a subset.

## Compute

Four shapes, the same general-purpose Intel family class on every provider, on-demand Linux:

| Shape | vCPU / RAM (GiB) | AWS m5 | Azure Dsv5 | GCP N2 |
|---|---|---|---|---|
| small | 2 / 8 | m5.large | Standard_D2s_v5 | n2-standard-2 |
| medium | 4 / 16 | m5.xlarge | Standard_D4s_v5 | n2-standard-4 |
| large | 8 / 32 | m5.2xlarge | Standard_D8s_v5 | n2-standard-8 |
| xlarge | 16 / 64 | m5.4xlarge | Standard_D16s_v5 | n2-standard-16 |

AWS and Azure prices are whole-instance SKUs. GCP prices are composed as
`vCPU × core rate + GiB × RAM rate`, with the N2 rates fitted exactly (residual 0) from the
public machine-type prices. Monthly price = hourly × 730.

## Egress rules (every cell of the 24 × 24 directed matrix)

- **R1** same provider, same region → $0/GB. Traffic is assumed to stay in one zone; cross-zone
  charges are ignored.
- **R2** same provider, different region → that provider's inter-region rate for the pair:
  AWS from the per-pair SKU (sender side); Azure from the sender's intra-continent meter when both
  regions are on the same continent, otherwise the sender continent's intercontinental meter
  (e.g. North America/Europe to any other continent $0.05, South America $0.16); GCP from the
  Premium Tier group matrix (NA–NA $0.0186/GB, NA–EU $0.0466/GB, anything involving South
  America $0.1304/GB).
- **R3** different provider → the **sender's** internet egress rate from the sender region.
  AWS and Azure do not price by destination. GCP does, so the receiver's continent picks the
  GCP destination group (NA, Europe, Asia excl. Korea/Indonesia, or the group that contains
  South America).
- **R4** ingress → $0 on all three providers, so it has no column.

The matrix is directed: `egress[a][b]` and `egress[b][a]` differ whenever the two senders'
rates differ. A request and its response are two separate edges.

Every cell records its `rule` and its `source` (SKU id, meter id or pricing-page anchor).
When a price cannot be resolved, a continent-pair rate is used and the source is marked
`fallback:<reason>`. **In the 2026-09-21 build, 0 of 168 R2 cells use a fallback**, and R1/R3
never need one.

## Internet egress (`internet.csv`)

Traffic to end users. Rate = the sender region's internet rate. AWS and Azure have one rate per
region; for GCP, the destination group is the sender's own continent (users are assumed to be
near the region they are served from).

## Object storage (`storage.csv`)

Standard class, first tier: AWS S3 Standard, Azure Blob Hot LRS, GCP Cloud Storage Standard
(regional), in USD per GB-month.

## Flattened tiers and units

- Every tiered price is flattened to its **first paid tier**, the lowest tier start with a price
  above 0. For AWS that is the 0 GB tier. For Azure it is the 100 GB tier (the first 100 GB are
  free). For some GCP pairs it starts at 1 GiB. Volume discounts at higher tiers and the free
  allowances are not modelled. This slightly overstates cost for very small and very large
  volumes; M15 tests how sensitive the results are to this.
- Volumes and prices are per GB (10^9 bytes). GCP's per-GiB page prices are converted with
  ÷ 1.073741824. AWS and Azure prices are used as quoted, with their unit labelled "GB".

## Declared limitations

- GCP prices come from the public pricing pages, not the Cloud Billing API (no API key; D-026).
- Azure internet egress uses the default Microsoft-network routing (MGN), which is about 9% more
  than the ISP-routed option (D-018).
- AWS uses m5 rather than the newer m6i (D-024).
- On-demand list prices only: no committed-use, reserved or spot discounts.
