"""The frozen hypothesis thresholds of `docs/methodology/project_brief.md §4` (integrity rule I5).

They are copied here as constants and are never read from, or tuned on, results. They live
in a module of their own so that both `analysis.verdicts` (which applies the 05 §4 rules)
and `analysis.tables` (which prints the threshold beside the measurement) can state the same
number without one importing the other. `tests/test_analysis.py` re-reads the brief and
fails if any of these drifts from it.
"""
from __future__ import annotations

H1_MIN_REDUCTION = 0.20      # H1: ILP reduces total monthly cost by >= 20% vs B1
H2_MAX_GAP = 0.05            # H2: SA within 5% of the CBC optimum (median over seeds)
H2_MIN_SPEEDUP = 10          # H2: ... while reducing wall-clock time by >= 10x
H3_RANGE = (0.01, 100)       # H3: swept range of traffic scale factors, 10^-2 to 10^2
H3_SUPPORT_RATE = 0.80       # 05 §4.3: SUPPORTED needs a crossover in >= 80% of draws
H3_REFUTE_RATE = 0.20        # 05 §4.3: REFUTED if it appears in <= 20% of draws
MIN_QUALIFYING_INSTANCES = 3  # 05 §4.2: fewer than this and H2 is INCONCLUSIVE by rule
