"""Regression tests for the deterministic, zero-AI comprehension eval harness.

The harness (eval/run_eval.py) is itself the code-comprehension gate for the
MVP, so these tests assert two things about it:

  1. Correctness — on the checked-in spring_mini fixtures + questions.json it
     answers EVERY question correctly (all_pass) with the expected graph shape.
  2. Determinism — two independent runs produce byte-identical results (no LLM,
     no ordering nondeterminism), which is the whole point of a regression gate.

The harness lives under eval/ (not an installed package), so we load it by path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

import run_eval  # noqa: E402  (path-injected above)


def test_harness_all_questions_pass():
    summary = run_eval.run()
    # every question answered correctly
    assert summary["all_pass"] is True, summary["results"]
    assert summary["passed"] == summary["total"]
    # the fixture corpus + question set are fixed ground truth anchors
    assert summary["total"] == 10
    assert summary["node_count"] == 21
    assert summary["edge_count"] == 30
    # no question silently skipped: each result carries a boolean pass verdict
    assert all(isinstance(x["pass"], bool) for x in summary["results"])
    assert {x["id"] for x in summary["results"]} == {q["id"] for q in _questions()}


def test_harness_is_deterministic():
    a = run_eval.run()
    b = run_eval.run()
    # full result payload must be byte-identical across independent runs
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_harness_main_exit_zero_on_green():
    # the CLI entrypoint returns 0 when everything passes (the CI gate contract)
    assert run_eval.main([]) == 0
    assert run_eval.main(["--json"]) == 0


def _questions() -> list[dict]:
    qpath = _EVAL_DIR / "questions.json"
    return json.loads(qpath.read_text(encoding="utf-8"))
