"""Opt-in MultiDiGraph build mode (blocker-1).

Covers build_from_json(..., multigraph=True):
  * default path stays byte-compatible (parallel edges collapse; type unchanged);
  * multigraph path preserves parallel edges keyed relation:source_file:source_location;
  * the reverse-direction dedup guard does NOT eat parallel edges under multigraph;
  * require_multigraph_capabilities() gates the multigraph build;
  * diagnose_extraction reports 0 collapsed edges for a graph built with multigraph.
"""
from __future__ import annotations

import networkx as nx
import pytest

from graphify.build import build, build_from_json


def _parallel_extraction() -> dict:
    """Two edges a->b that differ only by relation+line: a `calls` and an `imports`."""
    return {
        "nodes": [
            {"id": "a", "label": "a", "source_file": "a.py"},
            {"id": "b", "label": "b", "source_file": "a.py"},
        ],
        "edges": [
            {"source": "a", "target": "b", "relation": "calls",
             "source_file": "a.py", "source_location": "L1"},
            {"source": "a", "target": "b", "relation": "imports",
             "source_file": "a.py", "source_location": "L2"},
        ],
    }


def test_default_collapses_parallel_edges():
    """Baseline preserved: without the flag, parallel edges still collapse."""
    g = build_from_json(_parallel_extraction(), directed=True)
    assert not g.is_multigraph()
    assert g.number_of_edges() == 1  # the two edges coalesce into one


def test_multigraph_preserves_parallel_edges_with_upstream_keys():
    """multigraph=True keeps both edges, keyed relation:source_file:source_location."""
    g = build_from_json(_parallel_extraction(), multigraph=True)
    assert isinstance(g, nx.MultiDiGraph)
    assert g.is_multigraph() and g.is_directed()
    assert g.number_of_edges() == 2
    keys = sorted(k for _u, _v, k in g.edges(keys=True))
    assert keys == ["calls:a.py:L1", "imports:a.py:L2"]


def test_multigraph_keeps_reverse_direction_edges():
    """The `if not G.is_directed()` reverse-dedup guard is skipped for MultiDiGraph,
    so a->b and b->a both survive (they collapse under undirected default)."""
    ex = {
        "nodes": [
            {"id": "a", "label": "a", "source_file": "a.py"},
            {"id": "b", "label": "b", "source_file": "a.py"},
        ],
        "edges": [
            {"source": "a", "target": "b", "relation": "calls",
             "source_file": "a.py", "source_location": "L1"},
            {"source": "b", "target": "a", "relation": "calls",
             "source_file": "a.py", "source_location": "L3"},
        ],
    }
    g = build_from_json(ex, multigraph=True)
    assert g.number_of_edges() == 2
    assert g.has_edge("a", "b") and g.has_edge("b", "a")


def test_same_endpoint_same_key_coalesces():
    """Two edges sharing (relation, file, source_location) are the SAME edge and
    intentionally coalesce even under multigraph (last-wins on the explicit key)."""
    ex = {
        "nodes": [
            {"id": "a", "label": "a", "source_file": "a.py"},
            {"id": "b", "label": "b", "source_file": "a.py"},
        ],
        "edges": [
            {"source": "a", "target": "b", "relation": "calls",
             "source_file": "a.py", "source_location": "L1"},
            {"source": "a", "target": "b", "relation": "calls",
             "source_file": "a.py", "source_location": "L1"},
        ],
    }
    g = build_from_json(ex, multigraph=True)
    assert g.number_of_edges() == 1


def test_multigraph_gates_on_capability_probe(monkeypatch):
    """build_from_json(multigraph=True) must call require_multigraph_capabilities();
    if the runtime is unfit it raises RuntimeError rather than silently degrading."""
    import graphify.multigraph_compat as mc

    called = {"n": 0}
    real = mc.require_multigraph_capabilities

    def _spy():
        called["n"] += 1
        return real()

    monkeypatch.setattr(mc, "require_multigraph_capabilities", _spy)
    build_from_json(_parallel_extraction(), multigraph=True)
    assert called["n"] == 1, "capability probe was not invoked"

    def _boom():
        raise RuntimeError("runtime unfit for MultiDiGraph round-trip")

    monkeypatch.setattr(mc, "require_multigraph_capabilities", _boom)
    with pytest.raises(RuntimeError):
        build_from_json(_parallel_extraction(), multigraph=True)


def test_build_passthrough_multigraph():
    """The public build() threads multigraph through to build_from_json."""
    g = build([_parallel_extraction()], multigraph=True)
    assert isinstance(g, nx.MultiDiGraph)
    assert g.number_of_edges() == 2


def test_diagnose_reports_no_collapse_under_multigraph():
    """Ground-truth metric: a multigraph build loses 0 parallel edges, whereas the
    directed default reports them as directed_same_endpoint_collapsed_edges."""
    from graphify.diagnostics import diagnose_extraction

    ex = _parallel_extraction()
    diag = diagnose_extraction(ex)
    # the directed diagnostic build collapses the parallel pair -> reports >=1
    assert diag["directed_same_endpoint_collapsed_edges"] >= 1
    # and the multigraph build actually preserves them
    g = build_from_json(ex, multigraph=True)
    assert g.number_of_edges() == len(ex["edges"])
