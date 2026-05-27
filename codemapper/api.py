import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from codemapper.index import CodeIndex
from codemapper.session import Session


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

def _symbol_dict(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "kind": sym.kind, "line": sym.line}
    if level >= 2:
        d["signature"] = sym.signature
        d["parent"] = sym.parent
    return d


def _file_response(pf, level: int) -> dict:
    result: dict = {
        "path": pf.path,
        "level": level,
        "module_doc": pf.module_doc,
        "imports": [asdict(i) for i in pf.imports],
        "symbols": [],
    }
    if level >= 1:
        result["symbols"] = [_symbol_dict(s, level) for s in pf.symbols]
    return result


def _map_entry(pf, level: int) -> dict:
    entry: dict = {"module_doc": pf.module_doc}
    if level >= 1:
        entry["symbols"] = [_symbol_dict(s, level) for s in pf.symbols]
    return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/map")
async def get_map(level: int = 0) -> dict:
    index: CodeIndex = app.state.index
    files = {path: _map_entry(index.get_file(path), level) for path in index.all_files()}
    return {"root": str(app.state.root), "level": level, "files": files}


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
