"""Environment acceptance tests for M00: solver present, and it actually solves."""
import sys
from pathlib import Path

import pulp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify_env import run_smoke_model  # noqa: E402


def test_pulp_imports_with_a_version() -> None:
    """pulp must import and report a version string."""
    assert pulp.__version__


def test_cbc_solver_available() -> None:
    """CBC must be listed among the solvers pulp can actually run."""
    assert "PULP_CBC_CMD" in pulp.listSolvers(onlyAvailable=True)


@pytest.fixture(scope="module")
def smoke() -> dict:
    """Run the M00 smoke model once and share the result across tests."""
    return run_smoke_model()


def test_smoke_model_is_optimal(smoke: dict) -> None:
    """The rigged 3x3 placement ILP must solve to proven optimality."""
    assert smoke["status"] == "Optimal"


def test_egress_blind_placement_is_penalised(smoke: dict) -> None:
    """Ignoring egress must cost strictly more than the egress-aware optimum.

    The constants are rigged so the cheapest-compute answer is wrong; a
    non-positive penalty means the model or the constants have drifted.
    """
    assert smoke["objective"] > 0
    assert smoke["blind_cost"] > smoke["objective"]
    assert smoke["penalty_pct"] > 0
