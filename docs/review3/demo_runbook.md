# Live demo runbook — P5 egress-aware placement

Everything here is for the person at the keyboard on the day. The app is
`demo/app.py` (Streamlit, local, offline): an 11-chapter guided walkthrough (M22, MIG-003)
whose Next links carry a viewer from the problem to the conclusion. The chapter map and the
self-guided reading order are in [`walkthrough.md`](walkthrough.md); this file is the
presenter's script. Nothing in the demo touches the network, so a
dead wifi connection cannot break it.

**One thing to know before reading the script:** there is **no crossover** in this snapshot.
The optimum uses a single provider at every traffic scale from s = 0.01 to s = 100, in all 30
uncertainty draws (H3 REFUTED, Wilson CI [0.00, 11.35] %). The reason is structural:
`azure:eastus` is the cheapest location for *every* cost component on its own, so there is no
multi-provider region for the optimum to leave (D-060, D-058). The demo shows this as a
finding, not as a failure — it is a result with a mechanism behind it. See D-085.

---

## T–30 minutes

1. Laptop **on the charger**. Notifications off (Windows: Focus assist → Alarms only).
2. Docker Desktop running; wait for the whale icon to go steady.
3. Set the tool paths in the shell you will use (from the repo root):
   ```
   $env:PATH = "$PWD\.tools\bin;$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
   $env:KUBECONFIG = "$PWD\.tools\kube\config"
   ```
4. Cluster up. If `kubectl get nodes` fails, recreate it (about 3 minutes):
   ```
   kind create cluster --name p5 --config testbed/k8s/kind.yaml
   kind load docker-image p5-web:m07 p5-api:m07 --name p5
   kubectl apply -f testbed/k8s/00-namespace.yaml
   kubectl apply -f testbed/k8s/
   ```
   Wait for four pods Running: `kubectl -n p5 get pods -w`.
5. **Preflight — every line must say OK:**
   ```
   .\.venv\Scripts\python.exe -m demo.preflight
   ```
   If the cluster is not up, `--offline` must still be clean; then plan to use the cached
   measurement in chapter 9 and say so out loud.
6. Start the app and leave it running:
   ```
   .\.venv\Scripts\streamlit.exe run demo/app.py
   ```
7. Browser zoom **125 %**, window maximised, one tab only. Click through every chapter once
   (the first visit to each page is the slow one) and press **Solve now** in chapter 4 with
   T1, so no click on stage is a cold start. If you edit any code, restart Streamlit: a
   running server keeps the old `demo/*.py` modules in memory.

---

## The 5-minute script

Timings are cumulative. What to click is in `code`, what to say is in plain text. Open on
**Start here** while you say the first line: the verdict chips are on screen behind you.

### 0:00 — the problem, one sentence
> A multi-component service can be spread across AWS, Azure and GCP. Compute is cheapest in
> one place and data transfer is cheapest in another, and every gigabyte that crosses a
> provider boundary is billed. We ask: where should each component go, and how much does
> ignoring egress actually cost?

### 0:30 — T1 at s = 1: the exact optimum against the egress-blind baseline
`4 · Solvers, live` · workload **T1 three-tier (measured)**, locations **core**,
s = **1** · methods ILP, greedy+1-opt, B1, B2-best · **Solve now**. (If asked where the
volumes come from, chapter 2 shows the graph and the measured bytes.)

> These volumes are measured, not assumed — three ten-minute load runs on a local Kubernetes
> cluster, per-edge byte counters, coefficient of variation under 1 %.

Point at the metric row: ILP **$481.18/month**, solved in well under a second and *proven
optimal* by CBC. B1, the egress-blind baseline, is **$497.58** — **3.41 % more**. Point at
the placement table: every component lands on `azure:eastus`, so the optimum pays **zero**
inter-component egress.

> On this topology the penalty is small. That is itself a finding, and it is why the next
> one matters.

### 1:30 — T2: where ignoring egress does hurt
Same chapter: workload **T2 pipeline** · **Solve now**. Then `5 · H1 egress penalty`
for the interval against the red 20 % line.

ILP **$1,028.79**, B1 **$1,303.65** — **26.7 % more**. Over 30 uncertainty draws the mean
reduction is **22.55 %, 95 % CI [20.52, 24.59] %**, Wilcoxon p = 0.015.

> This is the one topology where our pre-registered 20 % hypothesis holds. We froze that
> threshold before we had any results and we are reporting it as it fell: **H1 is supported on
> T2 and refuted on T1 and T3**, so refuted overall. The margin on T2 is half a percentage
> point, and our sensitivity analysis says it would not survive a 25 % cut in egress prices.

### 2:30 — drag the traffic slider: the cost of being egress-blind explodes
`7 · H3 traffic sweep` · topology **T2**, the slider starts at s = **100** and solves on
the spot.

ILP is still **$1,028.79** on one provider. B1 is now **$28,511.82** — a **2,671 %** penalty.

> The optimum does not move, because it never crossed a provider boundary in the first place.
> The baseline is the thing that explodes: it split the components across providers to chase
> cheap compute, and at a hundred times the traffic it is paying for that split every month.

