# codemapper API — Codebase Mapping

Endpoints for obtaining a structural view of the indexed repository.

---

## `GET /map`

Returns a map of the entire repository. Detail level controls how much information is included per file.

### Query parameters

| Parameter | Type | Required | Values | Default |
|-----------|------|----------|--------|---------|
| `level` | int | no | 0, 1, 2 | 0 |

### Level semantics

| Level | Name | What is included |
|-------|------|-----------------|
| 0 | overview | `module_doc` per file only |
| 1 | structure | Adds `symbols` list with `name`, `kind`, `line` |
| 2 | signatures | Adds `signature` field on each function/method symbol |

### Examples

```bash
# Level 0 — overview
curl "http://localhost:8000/map?level=0"

# Level 1 — structure
curl "http://localhost:8000/map?level=1"

# Level 2 — full signatures
curl "http://localhost:8000/map?level=2"
```

### Example responses

**Level 0:**

```json
{
  "root": "/home/user/myproject",
  "level": 0,
  "files": {
    "codemapper/__init__.py": {
      "module_doc": null
    },
    "codemapper/parser.py": {
      "module_doc": "AST-based Python file parser."
    },
    "codemapper/index.py": {
      "module_doc": "Repo-wide symbol index with incremental refresh."
    },
    "codemapper/session.py": {
      "module_doc": "Progressive disclosure session state."
    },
    "codemapper/api.py": {
      "module_doc": null
    },
    "codemapper/cli.py": {
      "module_doc": null
    }
  }
}
```

**Level 1:**

```json
{
  "root": "/home/user/myproject",
  "level": 1,
  "files": {
    "codemapper/parser.py": {
      "module_doc": "AST-based Python file parser.",
      "symbols": [
        {"name": "ImportInfo",  "kind": "class",    "line": 12},
        {"name": "Symbol",      "kind": "class",    "line": 22},
        {"name": "ParsedFile",  "kind": "class",    "line": 35},
        {"name": "parse_file",  "kind": "function", "line": 50},
        {"name": "parse_repo",  "kind": "function", "line": 80}
      ]
    },
    "codemapper/index.py": {
      "module_doc": "Repo-wide symbol index with incremental refresh.",
      "symbols": [
        {"name": "SymbolLocation", "kind": "class",    "line": 10},
        {"name": "UsageLocation",  "kind": "class",    "line": 18},
        {"name": "SymbolMatch",    "kind": "class",    "line": 25},
        {"name": "PackageInfo",    "kind": "class",    "line": 31},
        {"name": "CodeIndex",      "kind": "class",    "line": 40}
      ]
    }
  }
}
```

**Level 2** (same shape as level 1, adds `signature` on function/method symbols):

```json
{
  "root": "/home/user/myproject",
  "level": 2,
  "files": {
    "codemapper/parser.py": {
      "module_doc": "AST-based Python file parser.",
      "symbols": [
        {"name": "ImportInfo",  "kind": "class",    "line": 12, "signature": null},
        {"name": "Symbol",      "kind": "class",    "line": 22, "signature": null},
        {"name": "ParsedFile",  "kind": "class",    "line": 35, "signature": null},
        {
          "name": "parse_file",
          "kind": "function",
          "line": 50,
          "signature": "parse_file(path: Path, root: Path | None = None) -> ParsedFile"
        },
        {
          "name": "parse_repo",
          "kind": "function",
          "line": 80,
          "signature": "parse_repo(root: Path) -> dict[str, ParsedFile]"
        }
      ]
    }
  }
}
```

---

## `GET /file/{path}`

Returns detail for a single file. The `{path}` is the file path relative to the repo root, using forward slashes (e.g., `codemapper/parser.py`). Always includes `imports` regardless of level, which distinguishes it from `/map`.

### Path parameters

| Parameter | Description |
|-----------|-------------|
| `path` | File path relative to repo root, e.g. `codemapper/parser.py` |

### Query parameters

| Parameter | Type | Required | Values | Default |
|-----------|------|----------|--------|---------|
| `level` | int | no | 0, 1, 2 | 0 |

### Examples

```bash
# Level 0 — overview + imports
curl "http://localhost:8000/file/codemapper/parser.py?level=0"

# Level 2 — full detail with signatures
curl "http://localhost:8000/file/codemapper/parser.py?level=2"
```

### Example responses

**Level 0** (includes imports at all levels):

```json
{
  "path": "codemapper/parser.py",
  "level": 0,
  "module_doc": "AST-based Python file parser.",
  "imports": [
    {"module": "ast",         "alias": null,        "kind": "stdlib",  "line": 1},
    {"module": "pathlib",     "alias": "Path",      "kind": "stdlib",  "line": 2},
    {"module": "dataclasses", "alias": "dataclass", "kind": "stdlib",  "line": 3},
    {"module": "sys",         "alias": null,        "kind": "stdlib",  "line": 4}
  ],
  "symbols": []
}
```

**Level 2** (full detail):

```json
{
  "path": "codemapper/parser.py",
  "level": 2,
  "module_doc": "AST-based Python file parser.",
  "imports": [
    {"module": "ast",         "alias": null,        "kind": "stdlib",  "line": 1},
    {"module": "pathlib",     "alias": "Path",      "kind": "stdlib",  "line": 2},
    {"module": "dataclasses", "alias": "dataclass", "kind": "stdlib",  "line": 3},
    {"module": "sys",         "alias": null,        "kind": "stdlib",  "line": 4}
  ],
  "symbols": [
    {"name": "ImportInfo",  "kind": "class",    "line": 12, "signature": null,   "parent": null},
    {"name": "Symbol",      "kind": "class",    "line": 22, "signature": null,   "parent": null},
    {"name": "ParsedFile",  "kind": "class",    "line": 35, "signature": null,   "parent": null},
    {
      "name": "parse_file",
      "kind": "function",
      "line": 50,
      "signature": "parse_file(path: Path, root: Path | None = None) -> ParsedFile",
      "parent": null
    },
    {
      "name": "parse_repo",
      "kind": "function",
      "line": 80,
      "signature": "parse_repo(root: Path) -> dict[str, ParsedFile]",
      "parent": null
    }
  ]
}
```

### Error responses

**404 — file not found in index:**

```json
{"detail": "File not found in index: codemapper/missing.py"}
```
