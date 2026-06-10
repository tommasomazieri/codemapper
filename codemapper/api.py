"""FastAPI server — internal engine for the codemapper2 MCP adapter.

Graph navigation uses GraphIndex (Graphify's graph_annotated.json).
Diagnostics use the existing analyzer stack on a CodeIndex (Phase 1 bridge;
Phase 2 will migrate analyzers to GraphIndex).
"""

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException

from codemapper.analysis import ANALYZERS, analyze
from codemapper.graph_index import GraphIndex
from codemapper.graphify_runner import path_query, query
from codemapper.index import CodeIndex
from codemapper.staleness import STALE_COMMIT_THRESHOLD, analyze_staleness


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    root = Path(os.environ.get("CODEMAPPER_ROOT", ".")).resolve()
    graph = GraphIndex(root)
    try:
        graph.load()
    except FileNotFoundError:
        pass  # graph not yet built; navigation endpoints will return 503

    # Phase 1 bridge: CodeIndex for the diagnostic analyzers
    index = CodeIndex(root)
    index.build()

    app.state.root = root
    app.state.graph = graph
    app.state.index = index
    yield


app = FastAPI(
    title="codemapper2",
    description="Graphify graph + codemapper diagnostics, unified.",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _graph_ready() -> GraphIndex:
    graph: GraphIndex = app.state.graph
    if not graph._loaded:
        raise HTTPException(
            status_code=503,
            detail="Graph not yet built. Run 'codemapper2 build' first.",
        )
    return graph


def _node_dict(node) -> dict:
    return {
        "id": node.id,
        "label": node.label,
        "file_type": node.file_type,
        "source_file": node.source_file,
        "source_location": node.source_location,
        "community": node.community,
        "degree": node.degree,
        "codemapper": node.codemapper,
    }


# ---------------------------------------------------------------------------
# Graph navigation endpoints
# ---------------------------------------------------------------------------

@app.get("/status")
async def status() -> dict:
    graph: GraphIndex = app.state.graph
    if not graph._loaded:
        return {"graph_ready": False, "root": str(app.state.root)}
    return {
        "graph_ready": True,
        "root": str(app.state.root),
        "nodes": graph.node_count(),
        "communities": graph.community_count(),
    }


@app.get("/god_nodes")
async def god_nodes(
    n: int = 10,
    stale_only: bool = False,
    min_complexity: int | None = None,
    dead_only: bool = False,
) -> list[dict]:
    graph = _graph_ready()
    nodes = graph.get_god_nodes(n=n, stale_only=stale_only, min_complexity=min_complexity, dead_only=dead_only)
    return [_node_dict(nd) for nd in nodes]


@app.get("/community/{node_id:path}")
async def community(node_id: str) -> dict:
    graph = _graph_ready()
    siblings = graph.get_community(node_id)
    focal = graph.get_node(node_id)
    return {
        "node_id": node_id,
        "community_id": focal.community if focal else None,
        "members": [_node_dict(n) for n in siblings],
    }


@app.get("/neighbors/{node_id:path}")
async def neighbors(node_id: str, relation: str | None = None) -> dict:
    graph = _graph_ready()
    out = graph.get_neighbors(node_id, relation=relation)
    inc = graph.get_incoming(node_id, relation=relation)
    return {
        "node_id": node_id,
        "outgoing": [{"relation": e.relation, "confidence": e.confidence, "node": _node_dict(n)} for e, n in out],
        "incoming": [{"relation": e.relation, "confidence": e.confidence, "node": _node_dict(n)} for e, n in inc],
    }


@app.get("/explore")
async def explore(q: str, budget: int = 2000) -> dict:
    root: Path = app.state.root
    try:
        result = query(q, root, budget=budget)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"query": q, "result": result}


@app.get("/path")
async def path_between(a: str, b: str) -> dict:
    root: Path = app.state.root
    try:
        result = path_query(a, b, root)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"from": a, "to": b, "result": result}


@app.get("/find")
async def find_nodes(label: str) -> list[dict]:
    graph = _graph_ready()
    return [_node_dict(n) for n in graph.find_by_label(label)]


# ---------------------------------------------------------------------------
# Diagnostic endpoints (Phase 1: CodeIndex bridge)
# ---------------------------------------------------------------------------

@app.get("/diagnose")
async def diagnose(path: str | None = None, scope: str | None = None) -> dict:
    index: CodeIndex = app.state.index
    root: Path = app.state.root
    scope_list = [s.strip() for s in scope.split(",")] if scope else list(ANALYZERS)
    result = analyze(index, root, scope=scope_list)

    findings_out = []
    for f in result.findings:
        if path and f.path and path not in f.path:
            continue
        findings_out.append({
            "rule": f.rule,
            "severity": f.severity,
            "path": f.path,
            "line": f.line,
            "symbol": f.symbol,
            "message": f.message,
            "introduced": f.introduced,
            "actions": [asdict(a) for a in f.actions],
        })

    return {
        "root": result.root,
        "path_filter": path,
        "scope": scope_list,
        "score": result.score,
        "summary": result.summary,
        "findings": findings_out,
    }


@app.get("/python_sig")
async def python_sig(path: str, symbol: str) -> dict:
    from codemapper.python_depth import signature
    result = signature(app.state.root, path, symbol)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No Python symbol '{symbol}' in {path}")
    return result


@app.get("/staleness")
async def staleness_report() -> dict:
    index: CodeIndex = app.state.index
    findings = analyze_staleness(app.state.root, index)
    return {
        "root": str(app.state.root),
        "threshold": STALE_COMMIT_THRESHOLD,
        "findings": [asdict(f) for f in findings],
        "stale_count": sum(1 for f in findings if f.stale),
    }


@app.post("/refresh")
async def refresh() -> dict:
    index: CodeIndex = app.state.index
    graph: GraphIndex = app.state.graph
    index.refresh()
    try:
        graph.load()
    except FileNotFoundError:
        pass
    return {"status": "ok", "files": len(index.all_files()), "graph_nodes": graph.node_count()}
