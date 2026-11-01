#!/usr/bin/env bash
# Phase 1 + 2: pull all three price lists and build the unified cost model.
# Everything here is free. Only GCP needs a key (also free).
set -e
export P5_SNAPSHOT_DATE=${P5_SNAPSHOT_DATE:-$(date +%F)}
echo "=== snapshot date: $P5_SNAPSHOT_DATE ==="
python -m pricing.pull_azure          # no auth
python -m pricing.pull_aws            # no auth
python -m pricing.pull_gcp            # needs GCP_API_KEY
python -m pricing.build_cost_model
echo "=== done. commit snapshots/$P5_SNAPSHOT_DATE and logs/ ==="
