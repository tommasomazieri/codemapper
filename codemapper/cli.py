"""codemapper2 CLI -setup, build, serve (API or MCP), diagnose, god-nodes."""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from codemapper import graphify_runner
from codemapper.graph_index import GraphIndex

app = typer.Typer(help="codemapper2 -unified codebase graph + diagnostics for AI agents.")
console = Console()


def _write_mcp_json(project: Path) -> None:
    """Register the codemapper2 stdio MCP server in the project's .mcp.json."""
    path = project / ".mcp.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
    servers = data.setdefault("mcpServers", {})
    servers["codemapper2"] = {
        "command": sys.executable,           # the venv python running this setup
        "args": ["-m", "codemapper.mcp_server"],
        "env": {"CODEMAPPER_ROOT": str(project)},
        "timeout": 600000,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_hook(project: Path) -> None:
    """Install the PreToolUse hook in the project's .claude/settings.json.

    Exec form (command + args) avoids shell-quoting issues with the spaced venv
    python path. Idempotent: removes any prior codemapper2 hook before adding.
    """
    settings_dir = project / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "settings.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}

    hooks = data.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    # Drop any existing codemapper2 hook entries (idempotent re-run).
    def _is_ours(entry: dict) -> bool:
        for h in entry.get("hooks", []):
            if "codemapper.hook" in (h.get("args") or []):
                return True
        return False
    pre[:] = [e for e in pre if not _is_ours(e)]
    pre.append({
        "matcher": "Grep|Glob|Bash",
        "hooks": [
            {
                "type": "command",
                "command": sys.executable,
                "args": ["-m", "codemapper.hook"],
                "timeout": 5000,
            }
        ],
    })
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@app.command()
def setup(
    path: Path = typer.Argument(Path("."), help="Target project to initialize."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM semantic pass."),
    backend: Optional[str] = typer.Option(None, "--backend"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Wire config but don't build now."),
) -> None:
    """One-command init for a target repo: register the MCP server (.mcp.json),
    install the PreToolUse hook (.claude/settings.json), and build the graph."""
    from codemapper.annotator import annotate

    project = path.resolve()
    console.print(f"[cyan]Initializing codemapper2 for[/cyan] {project}")
    _write_mcp_json(project)
    console.print("  [green]OK[/green] .mcp.json -registered codemapper2 MCP server")
    _write_hook(project)
    console.print("  [green]OK[/green] .claude/settings.json -installed PreToolUse hook")

    if skip_build:
        console.print("[yellow]Skipped build[/yellow] (--skip-build). Run 'codemapper2 build' later.")
        return

    console.print("  building graph (graphify) ...")
    graphify_runner.build(project, no_llm=no_llm, backend=backend)
    _, counts = annotate(project)
    g = GraphIndex(project)
    g.load()
    console.print(
        f"  [green]OK[/green] {g.node_count()} nodes, {g.community_count()} communities; "
        f"annotations: {counts}"
    )
    console.print("[bold green]Done.[/bold green] Restart Claude Code in this repo to load the MCP server.")


@app.command()
def build(
    path: Path = typer.Argument(Path("."), help="Repo root to build."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM semantic pass (code-only)."),
    backend: Optional[str] = typer.Option(None, "--backend", help="LLM backend (openrouter, ollama, ...)."),
) -> None:
    """Build the knowledge graph (graphify) and annotate it with diagnostics."""
    from codemapper.annotator import annotate

    root = path.resolve()
    console.print(f"[cyan]1/2 Building graph for[/cyan] {root} ...")
    graphify_runner.build(root, no_llm=no_llm, backend=backend)
    console.print("[cyan]2/2 Annotating with codemapper diagnostics ...[/cyan]")
    try:
        _, counts = annotate(root)
        g = GraphIndex(root)
        g.load()
        console.print(
            f"[green]OK[/green] {g.node_count()} nodes, {g.community_count()} communities; "
            f"annotations: {counts}"
        )
    except FileNotFoundError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def serve(
    mcp: bool = typer.Option(False, "--mcp", help="Start the MCP stdio server instead of the HTTP API."),
    port: int = typer.Option(8000, "--port", help="Port for the HTTP API."),
    root: Path = typer.Option(Path("."), "--root", help="Repo root to serve."),
) -> None:
    """Start the codemapper2 server -HTTP API (default) or MCP stdio (--mcp)."""
    os.environ["CODEMAPPER_ROOT"] = str(root.resolve())
    if mcp:
        from codemapper.mcp_server import main as mcp_main
        mcp_main()
        return
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required: pip install uvicorn", err=True)
        raise typer.Exit(1)
    uvicorn.run("codemapper.api:app", host="127.0.0.1", port=port, reload=False)


@app.command()
def diagnose(
    path: Optional[str] = typer.Argument(None, help="File path fragment to restrict findings."),
    root: Path = typer.Option(Path("."), "--root"),
    scope: Optional[str] = typer.Option(None, "--scope", help="dead,complexity,deps (default all)."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run deterministic diagnostics: dead code, complexity, dep hygiene, staleness."""
    from codemapper.analysis import ANALYZERS, analyze
    from codemapper.index import CodeIndex

    r = root.resolve()
    index = CodeIndex(r)
    index.build()
    scope_list = [s.strip() for s in scope.split(",")] if scope else list(ANALYZERS)
    result = analyze(index, r, scope=scope_list)

    findings = [
        f for f in result.findings
        if not path or (f.path and path in f.path)
    ]

    if json_output:
        typer.echo(json.dumps({
            "score": result.score,
            "summary": result.summary,
            "findings": [
                {"rule": f.rule, "severity": f.severity, "path": f.path,
                 "line": f.line, "symbol": f.symbol, "message": f.message}
                for f in findings
            ],
        }, indent=2))
        return

    console.print(f"[bold]Health score:[/bold] {result.score}/100")
    if not findings:
        console.print("[green]No findings.[/green]")
        return
    tbl = Table("rule", "severity", "path", "line", "symbol", "message")
    for f in findings:
        tbl.add_row(f.rule, f.severity, f.path or "", str(f.line or ""), f.symbol or "", f.message or "")
    console.print(tbl)


@app.command(name="god-nodes")
def god_nodes(
    n: int = typer.Option(10, "--n", help="How many nodes."),
    stale: bool = typer.Option(False, "--stale", help="Only nodes with stale docstrings."),
    min_complexity: Optional[int] = typer.Option(None, "--min-complexity"),
    dead: bool = typer.Option(False, "--dead", help="Only dead-code nodes."),
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List the most architecturally central files, filterable by quality signals."""
    g = GraphIndex(root.resolve())
    try:
        g.load()
    except FileNotFoundError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(1)

    nodes = g.get_god_nodes(n=n, stale_only=stale, min_complexity=min_complexity, dead_only=dead)

    if json_output:
        typer.echo(json.dumps([
            {"id": x.id, "label": x.label, "source_file": x.source_file,
             "source_location": x.source_location, "degree": x.degree,
             "codemapper": x.codemapper}
            for x in nodes
        ], indent=2))
        return

    tbl = Table("label", "source_file", "degree", "complexity", "stale", "dead")
    for x in nodes:
        cm = x.codemapper
        tbl.add_row(
            x.label, x.source_file, str(x.degree),
            str(cm.get("complexity", "")), str(cm.get("stale_docstring", "")),
            str(cm.get("dead", "")),
        )
    console.print(tbl)


if __name__ == "__main__":
    app()
