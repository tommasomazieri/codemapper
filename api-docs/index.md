# codemapper API Documentation

Base URL: `http://localhost:8000`

All endpoints return JSON. No authentication required (local service only).
Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs) (requires running server).

## Endpoints by topic

| File | Endpoints covered |
|------|-------------------|
| [mapping.md](./mapping.md) | `GET /map`, `GET /file/{path}` |
| [symbols.md](./symbols.md) | `GET /symbol/{name}`, `GET /usages/{name}`, `GET /imports/{module}`, `GET /search` |
| [packages.md](./packages.md) | `GET /packages` |
| [sessions.md](./sessions.md) | `POST /session/new`, `POST /session/{id}/expand` |

## Quick reference

| Endpoint | Description |
|----------|-------------|
| `GET /map?level=N` | Repo-wide map at detail level 0–2 |
| `GET /file/{path}?level=N` | Single file detail at level 0–2 |
| `GET /symbol/{name}` | Where a symbol is defined |
| `GET /usages/{name}` | Where a symbol is used |
| `GET /imports/{module}` | Files that import a given module |
| `GET /search?q=` | Fuzzy symbol search |
| `GET /packages` | Installed packages and which files use them |
| `POST /session/new` | Create a progressive-disclosure session |
| `POST /session/{id}/expand` | Expand a file within a session (returns delta only) |
| `POST /refresh` | Re-index the repo (pick up changed files) |

## Progressive disclosure levels

| Level | Name | What is returned |
|-------|------|-----------------|
| 0 | overview | File path + module docstring (one line) |
| 1 | structure | Level 0 + symbol names, kinds, line numbers |
| 2 | signatures | Level 1 + full function/method signatures |
