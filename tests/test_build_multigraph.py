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


# --------------------------------------------------------------------------
# CLI end-to-end lock: `graphify extract ... --multigraph` must make the
# exported graph.json self-describing (top-level `multigraph`) in BOTH the
# clustered and --no-cluster write paths, and must NOT alter the default.
# Regression guard for the two-path bug (#extract had a separate --no-cluster
# raw-dump branch that bypassed build() and dropped the flag).
# --------------------------------------------------------------------------
import json as _json
import subprocess as _sp
import sys as _sys


def _run_extract(tmp_path, *flags):
    """Run the real CLI in a fresh dir and return the parsed graph.json."""
    src = tmp_path / "s.py"
    src.write_text("def helper():\n    return 1\ndef main():\n    return helper()\n",
                   encoding="utf-8")
    proc = _sp.run(
        [_sys.executable, "-m", "graphify", "extract", str(tmp_path), "--no-llm", *flags],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"extract failed: {proc.stderr}\n{proc.stdout}"
    gj = tmp_path / "graphify-out" / "graph.json"
    assert gj.exists(), f"graph.json not written: {proc.stdout}"
    return _json.loads(gj.read_text(encoding="utf-8"))


def test_cli_multigraph_clustered_sets_true(tmp_path):
    """Clustered path + --multigraph -> exported graph.json has multigraph == True."""
    data = _run_extract(tmp_path, "--multigraph")
    assert data.get("multigraph") is True


def test_cli_multigraph_no_cluster_sets_true(tmp_path):
    """Raw --no-cluster path + --multigraph is self-describing (multigraph == True).
    Locks the two-path bug where the raw-dump branch bypassed build()."""
    data = _run_extract(tmp_path, "--no-cluster", "--multigraph")
    assert data.get("multigraph") is True


def test_cli_default_clustered_not_multigraph(tmp_path):
    """Default clustered export is a DiGraph (node_link_data emits multigraph == False)."""
    data = _run_extract(tmp_path)
    assert data.get("multigraph") is False


def test_cli_default_no_cluster_omits_key(tmp_path):
    """Default --no-cluster raw dump is byte-compatible: no multigraph key added."""
    data = _run_extract(tmp_path, "--no-cluster")
    assert "multigraph" not in data
