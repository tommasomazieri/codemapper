"""Repo-wide symbol index with incremental refresh."""

import ast
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from codemapper.docparser import DocFile, is_indexable_doc, parse_doc, parse_docs
from codemapper.parser import ImportInfo, ParsedFile, Symbol, parse_repo


@dataclass
class SymbolLocation:
    file: str
    name: str
    kind: str
    line: int
    parent: str | None


@dataclass
class UsageLocation:
    file: str
    line: int
    context: str  # stripped source line


@dataclass
class SymbolMatch:
    file: str
    name: str
    kind: str
    line: int


@dataclass
class PackageInfo:
    name: str
    version: str
    used_in: list[str]


_CACHE_VERSION = 2
_CACHE_FILE = ".codemapper_cache.json"


def _pf_to_dict(pf: ParsedFile) -> dict:
    return asdict(pf)


def _dict_to_pf(d: dict) -> ParsedFile:
    return ParsedFile(
        path=d["path"],
        module_doc=d["module_doc"],
        imports=[ImportInfo(**i) for i in d["imports"]],
        symbols=[Symbol(**s) for s in d["symbols"]],
        module_doc_full=d.get("module_doc_full"),
        doc_start_line=d.get("doc_start_line"),
        doc_end_line=d.get("doc_end_line"),
    )


def _dict_to_doc(d: dict) -> DocFile:
    return DocFile(
        path=d["path"],
        kind=d["kind"],
        top_keys=d.get("top_keys", []),
        headings=d.get("headings", []),
        wikilinks=d.get("wikilinks", []),
    )


