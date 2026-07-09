"""§11.6 lift eval: prove the graph's framework-boundary facts beat a naive
`grep @PreAuthorize` baseline on the *method-level-authz-coverage* question.

Question scored per controller: "does it enforce authorization on EVERY HTTP
endpoint?" The discriminating case is a controller with NO class-level guard
where one endpoint is @PreAuthorize-guarded and another is not — a naive grep
sees the token present and wrongly reports the whole controller as guarded.

Design guarantees (deterministic, zero-AI):
  * Ground truth is hand-written (ground_truth.json), never derived from graphify
    output -> the eval cannot be tautological.
  * The graph scorer runs the REAL extractor (graphify.extract.extract).
  * A mutation test strips the framework facts (class_authz_guarded flags +
    authz_guard edges) and asserts the graph scorer DEGRADES, proving the score
    is produced by those facts and not by a hardcoded/opposite-of-grep answer.

Exit 0 iff graph accuracy > naive accuracy AND mutated-graph accuracy <
graph accuracy. Otherwise exit 1.

Usage:
    python run_lift_eval.py [--json]
"""
from __future__ import annotations

import argparse
import atexit
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

# --- leak guard: register OUR temp-dir cleanup BEFORE importing/running graphify
# graphify.cache registers a stat-index flush hook lazily on first cache use
# during extraction (graphify.cache._ensure_stat_index), not at import time.
# Because we register our cleanup before importing graphify and before calling
# extract(), graphify's flush is registered later; atexit is LIFO, so our
# cleanup runs after graphify's flush on normal interpreter shutdown, and the
# cache dir is not re-created after we delete it. (Same fix as eval/run_eval.py.)
_LIFT_TMP_DIRS: list[Path] = []


def _cleanup_lift_tmp_dirs() -> None:
    for d in _LIFT_TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_lift_tmp_dirs)

# --- import the LOCAL worktree graphify, not the editable-installed main clone.
# `python run_lift_eval.py` puts this script's dir (eval/lift_authz) on sys.path[0],
# so the default PathFinder misses the worktree's top-level graphify/ package and
# falls through to the venv editable install (projects/graphify/graphify -> the main
# clone WITHOUT the impl-2/3 framework facts), silently scoring graph=None. Forcing
# the worktree root onto sys.path[0] makes PathFinder resolve the local package first.
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]
if str(_WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_ROOT))

from graphify.extract import extract  # noqa: E402

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
GROUND_TRUTH = HERE / "ground_truth.json"


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def run_extractor() -> dict:
    files = sorted(FIXTURES.glob("*.java"))
    if not files:
        raise SystemExit(f"no fixtures under {FIXTURES}")
    cache_root = Path(tempfile.mkdtemp(prefix="lift-authz-cache-"))
    _LIFT_TMP_DIRS.append(cache_root)
    return extract(files, cache_root=cache_root)


# --------------------------------------------------------------------------- #
# graph scorer
# --------------------------------------------------------------------------- #
def _is_controller(node: dict) -> bool:
    md = node.get("metadata") or {}
    return md.get("bean_stereotype") == "RestController"


def _edges_from(edges: list[dict], src_id: str) -> list[dict]:
    return [e for e in edges if e.get("source") == src_id]


def graph_predict(graph: dict) -> dict[str, bool]:
    """Return {className: fully_guarded_bool} using ONLY graph facts.

    A controller is fully guarded iff it has a class-level guard
    (metadata.class_authz_guarded) OR every HTTP-endpoint method carries an
    authz_guard annotation edge. An HTTP-endpoint method is a method node with
    an `exposure` edge to a *Mapping annotation.
    """
    nodes = graph["nodes"]
    edges = graph["edges"]
    by_id = {n["id"]: n for n in nodes}

    preds: dict[str, bool] = {}
    for cnode in nodes:
        if not _is_controller(cnode):
            continue
        cname = str(cnode.get("label"))
        cid = cnode["id"]
        class_guarded = bool((cnode.get("metadata") or {}).get("class_authz_guarded"))
        if class_guarded:
            preds[cname] = True
            continue

        # methods of this class: id prefixed by "<cid>_" and label starts with "."
        method_ids = [
            n["id"]
            for n in nodes
            if n["id"].startswith(cid + "_") and str(n.get("label", "")).startswith(".")
        ]
        endpoints: list[str] = []
        for mid in method_ids:
            for e in _edges_from(edges, mid):
                md = e.get("metadata") or {}
                if md.get("annotation_role") == "exposure":
                    ann = str(md.get("annotation") or by_id.get(e.get("target"), {}).get("label") or "")
                    if ann.endswith("Mapping"):
                        endpoints.append(mid)
                        break

        if not endpoints:
            # no detectable HTTP endpoints -> cannot claim full guard
            preds[cname] = False
            continue

        all_guarded = True
        for mid in endpoints:
            guarded = any(
                (e.get("metadata") or {}).get("annotation_role") == "authz_guard"
                for e in _edges_from(edges, mid)
            )
            if not guarded:
                all_guarded = False
                break
        preds[cname] = all_guarded
    return preds


