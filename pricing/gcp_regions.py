"""GCP region -> pricing group tables used by pull_gcp.py and gcp_pages.py.

Two groupings exist and they are not the same thing:

* `PRICING_GROUP` - the three continent groups used in Cloud Billing Catalog SKU
  descriptions ("... from Americas to EMEA"): Americas / EMEA / APAC (03_SKILLS S3).
* `INTER_REGION_GROUP` - the source/destination rows of the "Inter-region data transfer"
  matrix on cloud.google.com/vpc/network-pricing (North America, Europe, Asia, ...).
  Footnote markers ("Asia3") are stripped before matching.

Every region in LOCATIONS_EXT["gcp"] must appear in both tables (tested).
"""
from pricing.common import LOCATIONS_EXT

PRICING_GROUP = {
    "us-east4": "Americas", "us-west1": "Americas", "southamerica-east1": "Americas",
    "europe-west1": "EMEA", "europe-west3": "EMEA",
    "asia-south1": "APAC", "asia-southeast1": "APAC", "asia-northeast1": "APAC",
}

INTER_REGION_GROUP = {
    "us-east4": "North America", "us-west1": "North America",
    "europe-west1": "Europe", "europe-west3": "Europe",
    "asia-south1": "Asia", "asia-southeast1": "Asia", "asia-northeast1": "Asia",
    "southamerica-east1": "South America",
}

CONTINENT_GROUPS = ("Americas", "EMEA", "APAC")


def pricing_group(region: str) -> str:
    """Return the SKU continent group (Americas/EMEA/APAC) of a GCP region.

    Raises KeyError for a region outside the ext location set, so an unmapped region fails
    loudly instead of being priced with a guessed group.
    """
    return PRICING_GROUP[region]


def inter_region_group(region: str) -> str:
    """Return the network-pricing-page matrix group (e.g. 'North America') of a GCP region.

    Raises KeyError for an unmapped region.
    """
    return INTER_REGION_GROUP[region]


def unmapped_regions() -> list:
    """Return ext GCP regions missing from either mapping (empty list when complete)."""
    return [r for r in LOCATIONS_EXT["gcp"] if r not in PRICING_GROUP or r not in INTER_REGION_GROUP]
