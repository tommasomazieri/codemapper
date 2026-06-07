"""Dead-code analyzer: unreferenced top-level symbols and unimported modules."""

import ast
from pathlib import Path

from codemapper.analysis.findings import Action, Finding
from codemapper.analysis.util import collect_referenced_names, entry_point_roots, read_pyproject
from codemapper.index import CodeIndex

# Decorator attr-names that mark a symbol as a live framework hook.
_FRAMEWORK_DECORATOR_ATTRS = {
    "get", "post", "put", "delete", "patch", "head", "options",  # FastAPI/Flask
    "route",   # Flask
    "fixture", # pytest
    "command", # Typer
    "task",    # Celery
}

_ALWAYS_LIVE_NAMES = {"main"}


def _is_root(name: str, decorators: list[str], extra: set[str]) -> bool:
    if name in _ALWAYS_LIVE_NAMES or name in extra:
        return True
    if name.startswith("test_") or name.startswith("Test"):
        return True
    # decorators look like "@get", "@fixture", "@app.command" etc.
    for dec in decorators:
        attr = dec.lstrip("@").split(".")[-1]
        if attr in _FRAMEWORK_DECORATOR_ATTRS:
            return True
    return False


def _module_name(path_key: str) -> str:
    """'codemapper/parser.py' → 'codemapper.parser'; 'codemapper/__init__.py' → 'codemapper'."""
    if path_key.endswith("/__init__.py") or path_key == "__init__.py":
        return path_key.removesuffix("/__init__.py").removesuffix("__init__.py").replace("/", ".")
    return path_key.removesuffix(".py").replace("/", ".")


def _all_exports(root: Path, py_files: list[str]) -> set[str]:
    """Names listed in any __all__ across the repo."""
    exports: set[str] = set()
    for path_key in py_files:
        try:
            source = (root / Path(path_key)).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    exports.add(elt.value)
    return exports


def find_dead_code(index: CodeIndex, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    pyproject = read_pyproject(root)
    ep_roots = entry_point_roots(pyproject)
    all_files = index.all_files()

    all_refs = collect_referenced_names(root, all_files)
    exports = _all_exports(root, all_files)

    for path_key in all_files:
        pf = index.get_file(path_key)
        if pf is None:
            continue

        stem = Path(path_key).name
        is_init = stem == "__init__.py"
        parts = Path(path_key).parts
        is_test = parts[0] == "tests" or stem.startswith("test_")

        # ── dead_file ──────────────────────────────────────────────────────
        if not is_init and not is_test:
            mod = _module_name(path_key)
            mod_stem = mod.split(".")[-1]
            imported_by = index.find_imports(mod)
            # also try the short stem (handles top-level scripts like main.py)
            if not imported_by and mod != mod_stem:
                imported_by = index.find_imports(mod_stem)
            is_ep = mod_stem in ep_roots or mod_stem in _ALWAYS_LIVE_NAMES
            if not imported_by and not is_ep:
                findings.append(Finding(
                    rule="dead_file",
                    severity="info",
                    path=path_key,
                    message=(
                        f"Module '{path_key}' is never imported by any local file"
                        " (heuristic; may be a top-level entry-point script)"
                    ),
                ))

        # ── dead_code (per symbol) ─────────────────────────────────────────
        for sym in pf.symbols:
            if sym.kind not in ("function", "class"):
                continue
            if sym.parent is not None:
                continue  # methods only — skip
            if sym.name in exports:
                continue
            if _is_root(sym.name, sym.decorators, ep_roots):
                continue
            if sym.name not in all_refs:
                findings.append(Finding(
                    rule="dead_code",
                    severity="warn",
                    path=path_key,
                    line=sym.line,
                    symbol=sym.name,
                    message=(
                        f"Top-level {sym.kind} '{sym.name}' is never referenced"
                        " (heuristic; check for dynamic use)"
                    ),
                    actions=[Action(kind="remove_symbol", auto_fixable=True)],
                    metadata={"kind": sym.kind},
                ))

    return findings
