"""Progressive disclosure session state."""

import json
from dataclasses import asdict
from pathlib import Path

from codemapper.index import CodeIndex
from codemapper.parser import ParsedFile


def _method_dict(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "line": sym.line, "decorators": sym.decorators}
    if level >= 2:
        d["signature"] = sym.signature
    return d


def _func_dict(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "line": sym.line, "decorators": sym.decorators}
    if level >= 2:
        d["signature"] = sym.signature
    return d


def _grouped_symbols(pf: ParsedFile, level: int) -> dict:
    classes_by_name: dict[str, dict] = {}
    functions: list[dict] = []
    constants: list[dict] = []

    for sym in pf.symbols:
        if sym.kind == "class":
            classes_by_name[sym.name] = {
                "name": sym.name,
                "line": sym.line,
                "decorators": sym.decorators,
                "methods": [],
            }
        elif sym.kind == "function":
            functions.append(_func_dict(sym, level))
        elif sym.kind == "constant":
            constants.append({"name": sym.name, "line": sym.line})

    for sym in pf.symbols:
        if sym.kind == "method" and sym.parent and sym.parent in classes_by_name:
            classes_by_name[sym.parent]["methods"].append(_method_dict(sym, level))

    result: dict = {}
    if constants:
        result["constants"] = constants
    if functions:
        result["functions"] = functions
    if classes_by_name:
        result["classes"] = list(classes_by_name.values())
    return result


def _format_file(pf: ParsedFile, level: int) -> dict:
    result: dict = {"module_doc": pf.module_doc}
    if level >= 1:
        result.update(_grouped_symbols(pf, level))
    return result


class Session:
    def __init__(
        self,
        index: CodeIndex,
        session_id: str,
        save_path: Path | None = None,
    ) -> None:
        self.index = index
        self.session_id = session_id
        self.save_path = save_path
        self._seen: dict[str, int] = {}  # path -> max level disclosed

    def expand(self, path: str, level: int) -> dict:
        pf = self.index.get_file(path)
        if pf is None:
            return {
                "session_id": self.session_id,
                "path": path,
                "level": level,
                "delta": None,
                "error": f"File not found in index: {path}",
            }

        prev_level = self._seen.get(path, -1)

        if level <= prev_level:
            return {"session_id": self.session_id, "path": path, "level": level, "delta": None}

        delta = self._compute_delta(pf, prev_level, level)
        self._seen[path] = level

        if self.save_path:
            self._persist()

        return {"session_id": self.session_id, "path": path, "level": level, "delta": delta}

    def reset(self) -> None:
        self._seen.clear()
        if self.save_path:
            self._persist()

    def snapshot(self) -> dict:
        return {"session_id": self.session_id, "seen": dict(self._seen)}

    def _compute_delta(self, pf: ParsedFile, from_level: int, to_level: int) -> dict:
        delta: dict = {}

        # Level 0 fields newly available
        if from_level < 0:
            delta["module_doc"] = pf.module_doc
            global_imports = [asdict(i) for i in pf.imports if i.scope is None]
            scoped_imports = [asdict(i) for i in pf.imports if i.scope is not None]
            delta["imports"] = {"global": global_imports, "scoped": scoped_imports}

        # Crossing into level >= 1: add full docstring + grouped structure
        # (signatures included when to_level >= 2, e.g. a direct 0 -> 2 jump).
        if from_level < 1 <= to_level:
            delta["module_doc_full"] = pf.module_doc_full
            delta.update(_grouped_symbols(pf, to_level))

        # Level 2 upgrade from level 1 — add signatures to what's already known
        elif from_level < 2 <= to_level and from_level >= 1:
            sigs: dict[str, str | None] = {}
            for s in pf.symbols:
                if s.kind in ("function", "method") and s.signature:
                    sigs[s.name] = s.signature
            if sigs:
                delta["signatures"] = sigs

        return delta

    def _persist(self) -> None:
        assert self.save_path is not None
        self.save_path.write_text(
            json.dumps({"session_id": self.session_id, "seen": self._seen}, indent=2),
            encoding="utf-8",
        )
