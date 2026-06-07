# codemapper — Technical Architecture

## Overview

codemapper is structured in three layers on top of a shared core:

```
codemapper/
├── parser.py     — Python AST analysis, symbol extraction
├── docparser.py  — light, deterministic parsing of non-.py files (JSON/TOML/YAML/MD)
├── staleness.py  — git-based docstring drift detection (deterministic anti-slop)
├── index.py      — repo-wide symbol + doc index, caching, incremental refresh
├── session.py    — progressive disclosure state management
├── api.py        — FastAPI REST server
├── cli.py        — Typer CLI (wraps api or calls core directly)
└── analysis/     — fallow-style quality analyzer (dead code, complexity, dep hygiene)
    ├── __init__.py   — analyze() orchestrator, ANALYZERS registry
    ├── findings.py   — Action, Finding, AnalysisResult data model
    ├── util.py       — read_pyproject, iter_functions, collect_referenced_names, entry_point_roots
    ├── deadcode.py   — find_dead_code(index, root)
    ├── complexity.py — find_complexity(index, root, ...)
    └── deps.py       — find_dependency_issues(index, root)
```

Beyond Python symbols, codemapper now gives agents **deterministic context** about
the rest of the repo — config files and markdown — a **staleness signal** that
flags module docstrings likely to have rotted as code changed, and a
**fallow-style quality analyzer** that finds dead code, high-complexity functions,
and dependency hygiene issues. None of this uses AI: every output is a reproducible
fact (the core principle borrowed from `fallow`).

---

## Core: `parser.py`

Uses Python's built-in `ast` module — no external parser needed for v1.

**What it extracts per file:**

```python
@dataclass
class Symbol:
    name: str
    kind: str           # "class" | "function" | "method" | "constant"
    line: int
    signature: str | None   # only at level 2
    parent: str | None      # class name for methods

@dataclass
class ParsedFile:
    path: str
    module_doc: str | None       # first line of module docstring (level-0 economy)
    imports: list[ImportInfo]    # each tagged: local | stdlib | package
    symbols: list[Symbol]
    module_doc_full: str | None  # complete module docstring (deep queries only)
    doc_start_line: int | None   # span of the module docstring, used by staleness
    doc_end_line: int | None
```

## Core: `docparser.py`

Light, deterministic parsing of **non-Python files** (no AI, never raises):

```python
@dataclass
class DocFile:
    path: str
    kind: str              # "json" | "toml" | "yaml" | "markdown" | "other"
    top_keys: list[str]    # config files: sorted top-level keys
    headings: list[str]    # markdown: "## Heading"
    wikilinks: list[str]   # markdown: deduped [[target]]
```

- JSON / TOML (stdlib `tomllib`) / YAML (PyYAML if present) → top-level keys.
- Markdown → headings + `[[wikilinks]]`.
- Everything else → listed by path only (`kind="other"`).
- Malformed input degrades to an empty summary so the index stays robust.

## Core: `staleness.py`

Deterministic docstring **drift detection** from git history:

```python
@dataclass
class StalenessFinding:
    path: str
    has_docstring: bool
    doc_last_touched: str | None   # "<short-sha> YYYY-MM-DD"
    code_commits_since: int        # commits touching the file after the doc was last touched
    stale: bool
    reason: str                    # "no_module_docstring" | "code_changed_Nx_since_doc" | "ok"
```

`git blame -L <doc-span>` finds when the docstring region was last edited; `git log
<doc-sha>..HEAD -- <file>` counts code commits since. `stale` when there is no
docstring, or `code_commits_since >= STALE_COMMIT_THRESHOLD` (5). No git (or an
untracked file) degrades gracefully — a missing docstring is still reported.

**Import tagging logic:**
1. Check if the module name matches a local file path → `local`
2. Check against `sys.stdlib_module_names` (Python 3.10+) → `stdlib`
3. Otherwise → `package`

**Key functions:**
- `parse_file(path: Path) -> ParsedFile`
- `parse_repo(root: Path, exclude: list[str]) -> dict[str, ParsedFile]`

---

## Index: `index.py`

Maintains a live map from file path → `ParsedFile`.

Maintains two maps: `path → ParsedFile` (`.py`) and `path → DocFile` (everything
else, via `docparser`). `all_docs()` / `get_doc()` mirror `all_files()` /
`get_file()`.

**Incremental refresh:** stores `mtime` per file (and per doc). On
`index.refresh()`, only files whose mtime changed are re-parsed. `.py` changes
trigger a full re-parse (import classification is cross-file); doc files have no
cross-file deps, so only the changed/removed docs are updated.

**Caching:** the index is serializable to `.codemapper_cache.json` (schema
`version: 2`, now including `doc_mtimes` + `docs`) at the repo root. On startup, if
the cache exists and matches the version, entries are loaded and only stale ones
re-parsed; a version mismatch forces a clean rebuild.

**Staleness** is computed on demand (it depends on git history, not mtime) and is
deliberately **not** part of the cached hot path.

**Key class:**

```python
class CodeIndex:
    def __init__(self, root: Path): ...
    def build(self) -> None           # full parse
    def refresh(self) -> None         # incremental re-parse
    def get_file(self, path: str) -> ParsedFile | None
    def all_files(self) -> list[str]
    def get_doc(self, path: str) -> DocFile | None     # non-.py files
    def all_docs(self) -> list[str]
    def find_symbol(self, name: str) -> list[SymbolLocation]
    def find_usages(self, name: str) -> list[UsageLocation]
    def find_imports(self, module: str) -> list[str]   # file paths
    def search(self, query: str) -> list[SymbolMatch]  # fuzzy match
    def packages(self) -> list[PackageInfo]
```