class CodeIndex:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._files: dict[str, ParsedFile] = {}
        self._mtimes: dict[str, float] = {}
        self._docs: dict[str, DocFile] = {}
        self._doc_mtimes: dict[str, float] = {}

    def build(self) -> None:
        self._files = parse_repo(self.root)
        self._mtimes = self._current_mtimes()
        self._docs = parse_docs(self.root)
        self._doc_mtimes = self._current_doc_mtimes()
        self._save_cache()

    def refresh(self) -> None:
        if not self._load_cache():
            self.build()
            return

        dirty = False

        # --- Python files ---
        current = self._current_mtimes()
        stale = [p for p, mt in current.items() if self._mtimes.get(p) != mt]
        removed = [p for p in list(self._files) if p not in current]

        for path_key in removed:
            del self._files[path_key]
        if removed:
            dirty = True

        if stale:
            # Classification is cross-file (local stems come from all files), so a
            # single changed .py means re-running the full parse+classify pass.
            self._files = parse_repo(self.root)
            dirty = True
        self._mtimes = current

        # --- Non-Python doc files (no cross-file deps → incremental) ---
        current_docs = self._current_doc_mtimes()
        stale_docs = [p for p, mt in current_docs.items() if self._doc_mtimes.get(p) != mt]
        removed_docs = [p for p in list(self._docs) if p not in current_docs]

        for path_key in removed_docs:
            del self._docs[path_key]
        for path_key in stale_docs:
            doc = parse_doc(self.root / Path(path_key), self.root)
            self._docs[doc.path] = doc
        if removed_docs or stale_docs:
            dirty = True
        self._doc_mtimes = current_docs

        if dirty:
            self._save_cache()

    def get_file(self, path: str) -> ParsedFile | None:
        return self._files.get(path)

    def all_files(self) -> list[str]:
        return sorted(self._files.keys())

    def get_doc(self, path: str) -> DocFile | None:
        return self._docs.get(path)

    def all_docs(self) -> list[str]:
        return sorted(self._docs.keys())

    def find_symbol(self, name: str) -> list[SymbolLocation]:
        results: list[SymbolLocation] = []
        for pf in self._files.values():
            for sym in pf.symbols:
                if sym.name == name:
                    results.append(SymbolLocation(
                        file=pf.path,
                        name=sym.name,
                        kind=sym.kind,
                        line=sym.line,
                        parent=sym.parent,
                    ))
        return results

    def find_usages(self, name: str) -> list[UsageLocation]:
        results: list[UsageLocation] = []
        for path_key in self._files:
            abs_path = self.root / Path(path_key)
            try:
                source = abs_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(abs_path))
            except (OSError, SyntaxError):
                continue

            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == name:
                    ctx_line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                    results.append(UsageLocation(file=path_key, line=node.lineno, context=ctx_line))
                elif isinstance(node, ast.Attribute) and node.attr == name:
                    ctx_line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                    results.append(UsageLocation(file=path_key, line=node.lineno, context=ctx_line))

        # deduplicate by (file, line)
        seen: set[tuple[str, int]] = set()
        deduped: list[UsageLocation] = []
        for u in results:
            key = (u.file, u.line)
            if key not in seen:
                seen.add(key)
                deduped.append(u)
        return sorted(deduped, key=lambda u: (u.file, u.line))

    def find_imports(self, module: str) -> list[str]:
        results: list[str] = []
        for pf in self._files.values():
            for imp in pf.imports:
                if imp.module == module or imp.module.startswith(module + "."):
                    results.append(pf.path)
                    break
        return sorted(results)

    def search(self, query: str) -> list[SymbolMatch]:
        q = query.lower()
        results: list[SymbolMatch] = []
        for pf in self._files.values():
            for sym in pf.symbols:
                if q in sym.name.lower():
                    results.append(SymbolMatch(
                        file=pf.path,
                        name=sym.name,
                        kind=sym.kind,
                        line=sym.line,
                    ))
        return sorted(results, key=lambda m: (m.file, m.line))

    def packages(self) -> list[PackageInfo]:
        try:
            import importlib.metadata as meta
        except ImportError:
            return []

        # Collect package imports across all files
        package_files: dict[str, set[str]] = {}
        for pf in self._files.values():
            for imp in pf.imports:
                if imp.kind == "package" and imp.module:
                    top = imp.module.split(".")[0]
                    package_files.setdefault(top, set()).add(pf.path)

        results: list[PackageInfo] = []
        seen: set[str] = set()
        for dist in meta.distributions():
            name = dist.metadata["Name"]
            if not name or name in seen:
                continue
            seen.add(name)
            version = dist.metadata["Version"] or ""
            # Match by normalized name (lowercase, dashes=underscores)
            normalized = name.lower().replace("-", "_")
            used_in = sorted(package_files.get(normalized, set()) | package_files.get(name.lower(), set()))
            results.append(PackageInfo(name=name, version=version, used_in=used_in))

        return sorted(results, key=lambda p: p.name.lower())

    def _current_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for py in self.root.rglob("*.py"):
            if "__pycache__" in py.parts or ".git" in py.parts or ".venv" in py.parts:
                continue
            key = py.relative_to(self.root).as_posix()
            try:
                mtimes[key] = py.stat().st_mtime
            except OSError:
                pass
        return mtimes

    def _current_doc_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        for path in self.root.rglob("*"):
            if not is_indexable_doc(path, self.root):
                continue
            key = path.relative_to(self.root).as_posix()
            try:
                mtimes[key] = path.stat().st_mtime
            except OSError:
                pass
        return mtimes

    def _save_cache(self) -> None:
        cache = {
            "version": _CACHE_VERSION,
            "root": str(self.root),
            "mtimes": self._mtimes,
            "files": {k: _pf_to_dict(v) for k, v in self._files.items()},
            "doc_mtimes": self._doc_mtimes,
            "docs": {k: asdict(v) for k, v in self._docs.items()},
        }
        cache_path = self.root / _CACHE_FILE
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    def _load_cache(self) -> bool:
        cache_path = self.root / _CACHE_FILE
        if not cache_path.exists():
            return False
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        if data.get("version") != _CACHE_VERSION:
            return False
        if data.get("root") != str(self.root):
            return False

        self._mtimes = data.get("mtimes", {})
        self._files = {k: _dict_to_pf(v) for k, v in data.get("files", {}).items()}
        self._doc_mtimes = data.get("doc_mtimes", {})
        self._docs = {k: _dict_to_doc(v) for k, v in data.get("docs", {}).items()}
        return True
