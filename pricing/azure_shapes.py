"""
Azure VM shapes used by the cost model: armSkuName -> (vcpu, ram_gb).

The Retail Prices API does not return vCPU or RAM, so they come from this table.
Family: Dsv5 (general purpose, Linux, 4 GiB per vCPU), per D-003.
Source (fetched 2026-09-21, HTTP 200, sizes confirmed on the page):
  https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dsv5-series

The four project shapes (03_SKILLS.md S5) map to: small D2s, medium D4s, large D8s, xlarge D16s.
"""

DSV5_SOURCE_URL = (
    "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dsv5-series"
)

# armSkuName -> (vcpu, ram_gb)
AZURE_SHAPES = {
    "Standard_D2s_v5": (2, 8),
    "Standard_D4s_v5": (4, 16),
    "Standard_D8s_v5": (8, 32),
    "Standard_D16s_v5": (16, 64),
}

# project shape name -> armSkuName
SHAPE_TO_SKU = {
    "small": "Standard_D2s_v5",
    "medium": "Standard_D4s_v5",
    "large": "Standard_D8s_v5",
    "xlarge": "Standard_D16s_v5",
}
