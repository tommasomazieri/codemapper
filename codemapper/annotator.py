"""Annotate graphify's graph.json with codemapper diagnostics → graph_annotated.json.

Joins deterministic codemapper findings (complexity, dead code, dependency
hygiene, docstring staleness) onto graph nodes by (source_file, label/line),
producing one graph_annotated.json that carries architecture + quality together.
Each affected node gains a "codemapper" block, e.g.:

    "codemapper": {
        "complexity": 53,
        "dead": true,
        "stale_docstring": true,
        "dep_issues": ["unused: os"]
    }
"""

import json
from collections import defaultdict
from pathlib import Path

from codemapper.analysis import analyze
from codemapper.index import CodeIndex
from codemapper.staleness import analyze_staleness


def _norm(p: str | None) -> str:
    """Normalize a path to repo-relative posix (matches graphify's source_file)."""
    if not p:
        return ""
    return p.replace("\\", "/").lstrip("./")


def _bare(label: str) -> str:
    """'main()' -> 'main'; 'ClassName' -> 'ClassName'."""
    return label.split("(")[0].strip()


def annotate(root: Path) -> tuple[Path, dict]:
    """Read graph.json, run analyzers, write graph_annotated.json. Returns
    (output_path, per-rule annotation counts)."""
    root = root.resolve()
    gpath = root / "graphify-out" / "graph.json"
    if not gpath.exists():
        raise FileNotFoundError(f"{gpath} not found; run a graphify build first.")

    data = json.loads(gpath.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])

    by_file: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        n.setdefault("codemapper", {})
        by_file[_norm(n.get("source_file"))].append(n)

    def file_node(path: str) -> dict | None:
        cands = by_file.get(_norm(path), [])
        base = _norm(path).split("/")[-1]
        for n in cands:
            if n.get("label") == base or (
                n.get("file_type") == "code" and n.get("source_location") == "L1"
            ):
                return n
        return cands[0] if cands else None

    def symbol_node(path: str, symbol: str | None, line: int | None) -> dict | None:
        cands = by_file.get(_norm(path), [])
        if not cands:
            return None
        if symbol:
            for n in cands:
                if _bare(n.get("label", "")) == symbol:
                    return n
        if line is not None:
            tag = f"L{line}"
            for n in cands:
                if n.get("source_location") == tag:
                    return n
        return None

    index = CodeIndex(root)
    index.build()
    result = analyze(index, root)
    stale = analyze_staleness(root, index)

    counts: dict[str, int] = defaultdict(int)

    for f in result.findings:
        if f.rule == "high_complexity":
            n = symbol_node(f.path, f.symbol, f.line) or file_node(f.path)
            if n is not None:
                cyc = (f.metadata or {}).get("cyclomatic", 0)
                cm = n["codemapper"]
                cm["complexity"] = max(cm.get("complexity", 0), cyc)
                counts["complexity"] += 1
        elif f.rule == "dead_code":
            n = symbol_node(f.path, f.symbol, f.line)
            if n is not None:
                n["codemapper"]["dead"] = True
                counts["dead"] += 1
        elif f.rule == "dead_file":
            n = file_node(f.path)
            if n is not None:
                n["codemapper"]["dead_file"] = True
                counts["dead_file"] += 1
        elif f.rule == "unused_import":
            n = file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("dep_issues", []).append(f"unused: {f.symbol}")
                counts["unused_import"] += 1
        elif f.rule == "undeclared_dependency":
            n = file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("dep_issues", []).append(f"undeclared: {f.symbol}")
                counts["undeclared_dependency"] += 1

    for s in stale:
        if not s.stale:
            continue
        n = file_node(s.path)
        if n is not None:
            n["codemapper"]["stale_docstring"] = True
            counts["stale_docstring"] += 1

    out = root / "graphify-out" / "graph_annotated.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out, dict(counts)
