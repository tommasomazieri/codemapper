"""Progressive disclosure session state."""

import json
from dataclasses import asdict
from pathlib import Path

from codemapper.index import CodeIndex
from codemapper.parser import ParsedFile


def _format_symbol(sym, level: int) -> dict:
    d: dict = {"name": sym.name, "kind": sym.kind, "line": sym.line}
    if level >= 2:
        d["signature"] = sym.signature
        d["parent"] = sym.parent
    return d


def _format_file(pf: ParsedFile, level: int) -> dict:
    result: dict = {"module_doc": pf.module_doc}
    if level >= 1:
        result["symbols"] = [_format_symbol(s, level) for s in pf.symbols]
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
            delta["imports"] = [asdict(i) for i in pf.imports]

        # Level 1 adds symbols (without signatures)
        if from_level < 1 <= to_level:
            delta["symbols"] = [
                {"name": s.name, "kind": s.kind, "line": s.line}
                for s in pf.symbols
            ]

        # Level 2 adds signatures to existing symbols
        if from_level < 2 <= to_level and from_level >= 1:
            sigs = {s.name: s.signature for s in pf.symbols if s.signature}
            if sigs:
                delta["signatures"] = sigs

        # Level 2 when jumping directly from <1 — include full symbol objects
        if from_level < 1 and to_level >= 2:
            delta["symbols"] = [
                {"name": s.name, "kind": s.kind, "line": s.line, "signature": s.signature, "parent": s.parent}
                for s in pf.symbols
            ]

        return delta

    def _persist(self) -> None:
        assert self.save_path is not None
        self.save_path.write_text(
            json.dumps({"session_id": self.session_id, "seen": self._seen}, indent=2),
            encoding="utf-8",
        )
