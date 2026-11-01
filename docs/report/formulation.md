# Exact formulation of egress-aware placement (Objective O2)

Implementation: `placement/ilp.py` (model), `placement/cbc_log.py` (solver-log parsing),
`placement/cost.py::evaluate` (the single cost function the ILP must reproduce).
Tests: `tests/test_ilp.py`. Results: `results/exact/runs.csv`. Decisions: D-004, D-005, D-006, D-042.

## 1. Sets

| Symbol | Meaning |
|---|---|
| $C$ | components of the application, $n = \lvert C\rvert$ |
| $L$ | candidate locations, each a `provider:region` pair (`core` set: 12, `ext` set: 24) |
| $A_c \subseteq L$ | allowed locations of component $c$ ($A_c = \{\ell_c\}$ if `pinned_to` = $\ell_c$, else $L$) |
| $E$ | directed traffic edges $(u, v)$, $u \ne v$ allowed or equal |
| $P$ | unordered component pairs $\{u, v\}$, $u \ne v$, joined by at least one edge in either direction |

## 2. Parameters

| Symbol | Unit | Meaning (source) |
|---|---|---|
| $k_{c\ell}$ | USD/month | compute of $c$'s fixed shape at $\ell$ (hourly × 730) plus its storage at $\ell$ (`cost_model/<date>/compute.csv`, `storage.csv`) |
| $w_{uv}$ | GB/month | traffic from $u$ to $v$ (topology JSON) |
| $p_{\ell m}$ | USD/GB | transfer price from location $\ell$ to $m$, paid by the sender; $p_{\ell\ell} = 0$ (`egress.csv`, D-005) |
| $q_c$ | GB/month | traffic from $c$ to end users (topology `internet_egress`) |
| $r_\ell$ | USD/GB | internet egress price at sender location $\ell$ (`internet.csv`) |

For a pair $\{u, v\} \in P$ (with $u$ before $v$ in topology order) the two directions are merged
into one coefficient:

$$W_{uv}(\ell, m) = w_{uv}\,p_{\ell m} + w_{vu}\,p_{m \ell}.$$

## 3. The problem

An assignment $a : C \to L$ with $a(c) \in A_c$ costs

$$\mathcal{C}(a) = \sum_{c} k_{c,a(c)} + \sum_{(u,v) \in E} w_{uv}\,p_{a(u),a(v)} + \sum_{c} q_c\,r_{a(c)} ,$$

which is exactly what `evaluate()` computes. The middle term couples the locations of pairs of
components; that coupling is the whole problem. Without it, each component could be placed
on its own.

## 4. Variables

- $x_{c\ell} \in \{0,1\}$ for $c \in C$, $\ell \in A_c$: component $c$ is placed at $\ell$.
- $y_{P\ell m} \ge 0$ (continuous) for $P = \{u,v\} \in P$, $\ell \in A_u$, $m \in A_v$: stands for the product $x_{u\ell}\,x_{vm}$.

## 5. Objective and constraints

$$
\min \;\; \sum_{c}\sum_{\ell \in A_c} \big(k_{c\ell} + q_c\,r_\ell + s_c\,p_{\ell\ell}\big)\,x_{c\ell}
\;+\; \sum_{\{u,v\} \in P}\;\sum_{\ell \in A_u}\sum_{m \in A_v} W_{uv}(\ell, m)\; y_{\{u,v\}\ell m}
$$

where $s_c = w_{cc}$ is self-loop traffic (0 in T1–T3; it costs $p_{\ell\ell} = 0$ but is kept for exactness).

$$
\begin{aligned}
&\textstyle\sum_{\ell \in A_c} x_{c\ell} = 1 && \forall c \in C &&\text{(each component placed once)}\\[2pt]
\textbf{tight:}\quad &\textstyle\sum_{m \in A_v} y_{\{u,v\}\ell m} = x_{u\ell} && \forall \{u,v\} \in P,\ \ell \in A_u &&\text{(row marginals)}\\
&\textstyle\sum_{\ell \in A_u} y_{\{u,v\}\ell m} = x_{vm} && \forall \{u,v\} \in P,\ m \in A_v &&\text{(column marginals)}\\[2pt]
\textbf{McCormick:}\quad & y_{\{u,v\}\ell m} \ge x_{u\ell} + x_{vm} - 1 && \forall \{u,v\} \in P,\ \ell \in A_u,\ m \in A_v &&\text{(ablation only)}
\end{aligned}
$$

Pins are imposed by the variable domain ($x_{c\ell}$ exists only for $\ell \in A_c$), not by extra rows.

## 6. Why the tight linearisation is exact

Fix a pair $\{u,v\}$ and any integer $x$ satisfying the assignment rows, with $a(u) = \ell^\*$
and $a(v) = m^\*$. Read $y_{\{u,v\}}$ as an $\lvert A_u\rvert \times \lvert A_v\rvert$ non-negative matrix.

