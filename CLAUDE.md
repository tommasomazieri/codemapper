# codemapper 2.0

A unified codebase-intelligence tool for AI agents. It combines **Graphify**'s
relational knowledge graph (architecture, communities, importance) with
**codemapper**'s deterministic diagnostics (dead code, complexity, dependency
hygiene, docstring staleness), and serves the result to Claude Code through a
single MCP server. One interface; the agent never talks to Graphify directly.

## How the pieces fit

```
Claude Code  ──MCP (one server)──▶  mcp_server.py
                                        ├─ graph nav:  graph_index.py  (NetworkX on graph_annotated.json)
                                        ├─ traversal:  graphify_runner.py → graphify (subprocess)
                                        └─ diagnostics: analysis/ + staleness.py + python_depth.py

build pipeline:
  graphify_runner.build()  → graphify extract  → graphify-out/graph.json
  annotator.annotate()     → joins codemapper findings onto nodes → graph_annotated.json
```

## Stack

- Python 3.12 (graphify's tree-sitter wheels are cp312; do not use 3.13)
- `graphifyy` — the knowledge-graph engine (called as a subprocess, never imported)
- `openai` — required for graphify's OpenAI-compatible backend (OpenRouter)
- `mcp` (FastMCP) — the Claude Code-facing server
- `networkx` — graph queries; FastAPI + Typer + rich for the optional REST API / CLI
- Built-in `ast` — Python diagnostics + type-annotated signatures

## LLM backend (OpenRouter, free)

The semantic pass runs on `openai/gpt-oss-120b:free` via OpenRouter.
`graphify_runner` auto-registers an `openrouter` custom provider in
`~/.graphify/providers.json` (key-free, via `env_key`) and reads
`OPENROUTER_API_KEY` from `api_config.json` at the project root, injecting it into
the subprocess env. **Never read or print `api_config.json` contents** — it holds
private keys. Code-only repos can build fully offline with `--no-llm`.

## Key files

- `graphify_runner.py` — the only file that knows graphify exists: `build`, `query`, `path_query`, provider registration, key handling
- `graph_index.py` — reads `graph_annotated.json`; `get_god_nodes` (ranked by **degree**, graphify's importance metric), `get_community`, `get_neighbors(relation=...)`
- `annotator.py` — joins findings onto graph nodes by (source_file, label/line) → `graph_annotated.json`
- `mcp_server.py` — FastMCP stdio server (the single Claude Code interface); all tools run in-process
- `python_depth.py` — type-annotated Python signatures (Tree-sitter can't give these)
- `analysis/` — deterministic analyzers (dead code, complexity, deps); `staleness.py` — git docstring drift
- `index.py`, `parser.py` — AST substrate for the analyzers and python_depth
- `api.py` — optional standalone REST surface (not required by the MCP path)
- `cli.py` — `setup`, `build`, `serve [--mcp]`, `diagnose`, `god-nodes`
- `hook.py` — PreToolUse hook that nudges Claude toward the graph

## MCP tools

`build`, `god_nodes` (filterable by complexity/staleness/dead), `explore(query)`,
`community`, `neighbors`, `path_between`, `diagnose`, `python_sig`.

## Setup on a target repo

The `codemapper-setup` skill (user-level) runs:
```
<venv python> -m codemapper.cli setup <project>
```
which writes `.mcp.json` (project-scoped MCP server), merges a `PreToolUse[Grep|Glob]`
hook into `.claude/settings.json`, and builds the annotated graph. Idempotent.

## Real edge relations (for analyzer adapters)

`contains`, `method`, `calls`, `uses`, `imports`/`imports_from`, `references`,
`implements`, `inherits`, `rationale_for` (semantic). Node `file_type`:
`code` | `rationale` | `document`. Node degree = importance.

## Status

Phase 1 (core restructure) + Phase 2 (annotator, graph schema) + Python depth +
servers + setup wiring are done and validated against `../geneticmon`. Deferred:
adapting `deadcode.py`/`deps.py` to traverse graph edges for multi-language
diagnostics (the Python AST analyzers already work and annotate correctly).

## Code navigation rule

For any code exploration, search, or navigation, use the codemapper2 MCP tools
(`explore`, `god_nodes`, `neighbors`, `community`, `path_between`, `diagnose`, `python_sig`).
Do NOT use Bash grep/find/cat/rg or Read to explore code structure. Read is only
acceptable for a specific already-known file path needed directly.
