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

    def _tag_lang(n: dict | None, lang: str | None) -> None:
        if n is not None and lang:
            n["codemapper"].setdefault("language", lang)

    for f in result.findings:
        if f.rule == "high_complexity":
            n = symbol_node(f.path, f.symbol, f.line) or file_node(f.path)
            if n is not None:
                cyc = (f.metadata or {}).get("cyclomatic") or 0
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
        elif f.rule in ("unused_import", "unused_dependency"):
            n = file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("dep_issues", []).append(f"unused: {f.symbol}")
                counts[f.rule] += 1
        elif f.rule == "undeclared_dependency":
            n = file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("dep_issues", []).append(f"undeclared: {f.symbol}")
                counts["undeclared_dependency"] += 1
        # --- js/ts (fallow) ---
        elif f.rule == "duplicate_code":
            n = symbol_node(f.path, f.symbol, f.line) or file_node(f.path)
            if n is not None:
                n["codemapper"]["duplicate"] = True
                counts["duplicate"] += 1
        elif f.rule == "circular_dependency":
            n = file_node(f.path)
            if n is not None:
                n["codemapper"]["circular"] = True
                counts["circular"] += 1
        elif f.rule == "security":
            n = symbol_node(f.path, f.symbol, f.line) or file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("security", []).append(f.message)
                counts["security"] += 1
        # --- html (tree-sitter) ---
        elif f.rule in ("duplicate_id", "broken_local_ref", "missing_alt", "missing_lang", "inline_script_loc"):
            n = file_node(f.path)
            if n is not None:
                n["codemapper"].setdefault("html_issues", []).append(f"{f.rule}: {f.message}")
                counts[f.rule] += 1
        else:
            n = None
        _tag_lang(n, f.language)

    for s in stale:
        if not s.stale:
            continue
        n = file_node(s.path)
        if n is not None:
            n["codemapper"]["stale_docstring"] = True
            counts["stale_docstring"] += 1

    out = root / "graphify-out" / "graph_annotated.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _write_graph_report(root, nodes)
    return out, dict(counts)


def _write_graph_report(root: Path, nodes: list[dict]) -> None:
    """Write graphify-out/GRAPH_REPORT.md — a human-readable overview for the model."""
    by_degree = sorted(nodes, key=lambda n: n.get("degree", 0), reverse=True)
    top_nodes = by_degree[:15]

    communities: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        cid = str(n.get("community", "none"))
        communities[cid].append(n)

    stale_nodes = [n for n in nodes if n.get("codemapper", {}).get("stale_docstring")][:5]
    complex_nodes = sorted(
        [n for n in nodes if n.get("codemapper", {}).get("complexity")],
        key=lambda n: n["codemapper"].get("complexity", 0),
        reverse=True,
    )[:5]
    dead_count = sum(1 for n in nodes if n.get("codemapper", {}).get("dead") or n.get("codemapper", {}).get("dead_file"))

    lines = ["# Codebase Knowledge Graph Report", ""]

    lines += ["## God Nodes (most architecturally central files)", ""]
    lines += ["| label | source_file | degree | complexity | stale | dead |", "|---|---|---|---|---|---|"]
    for n in top_nodes:
        cm = n.get("codemapper", {})
        lines.append(
            f"| {n.get('label', '')} | {n.get('source_file', '')} | {n.get('degree', 0)} "
            f"| {cm.get('complexity', '')} | {cm.get('stale_docstring', '')} | {cm.get('dead', '') or cm.get('dead_file', '')} |"
        )
    lines.append("")

    lines += ["## Communities", ""]
    for cid, members in sorted(communities.items(), key=lambda x: -len(x[1]))[:10]:
        rep = max(members, key=lambda n: n.get("degree", 0))
        lines.append(f"- Community **{cid}**: {len(members)} nodes — representative: `{rep.get('label', '')}` ({rep.get('source_file', '')})")
    lines.append("")

    lines += ["## Quality Signals", ""]
    lines.append(f"Dead code / dead files: **{dead_count}** nodes flagged")
    if stale_nodes:
        lines.append("Top stale docstrings: " + ", ".join(f"`{n.get('label')}`" for n in stale_nodes))
    if complex_nodes:
        lines.append("Top complexity: " + ", ".join(
            f"`{n.get('label')}` ({n['codemapper']['complexity']})" for n in complex_nodes
        ))
    lines.append("")

    if top_nodes:
        a, b = top_nodes[0], top_nodes[1] if len(top_nodes) > 1 else top_nodes[0]
        lines += [
            "## Suggested queries",
            f'- `explore("{a.get("label", "")} architecture")`',
            f'- `explore("how does {a.get("label", "")} relate to {b.get("label", "")}")`',
            f'- `god_nodes(stale_only=True)` — files with outdated docstrings',
            f'- `god_nodes(dead_only=True)` — dead-code candidates',
        ]

    report_path = root / "graphify-out" / "GRAPH_REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
