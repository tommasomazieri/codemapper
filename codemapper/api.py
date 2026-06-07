import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from codemapper.index import CodeIndex
from codemapper.session import Session
from codemapper.staleness import STALE_COMMIT_THRESHOLD, analyze_staleness


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ExpandRequest(BaseModel):
    path: str
    level: int = 1


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

_sessions: dict[str, Session] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    root = Path(os.environ.get("CODEMAPPER_ROOT", ".")).resolve()
    index = CodeIndex(root)
    index.build()
    app.state.index = index
    app.state.root = root
    yield
    # Nothing to clean up


app = FastAPI(
    title="codemapper",
    description="Progressive-disclosure API for Python codebases.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _method_dict(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "line": sym.line, "decorators": sym.decorators}
    if level >= 2:
        d["signature"] = sym.signature
    return d


def _func_dict(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "line": sym.line, "decorators": sym.decorators}
    if level >= 2:
        d["signature"] = sym.signature
    return d


def _grouped_symbols(pf, level: int, include_variables: bool = False) -> dict:
    classes_by_name: dict[str, dict] = {}
    functions: list[dict] = []
    constants: list[dict] = []
    variables: list[dict] = []

    for sym in pf.symbols:
        if sym.kind == "class":
            classes_by_name[sym.name] = {
                "name": sym.name,
                "line": sym.line,
                "decorators": sym.decorators,
                "methods": [],
            }
        elif sym.kind == "function":
            functions.append(_func_dict(sym, level))
        elif sym.kind == "constant":
            constants.append({"name": sym.name, "line": sym.line})
        elif sym.kind == "variable" and include_variables:
            variables.append({"name": sym.name, "line": sym.line})

    for sym in pf.symbols:
        if sym.kind == "method" and sym.parent and sym.parent in classes_by_name:
            classes_by_name[sym.parent]["methods"].append(_method_dict(sym, level))

    result: dict = {}
    if constants:
        result["constants"] = constants
    if include_variables and variables:
        result["variables"] = variables
    if functions:
        result["functions"] = functions
    if classes_by_name:
        result["classes"] = list(classes_by_name.values())
    return result


def _file_response(pf, level: int) -> dict:
    global_imports = [asdict(i) for i in pf.imports if i.scope is None]
    scoped_imports = [asdict(i) for i in pf.imports if i.scope is not None]

    result: dict = {
        "path": pf.path,
        "level": level,
        "module_doc": pf.module_doc,
        "imports": {
            "global": global_imports,
            "scoped": scoped_imports,
        },
    }
    if level >= 1:
        result["module_doc_full"] = pf.module_doc_full
        result.update(_grouped_symbols(pf, level, include_variables=True))
    return result


def _map_entry(pf, level: int) -> dict:
    entry: dict = {"module_doc": pf.module_doc}
    if level >= 1:
        entry.update(_grouped_symbols(pf, level, include_variables=False))
    return entry


def _doc_entry(doc, level: int) -> dict:
    """Doc summary for /docs and the map's docs block. level 0 = kind only."""
    if level < 1:
        return {"kind": doc.kind}
    entry: dict = {"kind": doc.kind}
    if doc.top_keys:
        entry["top_keys"] = doc.top_keys
    if doc.headings:
        entry["headings"] = doc.headings
    if doc.wikilinks:
        entry["wikilinks"] = doc.wikilinks
    return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/map")
async def get_map(level: int = 0, include_docs: bool = False) -> dict:
    index: CodeIndex = app.state.index
    files = {path: _map_entry(index.get_file(path), level) for path in index.all_files()}
    result: dict = {"root": str(app.state.root), "level": level, "files": files}
    if include_docs:
        result["docs"] = {path: _doc_entry(index.get_doc(path), 0) for path in index.all_docs()}
    return result


@app.get("/docfiles")
async def get_docfiles(level: int = 0) -> dict:
    index: CodeIndex = app.state.index
    docs = {path: _doc_entry(index.get_doc(path), level) for path in index.all_docs()}
    return {"root": str(app.state.root), "level": level, "docs": docs}


@app.get("/doc/{path:path}")
async def get_doc(path: str) -> dict:
    index: CodeIndex = app.state.index
    doc = index.get_doc(path)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Doc not found in index: {path}")
    return asdict(doc)


@app.get("/staleness")
async def get_staleness() -> dict:
    index: CodeIndex = app.state.index
    findings = analyze_staleness(app.state.root, index)
    return {
        "root": str(app.state.root),
        "threshold": STALE_COMMIT_THRESHOLD,
        "findings": [asdict(f) for f in findings],
        "stale_count": sum(1 for f in findings if f.stale),
    }


@app.get("/file/{path:path}")
async def get_file(path: str, level: int = 0) -> dict:
    index: CodeIndex = app.state.index
    pf = index.get_file(path)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"File not found in index: {path}")
    return _file_response(pf, level)


@app.get("/symbol/{name}")
async def get_symbol(name: str) -> list[dict]:
    index: CodeIndex = app.state.index
    return [asdict(loc) for loc in index.find_symbol(name)]


@app.get("/usages/{name}")
async def get_usages(name: str) -> list[dict]:
    index: CodeIndex = app.state.index
    return [asdict(u) for u in index.find_usages(name)]


@app.get("/imports/{module}")
async def get_imports(module: str) -> list[str]:
    index: CodeIndex = app.state.index
    return index.find_imports(module)


@app.get("/search")
async def search(q: str) -> list[dict]:
    index: CodeIndex = app.state.index
    return [asdict(m) for m in index.search(q)]


@app.get("/packages")
async def get_packages() -> list[dict]:
    index: CodeIndex = app.state.index
    return [asdict(p) for p in index.packages()]


@app.post("/session/new")
async def new_session() -> dict:
    index: CodeIndex = app.state.index
    session_id = str(uuid.uuid4())
    _sessions[session_id] = Session(index=index, session_id=session_id)
    return {"session_id": session_id}


@app.post("/session/{session_id}/expand")
async def expand_session(session_id: str, body: ExpandRequest) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session.expand(body.path, body.level)


@app.post("/refresh")
async def refresh() -> dict:
    index: CodeIndex = app.state.index
    index.refresh()
    return {"status": "ok", "files": len(index.all_files())}
