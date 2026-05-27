"""
Manual API endpoint tester — auto-starts the server if not running.
Run:  python smoke_api.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.rule import Rule
from rich.text import Text

PORT = 8001
BASE = f"http://localhost:{PORT}"
ROOT = r"C:\Users\tomin\OneDrive\Desktop\PROGETTI\operating_proejcts\The Great Real Estate Boardgame\companion_web_app"
console = Console()


def section(title: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))


def show(label: str, data: object, status: int = 200) -> None:
    color = "green" if status < 400 else "red"
    header = Text(f"HTTP {status}  —  {label}", style=f"bold {color}")
    console.print(Panel(Pretty(data, indent_guides=True), title=header, border_style=color))


def get(path: str, params: dict | None = None, label: str | None = None) -> object:
    url = BASE + path
    r = httpx.get(url, params=params, timeout=10)
    show(label or f"GET {path}", r.json(), r.status_code)
    return r.json()


def post(path: str, data: dict | None = None, label: str | None = None) -> object:
    url = BASE + path
    r = httpx.post(url, json=data, timeout=10)
    show(label or f"POST {path}", r.json(), r.status_code)
    return r.json()


# ---------------------------------------------------------------------------
# Auto-start server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _server_proc = None
    try:
        httpx.get(BASE + "/map", timeout=2)
        console.print(f"[dim]Server already running on {BASE}[/dim]")
    except (httpx.ConnectError, httpx.ConnectTimeout):
        console.print(f"[yellow]Starting server on port {PORT}...[/yellow]")
        env = os.environ.copy()
        env["CODEMAPPER_ROOT"] = ROOT
        _server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "codemapper.api:app", "--port", str(PORT)],
            cwd=str(Path(__file__).parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            try:
                httpx.get(BASE + "/map", timeout=1)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                pass
        else:
            console.print(f"[bold red]Server failed to start on {BASE}[/bold red]")
            _server_proc.terminate()
            sys.exit(1)

    console.print(Panel(
        "[bold green]codemapper API — endpoint test run[/bold green]\n"
        f"Server: [cyan]{BASE}[/cyan]",
        border_style="bright_blue",
    ))

    # ---------------------------------------------------------------------------
    # /map
    # ---------------------------------------------------------------------------

    section("/map  —  codebase overview")
    get("/map", {"level": 0}, "GET /map?level=0  (file tree + docstrings)")
    get("/map", {"level": 1}, "GET /map?level=1  (adds symbol names)")
    get("/map", {"level": 2}, "GET /map?level=2  (adds signatures)")

    # ---------------------------------------------------------------------------
    # /file/{path}
    # ---------------------------------------------------------------------------

    section("/file/{path}  —  single file detail")
    get("/file/src/main.py", {"level": 0}, "GET /file/src/main.py?level=0")
    get("/file/src/main.py", {"level": 2}, "GET /file/src/main.py?level=2")
    get("/file/nonexistent.py", label="GET /file/nonexistent.py  (expect 404)")

    # ---------------------------------------------------------------------------
    # /symbol, /usages, /imports, /search
    # ---------------------------------------------------------------------------

    section("/symbol/{name}  —  definition lookup")
    get("/symbol/GameSession", label="GET /symbol/GameSession")
    get("/symbol/Player",      label="GET /symbol/Player")

    section("/usages/{name}  —  all usage sites")
    get("/usages/GameSession", label="GET /usages/GameSession")

    section("/imports/{module}  —  files that import a module")
    get("/imports/fastapi",    label="GET /imports/fastapi")
    get("/imports/dataclasses", label="GET /imports/dataclasses")

    section("/search  —  fuzzy symbol search")
    get("/search", {"q": "session"}, "GET /search?q=session")
    get("/search", {"q": "player"},  "GET /search?q=player")

    # ---------------------------------------------------------------------------
    # /packages
    # ---------------------------------------------------------------------------

    section("/packages  —  installed packages")
    get("/packages", label="GET /packages")

    # ---------------------------------------------------------------------------
    # Sessions
    # ---------------------------------------------------------------------------

    section("Sessions  —  progressive disclosure flow")

    result = post("/session/new", label="POST /session/new")
    sid = result.get("session_id", "UNKNOWN")
    console.print(f"  [dim]session_id:[/dim] [yellow]{sid}[/yellow]")

    post(
        f"/session/{sid}/expand",
        {"path": "src/main.py", "level": 1},
        f"POST /session/{sid[:8]}…/expand  path=src/main.py level=1  (first call → full delta)",
    )

    post(
        f"/session/{sid}/expand",
        {"path": "src/main.py", "level": 1},
        f"POST /session/{sid[:8]}…/expand  path=src/main.py level=1  (repeat → delta=null)",
    )

    post(
        f"/session/{sid}/expand",
        {"path": "src/main.py", "level": 2},
        f"POST /session/{sid[:8]}…/expand  path=src/main.py level=2  (upgrade L1→L2 → sig delta)",
    )

    post(
        f"/session/{sid}/expand",
        {"path": "src/managers/managers_hub.py", "level": 1},
        f"POST /session/{sid[:8]}…/expand  path=managers_hub.py level=1  (new file → full delta)",
    )

    # ---------------------------------------------------------------------------
    # /refresh
    # ---------------------------------------------------------------------------

    section("/refresh  —  re-index")
    post("/refresh", label="POST /refresh")

    # ---------------------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------------------

    console.print()
    console.print(Panel("[bold green]All endpoints tested.[/bold green]", border_style="green"))

    if _server_proc is not None:
        _server_proc.terminate()
