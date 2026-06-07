"""Shared utilities for analysis passes."""

import ast
import re
from pathlib import Path
from typing import Iterator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def read_pyproject(root: Path) -> dict:
    """Return pyproject.toml as a dict, or {} if absent/unparseable."""
    path = root / "pyproject.toml"
    if tomllib is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def iter_functions(
    tree: ast.AST,
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, int]]:
    """Yield (qualname, node, lineno) for top-level functions and class methods."""

    def _walk(
        stmts: list, prefix: str
    ) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, int]]:
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{node.name}" if prefix else node.name
                yield qualname, node, node.lineno
            elif isinstance(node, ast.ClassDef):
                cls_prefix = f"{prefix}{node.name}." if prefix else f"{node.name}."
                yield from _walk(node.body, cls_prefix)

    if isinstance(tree, ast.Module):
        yield from _walk(tree.body, "")


def collect_referenced_names(root: Path, py_files: list[str]) -> set[str]:
    """All ast.Name.id / ast.Attribute.attr values used in repo + __all__ strings."""
    names: set[str] = set()
    for path_key in py_files:
        abs_path = root / Path(path_key)
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(abs_path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.add(elt.value)
    return names


def entry_point_roots(pyproject: dict) -> set[str]:
    """Function names declared as [project.scripts] entry-point targets."""
    roots: set[str] = set()
    for target in pyproject.get("project", {}).get("scripts", {}).values():
        # "codemapper.cli:app" → "app"
        if ":" in target:
            roots.add(target.split(":")[-1])
    return roots


def normalize_pkg_name(name: str) -> str:
    """Canonical package name: lowercase, dashes and underscores unified."""
    return re.sub(r"[-_]", "_", name.lower())


# Common import-name → distribution-name mappings where they differ.
_IMPORT_TO_DIST: dict[str, str] = {
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "pil": "pillow",
    "cv2": "opencv_python",
    "sklearn": "scikit_learn",
    "dateutil": "python_dateutil",
    "attr": "attrs",
    "dotenv": "python_dotenv",
    "serial": "pyserial",
    "jwt": "pyjwt",
    "boto": "boto3",
    "openssl": "pyopenssl",
    "crypto": "pycryptodome",
    "magic": "python_magic",
}


def import_to_dist(import_name: str) -> str:
    """Best-effort mapping from import name to distribution name (normalized)."""
    norm = normalize_pkg_name(import_name)
    return _IMPORT_TO_DIST.get(norm, norm)
