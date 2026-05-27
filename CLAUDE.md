# codemapper

A Python middleware tool that sits between an LLM agent and a codebase.
It pre-parses the repo and exposes a **progressive disclosure API** — the agent
starts with a high-level map and drills down only where needed, minimizing
tokens consumed while maximizing structural awareness.

## Stack

- Python 3.11+
- FastAPI + uvicorn (API layer)
- Typer + rich (CLI layer)
- Built-in `ast` module (parser, Python-only v1)

## Key Directories

- `codemapper/` — main package (parser, index, session, api, cli)
- `docs/` — design docs: `idea.md` (product spec), `architecture.md` (technical design)
- `tests/` — pytest tests

## Running locally

```bash
pip install -e ".[dev]"
codemapper serve          # starts API on localhost:8000
codemapper map            # print repo overview (level 0)
codemapper map --level 2  # with signatures
```

## API docs

FastAPI auto-docs available at http://localhost:8000/docs when server is running.

## Claude Code usage

All CLI commands accept `--json` for machine-readable output, making them
usable as bash tool calls directly from Claude Code.

```bash
codemapper map --json
codemapper inspect codemapper/parser.py --level 2 --json
codemapper find MyClass --json
codemapper packages --json
```

## Progressive disclosure levels

| Level | Name | Shows |
|-------|------|-------|
| 0 | overview | File tree + module docstring (one line) |
| 1 | structure | Top-level names: classes, functions, constants |
| 2 | signatures | Like L1 + `func(param: type) -> return` |

Levels 3+ (docstrings, full source) are intentionally out of scope — use grep/read for those.

## Workflow rules

- **Before planning**: always run `git pull` to ensure the local branch is up to date.
- **After implementing a plan**: always `git add`, `git commit`, and `git push` to persist the work.