---

## Session: `session.py`

Tracks what the agent has already been shown. Enables the "expand" model:
instead of returning the full map every time, `session.expand()` returns
only the delta — new information not yet disclosed.

```python
class Session:
    def __init__(self, index: CodeIndex): ...
    def expand(self, path: str, level: int) -> dict   # delta only
    def reset(self) -> None
    def snapshot(self) -> dict   # full current disclosed state
```

Sessions are ephemeral by default (in-memory). A session file path can be
passed to persist across CLI calls.

---

## API: `api.py`

FastAPI application. Instantiates a `CodeIndex` at startup, holds it in app
state. All endpoints return JSON.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/map` | Repo map. `?level=0\|1\|2`, `?include_docs=true` to append a non-`.py` block |
| GET | `/file/{path}` | Single file detail. `?level=0\|1\|2`; `module_doc_full` at level ≥1 |
| GET | `/docfiles` | Non-`.py` files. `?level=0` (kind only) `\|1` (keys/headings/wikilinks) |
| GET | `/doc/{path}` | Single non-`.py` file detail (full `DocFile`) |
| GET | `/staleness` | Docstring drift findings + `stale_count` |
| GET | `/analyze` | Quality analysis. `?scope=dead,complexity,deps` (default: all three) |
| GET | `/symbol/{name}` | Definition location(s) for a symbol |
| GET | `/usages/{name}` | All usage locations for a symbol |
| GET | `/imports/{module}` | Files that import a given module |
| GET | `/search` | Fuzzy symbol search. `?q=<query>` |
| GET | `/packages` | Installed packages + files that use each one |
| POST | `/session/new` | Create a new session, returns `session_id` |
| POST | `/session/{id}/expand` | Expand path to level, returns delta |

> Note: `/docs` is reserved by FastAPI for the Swagger UI, so the non-`.py`
> listing endpoint is `/docfiles`.

The CLI counterparts (`codemapper docfiles`, `codemapper doc`, `codemapper
staleness`, `codemapper map --include-docs`) are **delegated to the dedicated CLI
agent** and wired over these same core functions.

### Response shape (example `/map?level=1`)

```json
{
  "root": "/path/to/repo",
  "files": {
    "codemapper/parser.py": {
      "module_doc": "AST-based Python file parser",
      "symbols": [
        {"name": "Symbol", "kind": "class", "line": 12},
        {"name": "ParsedFile", "kind": "class", "line": 24},
        {"name": "parse_file", "kind": "function", "line": 40}
      ]
    }
  }
}
```

---

## CLI: `cli.py`

Typer application. Entry point registered as `codemapper` in `pyproject.toml`.

All commands accept `--json` to emit machine-readable output (used by Claude
Code bash tool calls) and print human-readable `rich` output otherwise.

### Commands

```
codemapper serve [--port 8000] [--root PATH]
codemapper map [--level 0-2] [--json] [--root PATH]
codemapper inspect <path> [--level 1] [--json]
codemapper find <symbol> [--json]
codemapper usages <symbol> [--json]
codemapper imports <module> [--json]
codemapper search <query> [--json]
codemapper packages [--json]
codemapper session new [--save PATH]
codemapper session expand <path> --level N [--session PATH] [--json]
```

The CLI can operate in two modes:
1. **Standalone** — calls core directly (no server needed, fast, synchronous)
2. **Client mode** — calls a running `codemapper serve` over HTTP (`--url http://localhost:8000`)

Default is standalone. Client mode is for integrations that need a persistent
index (e.g. an IDE plugin or a long-running agent session).

---

## Data Flow: Agent makes a `map` call

```
1. Agent runs: codemapper map --level 1 --json
2. CLI: checks for .codemapper_cache.json, loads or builds CodeIndex
3. CodeIndex.all_files() → iterate ParsedFile for each
4. Format output at level 1: names only, no signatures
5. Print JSON to stdout
6. Agent receives structured map, picks files of interest
7. Agent runs: codemapper inspect src/parser.py --level 2 --json
8. CLI: CodeIndex.get_file("src/parser.py"), format at level 2
9. Agent sees signatures, picks the function it needs
10. Agent runs its own grep/read for the actual implementation
```

---

## Dependency Notes

| Package | Why |
|---------|-----|
| `fastapi` + `uvicorn` | API server with auto-generated OpenAPI docs |
| `typer` | CLI with automatic `--help` generation |
| `rich` | Human-readable terminal output (tables, trees) |
| `ast` (stdlib) | Python source parsing — no external dep needed for v1 |
| `pytest` + `httpx` | Testing (httpx is FastAPI's recommended test client) |
| `watchdog` (optional) | File system events for live index refresh in watch mode |

---

## Testing Strategy

- `tests/test_parser.py` — unit tests for AST extraction on fixture `.py` files
- `tests/test_index.py` — index build + incremental refresh
- `tests/test_api.py` — FastAPI endpoints via `httpx.AsyncClient`
- `tests/test_cli.py` — CLI commands via `typer.testing.CliRunner`
- `tests/test_analysis.py` — per-analyzer + orchestrator on synthetic `tmp_path` repos

Fixture files live in `tests/fixtures/` — small synthetic Python files that
exercise all symbol types.
