# M07 testbed: measured traffic for T1

The T1 three-tier application (`web` -> `api` -> `cache` (redis) / `db` (postgres)) runs on a
single-node kind cluster on the laptop. locust drives a fixed load, and every directed edge's
bytes are counted, so `topologies/t1_three_tier.json` holds measured volumes, not estimates.
No cloud resource is involved.

## Reproduce (PowerShell, from the repo root, Docker Desktop running)

```powershell
$env:PATH = "$PWD\.tools\bin;$env:PATH"; $env:KUBECONFIG = "$PWD\.tools\kube\config"
cd testbed/app; docker build -f web/Dockerfile -t p5-web:m07 .; docker build -f api/Dockerfile -t p5-api:m07 .; cd ../..
kind create cluster --name p5 --config testbed/k8s/kind.yaml; kind load docker-image p5-web:m07 p5-api:m07 --name p5
kubectl apply -f testbed/k8s/00-namespace.yaml; kubectl apply -f testbed/k8s/; kubectl -n p5 wait --for=condition=complete job/seed-db --timeout=300s
1..3 | % { .\.venv\Scripts\python.exe -m testbed.measure.run_measurement --runs 1 --first-run $_ --duration 600 }; .\.venv\Scripts\python.exe -m testbed.measure.summarize; .\.venv\Scripts\python.exe -m topologies.build
```

Tear down when finished: `kind delete cluster --name p5`.

On bash the commands are the same apart from the `$env:` lines (use `export`) and the loop
(`for k in 1 2 3; do ...; done`).

## What is measured

- **Application layer, per directed edge.** `app/common/counting.py` wraps the sockets web uses
  to call api and the sockets api uses for redis and postgres, so outbound edges are exact
  TCP-payload bytes (HTTP, RESP and the postgres wire protocol, framing included). Inbound
  HTTP (users -> web, web -> api at api) is counted by an ASGI middleware. Both sides of the
  web <-> api edge are counted independently and must agree (`api_side_bytes` in `runs.csv`).
- **Interface cross-check.** `/sys/class/net/eth0/statistics/{rx,tx}_bytes` in each pod
  before and after every run. `summary_interface.csv` reports app bytes / interface bytes per
  pod (the rest is IP/TCP/Ethernet headers, ACKs, probes and DNS).
- **Load.** locust, 20 users, spawn rate 5/s, 10 minutes per run, 3 runs with seeds 7, 8, 9;
  task mix browse 6 / product detail 3 / order (write) 1, with popularity skew
  (`load/locustfile.py`). Traffic enters through NodePort 30080 so it crosses web's eth0.
  Every run starts with zeroed counters and a flushed redis (cold cache).
- **Normalisation.** bytes per served web request = edge bytes / requests counted by web.
  `topologies/build.py` multiplies these by the stated production rate (50 requests/s,
  03 §S8) and 2,592,000 s/month. To rescale, change `T1_RATE` and re-run the builder.

Files: `measurements/runs.csv` (8 edge rows per run), `measurements/runs_interface.csv`
(4 pod rows per run), `measurements/summary.csv` (mean, sd, CV, min, max bytes/request per
edge), `measurements/summary_interface.csv`. Console logs: `evidence/logs/M07_measurement.txt`.

## Limitations

- **Payload vs wire bytes.** Cloud providers bill IP-level bytes. The volumes use TCP-payload
  bytes, so they understate billed egress by the protocol overhead shown in
  `summary_interface.csv` (app/interface ratio below 1).
- **Synthetic workload.** The catalogue (50,000 products), the page sizes, the 6/3/1 task mix,
  the popularity skew and the 60 s cache TTL are chosen, not taken from a production trace.
  Cache-related edges (api <-> cache, api <-> db) depend on the hit ratio, which depends on
  these choices and on run length (each run starts cold).
- **One operating point.** Bytes per request are measured at 20 users on one laptop and
  assumed to scale linearly to 50 requests/s. Per-request sizes do not depend on load, but
  the cache hit ratio does, somewhat.
- **Scope.** Single node, so no real network between components; only byte counts are used,
  not latency. T2 and T3 volumes remain stated estimates (`topologies/README.md`).
