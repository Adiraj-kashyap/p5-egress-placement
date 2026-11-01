"""Generate fake snapshots so the cost model can be tested without network access."""
import json, random
from pathlib import Path
from pricing.common import LOCATIONS, SNAPSHOT_DIR
random.seed(7)
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def w(name, rows):
    (SNAPSHOT_DIR/f"{name}.json").write_text(json.dumps(
        {"snapshot_date":"fixture","pulled_at_utc":"fixture","row_count":len(rows),
         "meta":{"FIXTURE":True},"rows":rows}, indent=1))

aws=[]
for r in LOCATIONS["aws"]:
    for t,v,m in [("m5.large",2,8),("m5.xlarge",4,16),("m5.2xlarge",8,32),("m5.4xlarge",16,64)]:
        aws.append({"provider":"aws","region":r,"instance_type":t,"vcpu":str(v),
                    "memory":f"{m} GiB","usd_per_hour":round(0.048*v*random.uniform(.9,1.2),5),
                    "sku":f"SKU{t}{r}"})
w("aws_compute",aws)
w("aws_egress",[{"provider":"aws","from_location":r,"to_location":"External",
  "from_type":"AWS Region","to_type":"External","transfer_type":"AWS Outbound",
  "tier_begin_gb":"0","tier_end_gb":"10240","usd_per_gb":0.09,"sku":f"DT{r}"} for r in LOCATIONS["aws"]])

az=[]
for r in LOCATIONS["azure"]:
    for t,v,m in [("Standard_D2s_v5",2,8),("Standard_D4s_v5",4,16),("Standard_D8s_v5",8,32),("Standard_D16s_v5",16,64)]:
        az.append({"provider":"azure","region":r,"instance_type":t,"vcpu":str(v),
                   "memory":f"{m} GiB","usd_per_hour":round(0.046*v*random.uniform(.9,1.2),5),
                   "product_name":"Dsv5 Series","meter_id":f"M{t}{r}"})
w("azure_compute",az)
w("azure_egress",[{"provider":"azure","region":r,"meter_name":"Internet Egress",
  "tier_min_gb":0,"usd_per_gb":0.087,"meter_id":f"E{r}"} for r in LOCATIONS["azure"]])

gcp=[]
for r in LOCATIONS["gcp"]:
    gcp.append({"provider":"gcp","region":r,"resource_group":"CPU","description":"N2 Instance Core",
                "usd_per_unit_hour":round(0.031*random.uniform(.9,1.2),6),"usage_unit":"h","sku_id":f"C{r}"})
    gcp.append({"provider":"gcp","region":r,"resource_group":"RAM","description":"N2 Instance Ram",
                "usd_per_unit_hour":round(0.0042*random.uniform(.9,1.2),6),"usage_unit":"GiBy.h","sku_id":f"R{r}"})
w("gcp_compute",gcp)
w("gcp_egress",[{"provider":"gcp","description":"Network Internet Egress from Americas to Americas",
  "resource_group":"N/A","service_regions":["global"],"usd_per_gb":0.12,"sku_id":"GI","kind":"internet"}])
print("fixtures written to", SNAPSHOT_DIR)
