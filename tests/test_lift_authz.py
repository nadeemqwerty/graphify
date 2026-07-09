"""Regression test for the §11.6 authz lift eval (eval/lift_authz/run_lift_eval.py).

This locks in the four claims the lift eval is designed to prove:

  1. The REAL graphify extractor answers "does this controller guard EVERY
     endpoint?" correctly on all four fixtures (graph_accuracy == 1.0).
  2. The naive `grep @PreAuthorize` baseline is strictly worse
     (naive_accuracy == 0.75) — it false-positives on the differentiator.
  3. The lift is positive (graph beats naive), so the graph adds real signal.
  4. The mutation test is non-tautological: strip the framework-boundary edges
     (class_authz_guarded + authz_guard) and accuracy DROPS below the graph's,
     proving the graph's win comes from those facts, not from the harness.

The eval is loaded by FILE PATH via importlib so that run_lift_eval.py's own
worktree-root ``sys.path`` insertion runs first — otherwise an editable pip
install of ``graphify`` (pointing at a different clone) would shadow the local
worktree extractor and the framework-boundary facts would be missing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# eval/lift_authz/run_lift_eval.py, relative to this test file (tests/).
_RUNNER = Path(__file__).resolve().parents[1] / "eval" / "lift_authz" / "run_lift_eval.py"


def _load_eval():
    assert _RUNNER.exists(), f"lift eval runner not found: {_RUNNER}"
    spec = importlib.util.spec_from_file_location("lift_authz_run_eval", _RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # runs the worktree-root sys.path insertion
    return module


def test_lift_eval_passes_and_numbers_are_exact():
    mod = _load_eval()
    result = mod.evaluate()

    # (1) real extractor is perfect on the four fixtures
    assert result["graph_accuracy"] == 1.0, result

    # (2) naive grep baseline is strictly worse (3/4)
    assert result["naive_accuracy"] == 0.75, result

    # (3) positive lift => graph adds real signal over the dumb baseline
    assert result["lift"] > 0, result
    assert result["graph_accuracy"] > result["naive_accuracy"], result

    # (4) non-tautological: ablating the framework-boundary edges hurts accuracy
    assert result["mutated_graph_accuracy"] < result["graph_accuracy"], result
    assert result["non_tautological"] is True, result

    # overall gate
    assert result["passed"] is True, result


def test_differentiator_fixture_separates_graph_from_naive():
    """MethodGuardedController is the whole point: one guarded endpoint + one
    open endpoint. The graph gets it right (False), the naive grep gets it
    wrong (True, because a real @PreAuthorize token is present)."""
    mod = _load_eval()
    row = mod.evaluate()["per_class"]["MethodGuardedController"]

    assert row["truth"] is False
    assert row["graph"] is False and row["graph_correct"] is True
    assert row["naive"] is True and row["naive_correct"] is False


def test_open_controller_is_a_clean_negative_control():
    """OpenController has NO authorization anywhere (and, post-fix, no literal
    ``@PreAuthorize`` token in its comments), so BOTH graph and naive must
    correctly report it as not-fully-guarded."""
    mod = _load_eval()
    row = mod.evaluate()["per_class"]["OpenController"]

    assert row["truth"] is False
    assert row["graph"] is False and row["graph_correct"] is True
    assert row["naive"] is False and row["naive_correct"] is True