### 3:15 — the sweep charts: what the statistics say
Same chapter, scroll to the charts (or `8 · Why: ablation` if asked *why*).

> Every curve here is a mean over 30 uncertainty draws with a 95 % bootstrap confidence
> interval — no single runs anywhere in this project. The bottom panel is the honest one: the
> number of providers the optimum uses is flat at one across four orders of magnitude of
> traffic. We hypothesised a crossover and there is none, in zero of thirty draws. The reason
> is that one region happens to minimise every cost term at once in this price snapshot, so
> there is no multi-provider region to leave. That is a property of the prices, not of the
> method.

Your live solve is the black diamond on the cost-vs-scale chart.

### 4:00 — Live testbed: measure, then re-optimise
`9 · Live testbed` · **Check cluster** (four pods Running) · **Measure live**, 60 s.

> This is running a real load generator against a real Kubernetes cluster right now and
> counting the bytes on every edge.

When it finishes: per-edge bytes/request, then T1 re-priced from those fresh numbers, old
optimum beside new.

> The two optima agree to within a fraction of a percent, which is the point — the
> measurement is reproducible, so the cost model is standing on something solid.

*(If the cluster is down: press **Use cached measurement** and say "the cluster isn't up on
this machine, so this is the committed measurement from our three ten-minute runs" — the
re-optimisation beat still works.)*

### 4:45 — the conclusion, one sentence
> Egress-aware placement is worth between 2 and 27 % depending on the topology, the exact
> optimum is cheap enough to compute live, and on this price snapshot the answer is always a
> single provider — which is a more interesting result than the one we expected.

---

## Fallbacks

| What breaks | What to do |
|---|---|
| Cluster down, pods not Ready, kubectl missing | Chapter 9 → **Use cached measurement**. The app already falls back on its own and prints why; the button is there so you can do it deliberately. |
| Locust fails or serves 0 requests | Same fallback. The app never raises — it shows the reason and offers the cache. |
| Streamlit will not start | `python -m demo.preflight --offline` names the failing check. Last resort: read the numbers off `docs/report/verdicts.md` and `figures/R2-1_cost_vs_scale.png`. |
| Cache missing or stale | `python -m demo.build_cache` (under a second). |
| Laptop fails | Teammate's laptop, repo cloned and `python -m demo.preflight --offline` run clean **the day before**, not on the day. |
| Projector will not do the laptop resolution | Run at 1280×720, browser zoom 100 %, and use the sidebar collapse arrow to give the tables room. |
| A solve is slow on stage | The demo caps the ILP at 30 s and says whether it was proven optimal. T3 solves in about 0.15 s; anything slower means another process is eating the CPU — close it. |

---

## Likely examiner questions

**Why an ILP and not an MIQP?** The natural objective has a product of two placement
variables (traffic between component *a* at location *i* and *b* at *j*). We linearise it
with pair variables and the tight constraint set, which gives an LP relaxation strictly
inside the McCormick one, so CBC proves optimality at the root node on all three topologies.
Full argument in `docs/report/formulation.md`.

**Why these regions and providers?** Eight regions per provider on four continents (24
locations, the "ext" set; "core" is the 12-location subset used for most runs), chosen to
span continents so inter-region and intercontinental rates both appear. The choice is fixed
in `pricing/common.py` and is a stated external-validity threat.

**How were the prices obtained?** A dated snapshot, 2026-09-21, pulled from each provider's
public price list: the AWS bulk pricing CSVs per region, the Azure retail prices API, and for
GCP the public pricing pages (the calculator price list 404s, D-026). All three raw snapshots
are committed, and one script builds the unified cost model from them, with ten validation
checks. Nothing is typed by hand.

**How were the volumes measured?** T1 is measured: a four-service app on a local kind
cluster, per-edge byte counters in the application plus an eth0 cross-check, three
ten-minute locust runs, max coefficient of variation 0.87 %, converted to GB/month at a
stated 50 requests/s. T2 and T3 are stated volumes from published descriptions, and we carry
that difference into the uncertainty model — measured edges get a tighter distribution than
stated ones.

**What do the error bars mean?** 95 % percentile bootstrap confidence intervals, B = 10,000,
over 30 traffic draws per configuration. Every draw is paired across methods, so the
comparisons are paired and we use the Wilcoxon signed-rank test for the hypothesis decisions.
One module computes every mean and interval in the project, so no two figures can disagree.

**Why is the optimum always one provider — did the method fail?** No: it is what the prices
say. `azure:eastus` is simultaneously the cheapest for compute, for storage and for egress in
this snapshot, so the single-provider placement dominates and there is nothing for a
multi-provider solution to buy. Our ablation confirms the mechanism: removing the
egress-coupling term is the single largest component of the gain at all six (topology, scale)
points we decomposed.

**Is 30 seconds of load enough to trust?** For the demo, no — it is there to show the loop is
real. The reported numbers come from three ten-minute runs, and the reproducibility claim
rests on those, not on what happens on stage.

---

## After the demo

Record what actually happened in `docs/review3/demo_rehearsal.md` (H-16): total duration,
anything that stalled, anything an examiner asked that is not answered above.
