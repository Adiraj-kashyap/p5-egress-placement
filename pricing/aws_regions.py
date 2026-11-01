"""
AWS region code <-> Price List location name, for the `ext` AWS regions (D-017/D-018).

The Price List files name a region in three different ways: the EC2 offer uses a `Location`
column ("US East (N. Virginia)"), the data-transfer and S3 offers add `From/To Region Code`
columns, and the region indexes are keyed by region code. The pull keys everything on the
region code and uses these names only to cross-check the `Location` text it reads, so a
renamed location shows up as a warning instead of silently dropping rows.
"""
from pricing.common import LOCATIONS_EXT

AWS_LOCATION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "eu-west-1": "EU (Ireland)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "us-west-2": "US West (Oregon)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "sa-east-1": "South America (Sao Paulo)",
}
LOCATION_TO_REGION = {name: code for code, name in AWS_LOCATION_NAMES.items()}

assert set(AWS_LOCATION_NAMES) == set(LOCATIONS_EXT["aws"]), "aws_regions.py out of sync with LOCATIONS_EXT"
