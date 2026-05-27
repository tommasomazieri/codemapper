"""
Manual API endpoint tester.
Start the server first:  uvicorn codemapper.api:app --reload
Then run:                python test_api.py
"""

import sys
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.rule import Rule
from rich.text import Text

BASE = "http://localhost:8000"
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
# Ping
# ---------------------------------------------------------------------------

try:
    httpx.get(BASE + "/map", timeout=3)
except httpx.ConnectError:
    console.print("[bold red]Cannot reach server at http://localhost:8000[/bold red]")
    console.print("Start it with:  [bold]uvicorn codemapper.api:app --reload[/bold]")
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
get("/file/codemapper/parser.py", {"level": 0}, "GET /file/codemapper/parser.py?level=0")
get("/file/codemapper/parser.py", {"level": 2}, "GET /file/codemapper/parser.py?level=2")
get("/file/nonexistent.py", label="GET /file/nonexistent.py  (expect 404)")

# ---------------------------------------------------------------------------
# /symbol, /usages, /imports, /search
# ---------------------------------------------------------------------------

section("/symbol/{name}  —  definition lookup")
get("/symbol/ParsedFile", label="GET /symbol/ParsedFile")
get("/symbol/CodeIndex",  label="GET /symbol/CodeIndex")

section("/usages/{name}  —  all usage sites")
get("/usages/ParsedFile", label="GET /usages/ParsedFile")

section("/imports/{module}  —  files that import a module")
get("/imports/fastapi",    label="GET /imports/fastapi")
get("/imports/dataclasses", label="GET /imports/dataclasses")

section("/search  —  fuzzy symbol search")
get("/search", {"q": "parse"}, "GET /search?q=parse")
get("/search", {"q": "index"}, "GET /search?q=index")

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
    {"path": "codemapper/parser.py", "level": 1},
    f"POST /session/{sid[:8]}…/expand  path=parser.py level=1  (first call → full delta)",
)

post(
    f"/session/{sid}/expand",
    {"path": "codemapper/parser.py", "level": 1},
    f"POST /session/{sid[:8]}…/expand  path=parser.py level=1  (repeat → delta=null)",
)

post(
    f"/session/{sid}/expand",
    {"path": "codemapper/parser.py", "level": 2},
    f"POST /session/{sid[:8]}…/expand  path=parser.py level=2  (upgrade L1→L2 → sig delta)",
)

post(
    f"/session/{sid}/expand",
    {"path": "codemapper/index.py", "level": 1},
    f"POST /session/{sid[:8]}…/expand  path=index.py level=1  (new file → full delta)",
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