def mutate_graph(graph: dict) -> dict:
    """Strip the framework-boundary facts the graph scorer relies on:
    drop class_authz_guarded flags and remove authz_guard annotation edges.
    A graph scorer that genuinely USES these facts must degrade on this input.
    """
    m = copy.deepcopy(graph)
    for n in m["nodes"]:
        md = n.get("metadata")
        if isinstance(md, dict) and "class_authz_guarded" in md:
            del md["class_authz_guarded"]
    m["edges"] = [
        e for e in m["edges"] if (e.get("metadata") or {}).get("annotation_role") != "authz_guard"
    ]
    return m


# --------------------------------------------------------------------------- #
# naive baseline
# --------------------------------------------------------------------------- #
def naive_predict() -> dict[str, bool]:
    """Baseline: a controller is 'guarded' iff its source file contains the
    literal token @PreAuthorize (a `grep @PreAuthorize` heuristic)."""
    preds: dict[str, bool] = {}
    for f in sorted(FIXTURES.glob("*.java")):
        cname = f.stem
        text = f.read_text(encoding="utf-8")
        preds[cname] = "@PreAuthorize" in text
    return preds


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def _accuracy(preds: dict[str, bool], truth: dict[str, bool]) -> tuple[int, int]:
    correct = sum(1 for k, v in truth.items() if preds.get(k) == v)
    return correct, len(truth)


def load_truth() -> dict[str, bool]:
    raw = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    return {k: bool(v["fully_guarded"]) for k, v in raw.items() if not k.startswith("_")}


def evaluate() -> dict:
    truth = load_truth()
    graph = run_extractor()

    graph_preds = graph_predict(graph)
    naive_preds = naive_predict()
    mutated_preds = graph_predict(mutate_graph(graph))

    g_ok, total = _accuracy(graph_preds, truth)
    n_ok, _ = _accuracy(naive_preds, truth)
    m_ok, _ = _accuracy(mutated_preds, truth)

    graph_acc = g_ok / total
    naive_acc = n_ok / total
    mutated_acc = m_ok / total

    per_class = {}
    for cname in sorted(truth):
        per_class[cname] = {
            "truth": truth[cname],
            "graph": graph_preds.get(cname),
            "naive": naive_preds.get(cname),
            "graph_correct": graph_preds.get(cname) == truth[cname],
            "naive_correct": naive_preds.get(cname) == truth[cname],
        }

    lift = round(graph_acc - naive_acc, 6)
    non_tautological = mutated_acc < graph_acc
    passed = (graph_acc > naive_acc) and non_tautological

    return {
        "question": "does the controller enforce authorization on EVERY HTTP endpoint?",
        "total": total,
        "graph_accuracy": round(graph_acc, 6),
        "naive_accuracy": round(naive_acc, 6),
        "mutated_graph_accuracy": round(mutated_acc, 6),
        "lift": lift,
        "non_tautological": non_tautological,
        "passed": passed,
        "per_class": per_class,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    result = evaluate()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Question: {result['question']}")
        print(f"  fixtures      : {result['total']}")
        print(f"  graph  acc    : {result['graph_accuracy']:.3f}")
        print(f"  naive  acc    : {result['naive_accuracy']:.3f}")
        print(f"  mutated  acc  : {result['mutated_graph_accuracy']:.3f}  (must be < graph)")
        print(f"  LIFT          : {result['lift']:+.3f}")
        print(f"  non-tautolog. : {result['non_tautological']}")
        print()
        print(f"  {'class':<26}{'truth':<7}{'graph':<7}{'naive':<7}")
        for cname, row in result["per_class"].items():
            print(f"  {cname:<26}{str(row['truth']):<7}{str(row['graph']):<7}{str(row['naive']):<7}")
        print()
        print("RESULT:", "PASS" if result["passed"] else "FAIL")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
