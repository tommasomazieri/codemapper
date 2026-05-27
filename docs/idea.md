# codemapper — Product Specification

## Problem

LLM agents working on large codebases waste tokens. To answer a simple
structural question — "where is `MyClass` defined?", "what methods does
`UserService` have?", "which files import `requests`?" — the agent currently
has no choice but to load entire files, grep with limited context, or explore
blindly. This is slow, token-heavy, and error-prone.

Tools like `grep` help once the agent already knows what to look for. But
discovery — building a mental model of an unknown codebase — is the expensive
part. The agent scouts around, loads files one by one, and wastes most of its
context window on boilerplate it doesn't need.

## Solution

**codemapper** is a local Python service that sits *between* the agent and the
codebase. It pre-parses the repo and maintains a symbol index. The agent
queries codemapper first — getting back precise, minimal-token answers — and
only reaches for raw files when it actually needs to read or edit them.

The core model is **progressive disclosure**: the agent starts with a bird's
eye view and zooms in only where needed.

---

## Progressive Disclosure

Each file (and the repo as a whole) can be queried at three levels of detail:

| Level | Name | What it shows |
|-------|------|---------------|
| **0** | overview | File tree with one-line module description (from module docstring) |
| **1** | structure | Top-level symbol names: classes, free functions, constants |
| **2** | signatures | Like L1, plus full signatures: `func(param: type, ...) -> return` |

The agent starts at level 0 to understand the shape of the repo, then
calls level 1 or 2 on specific files it wants to understand. Full source
reading (docstrings, implementation) is deliberately out of scope — the agent
uses its own grep/read tools for that. codemapper stops at the structural
boundary.

### Example interaction

```
Agent: codemapper map --level 0
→ src/
    parser.py       — AST-based Python file parser
    index.py        — symbol index with mtime-based refresh
    session.py      — progressive disclosure session state
    api.py          — FastAPI REST endpoints
    cli.py          — Typer CLI entry points

Agent: codemapper inspect src/parser.py --level 2
→ parser.py
    imports (local): —
    imports (package): ast [stdlib], pathlib [stdlib]
    class ParsedFile
        __init__(self, path: Path, symbols: list[Symbol]) -> None
        to_dict(self) -> dict
    class Symbol
        __init__(self, name: str, kind: str, line: int, signature: str | None) -> None
    def parse_file(path: Path) -> ParsedFile
    def parse_repo(root: Path) -> dict[str, ParsedFile]
```

The agent now knows exactly what `parser.py` contains without loading a single
line of source.

---

## On-the-go Query Methods

Beyond the map, codemapper exposes targeted lookups that return
deterministic, minimal-token answers:

| Command | What it answers |
|---------|----------------|
| `find <name>` | Where is this symbol defined? (file + line) |
| `usages <name>` | Where is this symbol called or referenced? |
| `imports <module>` | Which local files import this module? |
| `search <query>` | Fuzzy search across all symbol names |
| `packages` | List installed packages in the current env |

These are the queries an agent would otherwise answer by loading and scanning
files manually. codemapper answers them from its index instantly.

---

## Installed Packages Awareness

codemapper is aware of the Python environment:

- `codemapper packages` lists all installed packages (name + version)
- On every file's import section, each import is tagged as:
  - `local` — points to a file in this repo
  - `stdlib` — Python standard library
  - `package` — third-party installed package

This lets the agent quickly see what the project depends on and where each
dependency is actually used, without having to inspect `requirements.txt` or
`pyproject.toml` manually.

**No deep introspection of installed packages.** codemapper surfaces
*presence* and *usage locations*, not the package's own internals. For that,
the agent uses its standard web search or documentation tools.

---

## Architecture Overview

```
[ Agent / Claude Code ]
        │
        ▼  CLI commands (--json output)
[ codemapper CLI ]
        │
        ▼  HTTP calls (optional, for richer integrations)
[ codemapper API ]  ←— FastAPI, runs locally on demand
        │
        ▼
[ codemapper Core ]
    parser.py    — Python AST → symbol extraction
    index.py     — {filepath: ParsedFile}, incremental refresh
    session.py   — progressive disclosure state (ephemeral)
        │
        ▼
[ Target Codebase ]
```

The agent can use codemapper in two ways:
1. **Direct CLI** — call `codemapper map --json` as a bash tool in Claude Code
2. **API server** — `codemapper serve` starts a local FastAPI server; integrations
   can call REST endpoints directly

---

## What codemapper Is NOT

- Not a code editor or file writer
- Not a replacement for grep — targeted text search is still grep's job
- Not a full language server (no type inference, no go-to-definition via LSP)
- Not multi-language in v1 — Python only (extensible later with tree-sitter)
- Not a cloud service — runs entirely locally, on the target machine

---

## Future Extensions (not in v1)

- **Call graph traversal** — "which functions call `process_request`?"
- **Centrality ranking** — aider-style PageRank to surface most-referenced files
- **MCP server mode** — expose codemapper as a proper MCP tool for Claude Code
- **Multi-language support** — add tree-sitter for JS/TS, Go, Rust
- **Watch mode** — `codemapper watch` keeps the index live as files change
