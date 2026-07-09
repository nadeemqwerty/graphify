#!/usr/bin/env python3
"""Deterministic, zero-AI evaluation harness for graphify code comprehension.

Builds the graph for a fixed Java corpus, then answers a fixed set of
graph-structural questions PURELY by graph traversal (no LLM, no heuristics)
and scores each answer against hand-verified ground truth.

This is the "does the graph actually let you answer real code questions"
regression gate for the LLM-comprehension MVP. It is intentionally
deterministic: same fixtures + same questions => byte-identical result.

Answer sources (all real graphify public APIs / canonical graph data):
  * graphify.extract.extract      -> the canonical typed node/edge graph
  * graphify.build.build_from_json -> the networkx graph (used for hub ranking)
  * graphify.analyze.god_nodes     -> hub/degree ranking

Typed-edge traversal reads the canonical extraction edge list (which preserves
EVERY typed edge) rather than the collapsed simple networkx graph, so parallel
edges of different relations are never lost.

Exit codes:
  0  all questions passed
  1  one or more questions failed (or a harness/setup error)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from graphify.extract import extract
from graphify.build import build_from_json
from graphify.analyze import god_nodes

DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "spring_mini"
DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.json"


# --------------------------------------------------------------------------- #
# Graph loading + indexing
# --------------------------------------------------------------------------- #
def load_extraction(fixtures: Path) -> dict:
    """Extract the fixed corpus into the canonical {nodes,edges,raw_calls} dict.

    Uses a fresh temp cache each run so a stale cache can never influence the
    answers (determinism of the ANSWERS is what matters, not the cache path).
    """
    files = sorted(fixtures.glob("*.java"))
    if not files:
        raise SystemExit(f"no .java fixtures found under {fixtures}")
    cache_root = Path(tempfile.mkdtemp(prefix="graphify-eval-"))
    return extract(files, cache_root=cache_root)


class GraphIndex:
    """Typed adjacency over the canonical extraction edges + name resolution."""

    def __init__(self, r: dict):
        self.r = r
        self.id2 = {n["id"]: n for n in r["nodes"]}
        self.lbl2ids: dict[str, list[str]] = {}
        for n in r["nodes"]:
            self.lbl2ids.setdefault(n.get("label"), []).append(n["id"])
        # relation -> src_id -> [tgt_id]  and the reverse
        self.out: dict[str, dict[str, list[str]]] = {}
        self.inn: dict[str, dict[str, list[str]]] = {}
        self.method_owner: dict[str, str] = {}  # method_id -> class_id
        for e in r["edges"]:
            rel, s, t = e["relation"], e["source"], e["target"]
            self.out.setdefault(rel, {}).setdefault(s, []).append(t)
            self.inn.setdefault(rel, {}).setdefault(t, []).append(s)
            if rel == "method":
                self.method_owner[t] = s

    # -- name resolution ---------------------------------------------------- #
    def class_id(self, cls: str) -> str:
        cands = [
            nid for nid in self.lbl2ids.get(cls, [])
            if not (self.id2[nid].get("label") or "").endswith(".java")
            and not (self.id2[nid].get("label") or "").startswith(".")
        ]
        if len(cands) != 1:
            raise KeyError(f"class {cls!r} resolved to {len(cands)} nodes: {cands}")
        return cands[0]

    def method_id(self, qualified: str) -> str:
        cls, meth = qualified.split(".", 1)
        cid = self.class_id(cls)
        want = f".{meth}()"
        for tid in self.out.get("method", {}).get(cid, []):
            if self.id2[tid].get("label") == want:
                return tid
        raise KeyError(f"method {qualified!r} not found on class node {cid}")

    def qualify(self, method_id: str) -> str:
        owner = self.method_owner.get(method_id)
        cls = self.id2[owner]["label"] if owner else "?"
        lbl = self.id2[method_id].get("label", "")
        m = lbl[1:] if lbl.startswith(".") else lbl
        if m.endswith("()"):
            m = m[:-2]
        return f"{cls}.{m}"


# --------------------------------------------------------------------------- #
# Answerers (pure graph traversal, deterministic ordering)
# --------------------------------------------------------------------------- #
def _calls_reachable(idx: GraphIndex, src_id: str, dst_id: str) -> bool:
    seen = set()
    stack = [src_id]
    while stack:
        cur = stack.pop()
        if cur == dst_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(idx.out.get("calls", {}).get(cur, []))
    return False


def answer(idx: GraphIndex, G, q: dict):
    kind = q["kind"]
    if kind == "callees":
        mid = idx.method_id(q["target"])
        return sorted({idx.qualify(t) for t in idx.out.get("calls", {}).get(mid, [])})
    if kind == "callers":
        mid = idx.method_id(q["target"])
        return sorted({idx.qualify(s) for s in idx.inn.get("calls", {}).get(mid, [])})
    if kind == "reaches":
        return _calls_reachable(idx, idx.method_id(q["target"]), idx.method_id(q["to"]))
    if kind == "extends":
        cid = idx.class_id(q["target"])
        return sorted({idx.id2[t]["label"] for t in idx.out.get("inherits", {}).get(cid, [])})
    if kind == "references":
        cid = idx.class_id(q["target"])
        return sorted({idx.id2[t]["label"] for t in idx.out.get("references", {}).get(cid, [])})
    if kind == "method_count":
        cid = idx.class_id(q["target"])
        return len(idx.out.get("method", {}).get(cid, []))
    if kind == "god_top":
        hubs = god_nodes(G, top_n=int(q["n"]))
        return sorted({h["label"] for h in hubs})
    raise SystemExit(f"unknown question kind: {kind!r}")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run(fixtures: Path = DEFAULT_FIXTURES, questions: Path = DEFAULT_QUESTIONS) -> dict:
    r = load_extraction(fixtures)
    G = build_from_json(r, directed=True)
    idx = GraphIndex(r)
    qs = json.loads(Path(questions).read_text(encoding="utf-8"))

    results = []
    for q in qs:
        got = answer(idx, G, q)
        exp = q["expect"]
        exp_cmp = sorted(exp) if isinstance(exp, list) else exp
        ok = got == exp_cmp
        results.append({
            "id": q["id"],
            "kind": q["kind"],
            "question": q.get("question", ""),
            "expect": exp_cmp,
            "got": got,
            "pass": ok,
        })
    passed = sum(1 for x in results if x["pass"])
    return {
        "total": len(results),
        "passed": passed,
        "all_pass": passed == len(results),
        "node_count": len(r["nodes"]),
        "edge_count": len(r["edges"]),
        "results": results,
    }


def _print_human(summary: dict) -> None:
    print(f"graphify eval — {summary['passed']}/{summary['total']} passed "
          f"(nodes={summary['node_count']} edges={summary['edge_count']})")
    print("-" * 72)
    for x in summary["results"]:
        mark = "PASS" if x["pass"] else "FAIL"
        print(f"[{mark}] {x['id']:<4} {x['kind']:<13} {x['question']}")
        if not x["pass"]:
            print(f"        expected: {x['expect']}")
            print(f"        got     : {x['got']}")
    print("-" * 72)
    print("RESULT:", "ALL PASS" if summary["all_pass"] else "FAILURES PRESENT")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic graphify comprehension eval")
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    ap.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    summary = run(args.fixtures, args.questions)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human(summary)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
