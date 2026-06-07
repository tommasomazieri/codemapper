"""Light, deterministic parser for non-Python files.

Gives agents structural awareness of the *other* files in a repo — config
(JSON/TOML/YAML) and markdown — without any AI. For config files it surfaces
top-level keys; for markdown it surfaces headings and ``[[wikilinks]]``. Every
other file type is listed by path only. Parsing never raises: a malformed file
degrades to an empty summary so the index stays robust.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # stdlib 3.11+
except ModuleNotFoundError:  # pragma: no cover - we target 3.11+
    tomllib = None  # type: ignore[assignment]


_EXCLUDE_PARTS = {"__pycache__", "node_modules"}

_KIND_BY_SUFFIX = {
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".markdown": "markdown",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class DocFile:
    path: str  # relative to repo root, posix slashes
    kind: str  # "json" | "toml" | "yaml" | "markdown" | "other"
    top_keys: list[str] = field(default_factory=list)  # config files only
    headings: list[str] = field(default_factory=list)  # markdown only, e.g. "## Title"
    wikilinks: list[str] = field(default_factory=list)  # markdown only, e.g. "target"


def _kind_for(path: Path) -> str:
    return _KIND_BY_SUFFIX.get(path.suffix.lower(), "other")


def _json_keys(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    return sorted(data.keys()) if isinstance(data, dict) else []


def _toml_keys(text: str) -> list[str]:
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    return sorted(data.keys()) if isinstance(data, dict) else []


def _yaml_keys(text: str) -> list[str]:
    try:
        import yaml  # optional dependency
    except ModuleNotFoundError:
        return []
    try:
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - any YAML error degrades to empty
        return []
    return sorted(data.keys()) if isinstance(data, dict) else []


def _markdown_summary(text: str) -> tuple[list[str], list[str]]:
    headings: list[str] = []
    wikilinks: list[str] = []
    seen_links: set[str] = set()
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            headings.append(f"{m.group(1)} {m.group(2)}")
        for link in _WIKILINK_RE.findall(line):
            target = link.split("|", 1)[0].strip()
            if target and target not in seen_links:
                seen_links.add(target)
                wikilinks.append(target)
    return headings, wikilinks


def parse_doc(path: Path, root: Path | None = None) -> DocFile:
    rel = path.relative_to(root).as_posix() if root else path.name
    kind = _kind_for(path)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return DocFile(path=rel, kind=kind)

    if kind == "json":
        return DocFile(path=rel, kind=kind, top_keys=_json_keys(text))
    if kind == "toml":
        return DocFile(path=rel, kind=kind, top_keys=_toml_keys(text))
    if kind == "yaml":
        return DocFile(path=rel, kind=kind, top_keys=_yaml_keys(text))
    if kind == "markdown":
        headings, wikilinks = _markdown_summary(text)
        return DocFile(path=rel, kind=kind, headings=headings, wikilinks=wikilinks)
    return DocFile(path=rel, kind="other")


def is_indexable_doc(path: Path, root: Path) -> bool:
    """True if ``path`` is a non-Python file worth indexing.

    Skips Python (handled by the AST parser), ``__pycache__``/``node_modules``,
    and anything under a hidden (dot-prefixed) directory or a dotfile — that
    excludes ``.git``, ``.venv``, ``.pytest_cache``, ``.claude``, the cache file,
    etc., which are noise rather than agent context. Only path components *below
    root* are inspected, so a repo that itself lives under a dot-directory still
    indexes. The exclusion is shared with the index so the two can't drift.
    """
    if not path.is_file() or path.suffix == ".py":
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return not any(part in _EXCLUDE_PARTS or part.startswith(".") for part in rel.parts)


def parse_docs(root: Path) -> dict[str, DocFile]:
    docs: dict[str, DocFile] = {}
    for path in root.rglob("*"):
        if not is_indexable_doc(path, root):
            continue
        doc = parse_doc(path, root)
        docs[doc.path] = doc
    return docs
