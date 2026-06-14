"""Language detection and source-file bucketing for multi-language diagnostics.

Maps file extensions to a canonical language name and walks a repo into
per-language file lists, honoring the same ignore set the rest of codemapper
uses (so we never descend into vendored / build output).
"""

from pathlib import Path

# extension (lowercase, with dot) -> canonical language
EXT_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
}

# Directory names that are never source we own.
IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "graphify-out", ".next", "coverage", ".mypy_cache",
}


def detect_language(path: str) -> str | None:
    """Canonical language for a path by extension, or None if unsupported."""
    return EXT_LANGUAGE.get(Path(path).suffix.lower())


def _ignored(rel_parts: tuple[str, ...]) -> bool:
    return any(part in IGNORE_DIRS for part in rel_parts)


def collect_files_by_language(root: Path) -> dict[str, list[str]]:
    """Bucket every supported source file under ``root`` by language.

    Returns a dict keyed by language with repo-relative posix paths, e.g.
    ``{"python": ["pkg/a.py"], "typescript": ["src/x.ts"], "html": ["index.html"]}``.
    Languages with no files are omitted.
    """
    root = root.resolve()
    buckets: dict[str, list[str]] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if _ignored(rel.parts):
            continue
        lang = EXT_LANGUAGE.get(p.suffix.lower())
        if lang is None:
            continue
        buckets.setdefault(lang, []).append(rel.as_posix())
    for files in buckets.values():
        files.sort()
    return buckets
