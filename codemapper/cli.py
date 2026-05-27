import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from codemapper.index import CodeIndex

app = typer.Typer(help="codemapper — progressive-disclosure API for Python codebases.")
session_app = typer.Typer(help="Session management commands.")
app.add_typer(session_app, name="session")

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_index(root: Path) -> CodeIndex:
    index = CodeIndex(root)
    if (root / ".codemapper_cache.json").exists():
        index.refresh()
    else:
        index.build()
    return index


def _client_get(url: str, path: str, params: dict | None = None) -> dict | list:
    try:
        import httpx
    except ImportError:
        typer.echo("httpx is required for client mode: pip install httpx", err=True)
        raise typer.Exit(1)
    full_url = url.rstrip("/") + "/" + path.lstrip("/")
    r = httpx.get(full_url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _client_post(url: str, path: str, data: dict | None = None) -> dict | list:
    try:
        import httpx
    except ImportError:
        typer.echo("httpx is required for client mode: pip install httpx", err=True)
        raise typer.Exit(1)
    full_url = url.rstrip("/") + "/" + path.lstrip("/")
    r = httpx.post(full_url, json=data, timeout=10)
    r.raise_for_status()
    return r.json()


def _out(data, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(data, indent=2))
    else:
        console.print(data)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def serve(
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
    root: Path = typer.Option(Path("."), "--root", help="Repo root to index."),
) -> None:
    """Start the codemapper API server."""
    import os
    os.environ["CODEMAPPER_ROOT"] = str(root.resolve())
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required: pip install uvicorn", err=True)
        raise typer.Exit(1)
    uvicorn.run("codemapper.api:app", host="0.0.0.0", port=port, reload=False)


@app.command()
def map(
    level: int = typer.Option(0, "--level", help="Detail level (0-2)."),
    root: Path = typer.Option(Path("."), "--root", help="Repo root to index."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
    url: Optional[str] = typer.Option(None, "--url", help="URL of running server (client mode)."),
) -> None:
    """Print a repo map at the given detail level."""
    if url:
        data = _client_get(url, "/map", {"level": level})
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    files_out: dict = {}
    for path_key in index.all_files():
        pf = index.get_file(path_key)
        entry: dict = {"module_doc": pf.module_doc}
        if level >= 1:
            syms = []
            for s in pf.symbols:
                sd: dict = {"name": s.name, "kind": s.kind, "line": s.line}
                if level >= 2:
                    sd["signature"] = s.signature
                    sd["parent"] = s.parent
                syms.append(sd)
            entry["symbols"] = syms
        files_out[path_key] = entry

    data = {"root": str(root.resolve()), "level": level, "files": files_out}

    if json_output:
        typer.echo(json.dumps(data, indent=2))
        return

    tree = Tree(f"[bold]{root.resolve()}[/bold]  (level {level})")
    for fpath, fdata in files_out.items():
        branch = tree.add(f"[cyan]{fpath}[/cyan]  {fdata.get('module_doc') or ''}")
        for sym in fdata.get("symbols", []):
            sig = sym.get("signature") or sym["name"]
            branch.add(f"[green]{sym['kind']}[/green] {sig}  :[dim]{sym['line']}[/dim]")
    console.print(tree)


@app.command()
def inspect(
    path: str = typer.Argument(..., help="File path relative to root."),
    level: int = typer.Option(1, "--level", help="Detail level (0-2)."),
    root: Path = typer.Option(Path("."), "--root", help="Repo root."),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Show detail for a single file."""
    if url:
        data = _client_get(url, f"/file/{path}", {"level": level})
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    pf = index.get_file(path)
    if pf is None:
        typer.echo(f"File not found in index: {path}", err=True)
        raise typer.Exit(1)

    syms = []
    for s in pf.symbols:
        sd: dict = {"name": s.name, "kind": s.kind, "line": s.line}
        if level >= 2:
            sd["signature"] = s.signature
            sd["parent"] = s.parent
        syms.append(sd)

    data = {
        "path": pf.path,
        "level": level,
        "module_doc": pf.module_doc,
        "imports": [asdict(i) for i in pf.imports],
        "symbols": syms if level >= 1 else [],
    }

    if json_output:
        typer.echo(json.dumps(data, indent=2))
        return

    console.print(f"[bold]{pf.path}[/bold]  (level {level})")
    if pf.module_doc:
        console.print(f"[italic]{pf.module_doc}[/italic]")
    if data["imports"]:
        tbl = Table("module", "alias", "kind", "line", title="Imports")
        for imp in data["imports"]:
            tbl.add_row(imp["module"], imp["alias"] or "", imp["kind"], str(imp["line"]))
        console.print(tbl)
    if data["symbols"]:
        tbl = Table("name", "kind", "line", *(["signature"] if level >= 2 else []), title="Symbols")
        for sym in data["symbols"]:
            row = [sym["name"], sym["kind"], str(sym["line"])]
            if level >= 2:
                row.append(sym.get("signature") or "")
            tbl.add_row(*row)
        console.print(tbl)


@app.command()
def find(
    symbol: str = typer.Argument(..., help="Symbol name to locate."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Find where a symbol is defined."""
    if url:
        data = _client_get(url, f"/symbol/{symbol}")
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    results = [asdict(loc) for loc in index.find_symbol(symbol)]

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print(f"[yellow]No definition found for '{symbol}'[/yellow]")
        return
    tbl = Table("file", "kind", "line", "parent", title=f"Definition: {symbol}")
    for r in results:
        tbl.add_row(r["file"], r["kind"], str(r["line"]), r["parent"] or "")
    console.print(tbl)


@app.command()
def usages(
    symbol: str = typer.Argument(..., help="Symbol name to find usages of."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Find all usages of a symbol."""
    if url:
        data = _client_get(url, f"/usages/{symbol}")
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    results = [asdict(u) for u in index.find_usages(symbol)]

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print(f"[yellow]No usages found for '{symbol}'[/yellow]")
        return
    tbl = Table("file", "line", "context", title=f"Usages: {symbol}")
    for r in results:
        tbl.add_row(r["file"], str(r["line"]), r["context"])
    console.print(tbl)


@app.command(name="imports")
def imports_cmd(
    module: str = typer.Argument(..., help="Module name to search imports for."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """List files that import a module."""
    if url:
        data = _client_get(url, f"/imports/{module}")
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    results = index.find_imports(module)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print(f"[yellow]No files import '{module}'[/yellow]")
        return
    for f in results:
        console.print(f)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (case-insensitive substring)."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Fuzzy-search symbols by name."""
    if url:
        data = _client_get(url, "/search", {"q": query})
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    results = [asdict(m) for m in index.search(query)]

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print(f"[yellow]No symbols matching '{query}'[/yellow]")
        return
    tbl = Table("file", "name", "kind", "line", title=f"Search: {query}")
    for r in results:
        tbl.add_row(r["file"], r["name"], r["kind"], str(r["line"]))
    console.print(tbl)


@app.command()
def packages(
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """List installed packages and which indexed files use them."""
    if url:
        data = _client_get(url, "/packages")
        _out(data, json_output)
        return

    index = _get_index(root.resolve())
    results = [asdict(p) for p in index.packages()]

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    tbl = Table("name", "version", "used_in", title="Packages")
    for p in results:
        tbl.add_row(p["name"], p["version"], ", ".join(p["used_in"]))
    console.print(tbl)


# ---------------------------------------------------------------------------
# Session subcommands
# ---------------------------------------------------------------------------

@session_app.command("new")
def session_new(
    save: Optional[Path] = typer.Option(None, "--save", help="Path to persist session state."),
    url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Create a new progressive-disclosure session."""
    if url:
        data = _client_post(url, "/session/new")
        typer.echo(json.dumps(data, indent=2))
        return

    import uuid
    from codemapper.session import Session
    # In standalone mode, just generate an ID and optionally save state
    root = Path(".").resolve()
    index = _get_index(root)
    session_id = str(uuid.uuid4())
    session = Session(index=index, session_id=session_id, save_path=save)
    if save:
        session._persist()
    typer.echo(json.dumps({"session_id": session_id}, indent=2))


@session_app.command("expand")
def session_expand(
    path: str = typer.Argument(..., help="File path to expand."),
    level: int = typer.Option(1, "--level"),
    session_file: Optional[Path] = typer.Option(None, "--session", help="Saved session file."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
    url: Optional[str] = typer.Option(None, "--url"),
    session_id_opt: Optional[str] = typer.Option(None, "--session-id"),
) -> None:
    """Expand a file within a session (returns delta only)."""
    if url:
        if not session_id_opt:
            typer.echo("--session-id is required in client mode", err=True)
            raise typer.Exit(1)
        data = _client_post(url, f"/session/{session_id_opt}/expand", {"path": path, "level": level})
        _out(data, json_output)
        return

    import json as _json
    import uuid
    from codemapper.session import Session

    index = _get_index(root.resolve())

    if session_file and session_file.exists():
        saved = _json.loads(session_file.read_text())
        session_id = saved["session_id"]
        session = Session(index=index, session_id=session_id, save_path=session_file)
        session._seen = saved.get("seen", {})
    else:
        session_id = session_id_opt or str(uuid.uuid4())
        session = Session(index=index, session_id=session_id, save_path=session_file)

    result = session.expand(path, level)
    _out(result, json_output)
