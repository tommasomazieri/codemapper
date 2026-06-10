"""MCP stdio server — the single interface Claude Code sees.

Self-contained: every tool runs in-process (GraphIndex, the analyzers,
graphify_runner, python_depth). No separate API server is required. The REST API
(api.py) remains an independent optional surface for non-MCP integrations.
"""

import datetime
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from codemapper import graphify_runner
from codemapper.graph_index import GraphIndex

mcp = FastMCP("codemapper2")


def _root() -> Path:
    return Path(os.environ.get("CODEMAPPER_ROOT", ".")).resolve()


def _log_mcp(root: Path, tool: str, **params) -> None:
    try:
        log_path = root / "graphify-out" / "mcp_usage.jsonl"
        record = {"ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                  "event": "mcp_call", "tool": tool, **params}
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _graph() -> GraphIndex:
    g = GraphIndex(_root())
    g.load()
    return g


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@mcp.tool()
def build(no_llm: bool = True, backend: str | None = None) -> str:
    """Rebuild the codebase knowledge graph in the background (non-blocking).

    ALWAYS call with no_llm=True (the default). The LLM semantic pass takes
    10+ minutes on the free OpenRouter tier and will time out the MCP call.
    The AST-only rebuild completes in under 60 seconds.

    Args:
        no_llm: Skip the LLM semantic pass. Default True — do not change.
        backend: LLM backend override (only relevant when no_llm=False).
    """
    import subprocess
    import sys

    root = _root()
    _log_mcp(root, "build", no_llm=no_llm)
    cmd = [sys.executable, "-m", "codemapper.cli", "build", str(root)]
    if no_llm:
        cmd.append("--no-llm")
    if backend:
        cmd.extend(["--backend", backend])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mode = "AST-only" if no_llm else "full LLM"
    return json.dumps({
        "status": "started",
        "mode": mode,
        "note": f"{mode} build running in background. Wait ~30-60s then query normally.",
    })


# ---------------------------------------------------------------------------
# Architecture navigation
# ---------------------------------------------------------------------------

@mcp.tool()
def god_nodes(
    n: int = 10,
    stale_only: bool = False,
    min_complexity: int | None = None,
    dead_only: bool = False,
) -> str:
    """The most architecturally central files ("god nodes"), optionally filtered
    by codemapper quality signals. Use this to answer "where should I look first?"

    Args:
        n: How many nodes to return.
        stale_only: Only nodes whose module docstring is likely stale.
        min_complexity: Only nodes with at least this cyclomatic complexity.
        dead_only: Only nodes flagged as dead code.
    """
    _log_mcp(_root(), "god_nodes", n=n, stale_only=stale_only, min_complexity=min_complexity, dead_only=dead_only)
    g = _graph()
    nodes = g.get_god_nodes(n=n, stale_only=stale_only, min_complexity=min_complexity, dead_only=dead_only)
    return json.dumps([
        {"id": x.id, "label": x.label, "source_file": x.source_file,
         "source_location": x.source_location, "degree": x.degree,
         "codemapper": x.codemapper}
        for x in nodes
    ], indent=2)


@mcp.tool()
def explore(query: str, budget: int = 2000) -> str:
    """Semantic graph search — find the subgraph relevant to a natural-language
    question about the codebase. Delegates to graphify's traversal engine.

    Args:
        query: A natural-language question (e.g. "how does auth talk to the db?").
        budget: Output token cap for the traversal (graphify default 2000).
    """
    root = _root()
    _log_mcp(root, "explore", query=query)
    return graphify_runner.query(query, root, budget=budget)


@mcp.tool()
def path_between(a: str, b: str) -> str:
    """Shortest relationship path between two concepts or files in the graph.

    Args:
        a: Source node label or concept.
        b: Target node label or concept.
    """
    root = _root()
    _log_mcp(root, "path_between", a=a, b=b)
    return graphify_runner.path_query(a, b, root)


@mcp.tool()
def community(node_id: str) -> str:
    """The community cluster a node belongs to, plus its sibling nodes — the
    related-concern group that file sits in.

    Args:
        node_id: The graph node id.
    """
    _log_mcp(_root(), "community", node_id=node_id)
    g = _graph()
    members = g.get_community(node_id)
    focal = g.get_node(node_id)
    return json.dumps({
        "node_id": node_id,
        "community_id": focal.community if focal else None,
        "members": [{"id": m.id, "label": m.label, "source_file": m.source_file} for m in members],
    }, indent=2)


@mcp.tool()
def neighbors(node_id: str, relation: str | None = None) -> str:
    """Direct graph neighbors of a node, optionally filtered by edge relation
    (e.g. 'calls', 'imports').

    Args:
        node_id: The graph node id.
        relation: Edge relation filter.
    """
    _log_mcp(_root(), "neighbors", node_id=node_id, relation=relation)
    g = _graph()
    out = g.get_neighbors(node_id, relation=relation)
    inc = g.get_incoming(node_id, relation=relation)
    return json.dumps({
        "node_id": node_id,
        "outgoing": [{"relation": e.relation, "id": n.id, "label": n.label} for e, n in out],
        "incoming": [{"relation": e.relation, "id": n.id, "label": n.label} for e, n in inc],
    }, indent=2)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@mcp.tool()
def diagnose(path: str | None = None, scope: str | None = None) -> str:
    """Deterministic quality report for a file (or the whole repo): dead code,
    cyclomatic complexity, dependency hygiene, and docstring staleness. Every
    finding is traceable to a line. Runs in-process; no server required.

    Args:
        path: Restrict findings to files matching this path fragment.
        scope: Comma-separated analyzers (dead,complexity,deps); default all.
    """
    from codemapper.analysis import ANALYZERS, analyze
    from codemapper.index import CodeIndex

    root = _root()
    _log_mcp(root, "diagnose", path=path, scope=scope)
    index = CodeIndex(root)
    index.build()
    scope_list = [s.strip() for s in scope.split(",")] if scope else list(ANALYZERS)
    result = analyze(index, root, scope=scope_list)
    findings = [f for f in result.findings if not path or (f.path and path in f.path)]
    return json.dumps({
        "score": result.score,
        "summary": result.summary,
        "findings": [
            {"rule": f.rule, "severity": f.severity, "path": f.path,
             "line": f.line, "symbol": f.symbol, "message": f.message}
            for f in findings
        ],
    }, indent=2)


@mcp.tool()
def python_sig(path: str, symbol: str) -> str:
    """The full type-annotated Python signature for a symbol (e.g.
    'def verify_token(token: str, secret: bytes) -> bool'). Runs in-process.

    Args:
        path: File path containing the symbol.
        symbol: The function/method/class name.
    """
    from codemapper.python_depth import signature
    root = _root()
    _log_mcp(root, "python_sig", path=path, symbol=symbol)
    result = signature(root, path, symbol)
    return json.dumps(result or {"error": f"no Python symbol '{symbol}' in {path}"}, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