1. Row $\ell \ne \ell^\*$ must sum to $x_{u\ell} = 0$. Its entries are non-negative, so all are 0.
2. Column $m \ne m^\*$ must sum to $x_{vm} = 0$, so it is 0 as well.
3. The only entry left is $y_{\ell^\* m^\*}$, and row $\ell^\*$ sums to $x_{u\ell^\*} = 1$, so $y_{\ell^\* m^\*} = 1$.

Hence $y_{\{u,v\}\ell m} = x_{u\ell}\,x_{vm}$ for **every** feasible integer $x$. The $y$ values are
forced by the constraints. The argument does not use the objective or the sign of $W$, so the
objective equals $\mathcal{C}(a)$ exactly and the model is a correct reformulation of the problem.
This holds even though $y$ is continuous.

**Why this is tighter than McCormick.** In the LP relaxation ($0 \le x \le 1$), the tight
constraints imply all McCormick inequalities. For any $\ell, m$:

$$x_{u\ell} = \sum_{m'} y_{\ell m'} = y_{\ell m} + \sum_{m' \ne m} y_{\ell m'} \le y_{\ell m} + \sum_{\ell'}\sum_{m' \ne m} y_{\ell' m'} = y_{\ell m} + (1 - x_{vm}),$$

which rearranges to $y_{\ell m} \ge x_{u\ell} + x_{vm} - 1$. Likewise $y_{\ell m} \le x_{u\ell}$ and
$y_{\ell m} \le x_{vm}$. So the tight relaxation's feasible set lies inside the McCormick one, and
its LP bound is at least as high. The reverse is false: with every $x = 1/\lvert L\rvert$, McCormick
allows $y \equiv 0$, which removes all transfer cost from the LP bound. The tight form is
the standard "assignment" or RLT linearisation of a quadratic semi-assignment problem.

**McCormick is exact only here.** With integer $x$, $y_{\ell m} \ge x_{u\ell} + x_{vm} - 1$
forces $y_{\ell^\* m^\*} \ge 1$ and allows $y = 0$ elsewhere. It is exact only because the
problem minimises and every $W_{uv}(\ell,m) \ge 0$ (prices and volumes are non-negative). The
upper bounds $y \le x$ are then redundant and are omitted. `build_model` refuses a negative
coefficient in the McCormick form (D-042).

## 7. Model size

With $\lvert P\rvert$ merged pairs (at most $\lvert E\rvert$, and exactly $\lvert E\rvert / 2$
when every edge has a reverse edge):

| | binaries | continuous | constraints |
|---|---|---|---|
| general | $\sum_c \lvert A_c\rvert$ | $\sum_{\{u,v\}} \lvert A_u\rvert\,\lvert A_v\rvert$ | tight: $n + \sum_{\{u,v\}} (\lvert A_u\rvert + \lvert A_v\rvert)$; McCormick: $n + \sum_{\{u,v\}} \lvert A_u\rvert\,\lvert A_v\rvert$ |
| no pins | $nL$ | $\lvert P\rvert L^2$ | tight: $n + 2\lvert P\rvert L$; McCormick: $n + \lvert P\rvert L^2$ |

Merging directions halves the continuous variables when edges come in pairs. Without merging
there would be $\lvert E\rvert L^2$ of them. `tests/test_ilp.py::test_model_size_formula`
checks the no-pin formulas against the built models.

Sizes on the `core` set ($L = 12$), from `results/exact/runs.csv` (`n_vars`, `n_constraints`):

| Instance | $n$ | $\lvert P\rvert$ | variables | tight constraints | McCormick constraints |
|---|---|---|---|---|---|
| T1 three-tier | 4 | 3 | 480 | 76 | 436 |
| T2 pipeline | 7 | 7 | 1,092 | 175 | 1,015 |
| T3 microservices | 11 | 15 | 2,292 | 371 | 2,171 |

## 8. Solving and certifying optimality

CBC (bundled with PuLP 3.3.2) is called with `threads=1` so that runtimes can be compared fairly.
The time limit is 600 s by default. PuLP reports `Optimal` even for a run that CBC stopped on the time limit.
A real 3 s run that stopped with a 289 % gap was still labelled `Optimal` by PuLP
(`tests/data/cbc_stopped_on_time.log`). Therefore `proven_optimal`, the best bound and the
gap are read from CBC's own `Result - …` summary in the log. Every solve's log is kept
(`results/exact/cbc/`). Correctness is checked three ways (`tests/test_ilp.py`):

- equal to brute-force enumeration on 20 seeded tiny instances (≤ 4 components, ≤ 4 locations,
  with pins, self-loops and two-way edges), both formulations;
- equal to brute force on T1 at real prices ($12^4 = 20{,}736$ assignments);
- the objective equals `evaluate()` on the returned assignment, on T1–T3 (integrity rule I8).
