# fallow-for-python — quality analyzer (core trio shipped; advanced passes deferred)

The **core trio** (dead code, complexity, dependency hygiene) is **implemented** as
`codemapper/analysis/` — a report-only subpackage, exposed at `GET /analyze`.
This document records the deferred analyzers and the thinking behind the design.

## Where it comes from

[`fallow`](https://github.com/fallow-rs/fallow) is a Rust, TS/JS **deterministic,
graph-based code-quality analyzer**: dead code, duplication, complexity,
dependency hygiene, PR change-risk, architecture violations. Its defining property
is **"no AI inside the analyzer"** — every finding is a deterministic, traceable
fact, which is exactly what stops AI-generated slop from shipping silently. fallow
is JS-only, so we can't use it directly; we want the same *idea* for Python.

The v1 work (the deterministic context layer + git-based docstring staleness, see
`architecture.md`) already ports fallow's *philosophy* and its drift-detection
seed. **fallow-for-python** is the larger analyzer that would sit on top of it.

## Goal

A deterministic, AI-free Python quality analyzer that reuses the existing
`CodeIndex`, the doc index, and `staleness.py`, and is exposed through the same
shared-core → API → CLI shape (no new architecture).

## Candidate analyzers

Each maps to a fallow feature, implemented with the stdlib `ast` + git:

| Analyzer | How (deterministic) | Reuses |
|----------|---------------------|--------|
| **Dead code** | Unreferenced top-level defs / unused files via reachability from entry points | `index.find_usages`, import graph |
| **Duplication** | AST-token suffix-array clone detection (not pairwise) | `parser` token stream |
| **Complexity** | Cyclomatic + cognitive complexity per function via `ast` | `parser` |
| **Dependency hygiene** | unused / unresolved / unlisted imports vs `pyproject.toml` | import classification, doc index (`pyproject.toml` keys) |
| **Change-risk / hotspots** | git churn × complexity, with introduced-vs-pre-existing attribution | `staleness.py` git helpers |

## Anti-slop contract (ported from fallow)

- **No AI in the analyzer.** Findings are deterministic and reproducible.
- **Traceable.** Each finding says whether it was *introduced* by the current
  change or *pre-existing* (git attribution), so regressions can't slip in silently.
- **Actionable.** Each finding carries an `actions[]` list with an `auto_fixable`
  boolean, mirroring fallow's agent self-correction model.

## Proposed surface (sketch, not final)

```
GET /analyze?scope=all|dead|dupes|complexity|deps|risk
GET /audit                       # PR gate: pass | warn | fail with attribution
codemapper analyze [--scope ...] [--json]
codemapper audit [--json]
```

Example finding shape:

```json
{
  "rule": "dead_code",
  "path": "codemapper/legacy.py",
  "symbol": "old_helper",
  "line": 88,
  "introduced": false,
  "actions": [{"kind": "remove_symbol", "auto_fixable": true}]
}
```

## Why deferred

v1 deliberately ships the *context* layer first: it is closer to the current code,
directly helps agents writing Python, and provides the index/git plumbing this
analyzer depends on. Build that, dogfood it, then layer the analyzer on top.
