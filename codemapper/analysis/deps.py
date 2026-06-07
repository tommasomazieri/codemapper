"""Dependency hygiene analyzer: unused imports, unused/undeclared deps."""

import ast
import re
from pathlib import Path

from codemapper.analysis.findings import Action, Finding
from codemapper.analysis.util import (
    import_to_dist,
    normalize_pkg_name,
    read_pyproject,
)
from codemapper.index import CodeIndex


def _parse_dep_names(dep_list: list[str]) -> set[str]:
    """Extract normalized package names from PEP 508 dependency specs."""
    names: set[str] = set()
    for spec in dep_list:
        name = re.split(r"[>=<!;\[\s]", spec.strip())[0].strip()
        if name:
            names.add(normalize_pkg_name(name))
    return names


def _declared_deps(pyproject: dict) -> set[str]:
    """All normalized dep names from [project].dependencies + optional-dependencies."""
    project = pyproject.get("project", {})
    deps = list(project.get("dependencies", []))
    for extra_deps in project.get("optional-dependencies", {}).values():
        deps.extend(extra_deps)
    return _parse_dep_names(deps)


def _bound_name(imp) -> str | None:
    """The name bound in the local namespace for an ImportInfo."""
    if imp.alias is not None:
        return imp.alias
    if imp.module:
        return imp.module.split(".")[0]
    return None  # relative import with no module — skip


def _file_body_refs(tree: ast.Module) -> set[str]:
    """All ast.Name.id references in a file (includes __all__ string entries)."""
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                refs.add(elt.value)
    return refs


def _has_noqa(line: str) -> bool:
    return "# noqa" in line or "# codemapper:ignore" in line


def _module_to_path(module: str) -> list[str]:
    """Candidate index paths for a local module name."""
    base = module.replace(".", "/")
    return [base + ".py", base + "/__init__.py"]


def find_dependency_issues(index: CodeIndex, root: Path) -> list[Finding]:  # noqa: C901
    findings: list[Finding] = []
    pyproject = read_pyproject(root)
    declared = _declared_deps(pyproject)
    all_files = index.all_files()

    # Collect all package-kind imports repo-wide (for unused/undeclared dep checks).
    imported_pkg_names: set[str] = set()  # normalized top-level import names
    for path_key in all_files:
        pf = index.get_file(path_key)
        if pf is None:
            continue
        for imp in pf.imports:
            if imp.kind == "package" and imp.module:
                top = imp.module.split(".")[0]
                imported_pkg_names.add(normalize_pkg_name(top))

    # ── unused_dependency ──────────────────────────────────────────────────
    if declared:
        for dep in sorted(declared):
            # Check if the dep is imported anywhere (via normalized alias mapping)
            used = dep in imported_pkg_names
            if not used:
                # Try the reverse alias (dist name → import name)
                used = any(
                    normalize_pkg_name(import_to_dist(n)) == dep
                    for n in imported_pkg_names
                )
            if not used:
                findings.append(Finding(
                    rule="unused_dependency",
                    severity="info",
                    path="pyproject.toml",
                    symbol=dep,
                    message=f"Declared dependency '{dep}' is never imported",
                    actions=[Action(kind="remove_dependency", auto_fixable=True)],
                ))

    # ── undeclared_dependency ──────────────────────────────────────────────
    for norm_import in sorted(imported_pkg_names):
        dist_name = import_to_dist(norm_import)
        if dist_name not in declared and norm_import not in declared:
            findings.append(Finding(
                rule="undeclared_dependency",
                severity="warn",
                path="pyproject.toml",
                symbol=norm_import,
                message=(
                    f"Package '{norm_import}' is imported but not declared in"
                    " [project].dependencies"
                ),
                actions=[Action(kind="add_dependency", auto_fixable=True)],
            ))

    # ── per-file: unused_import + unresolved_import ────────────────────────
    for path_key in all_files:
        pf = index.get_file(path_key)
        if pf is None:
            continue

        is_init = Path(path_key).name == "__init__.py"

        abs_path = root / Path(path_key)
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(abs_path))
        except (OSError, SyntaxError):
            continue

        source_lines = source.splitlines()
        body_refs = _file_body_refs(tree)

        # Module-level imports only (skip scoped)
        for imp in pf.imports:
            if imp.scope is not None:
                continue

            # ── unresolved_import ──────────────────────────────────────────
            if imp.kind == "local" and imp.module:
                resolved = any(index.get_file(p) is not None for p in _module_to_path(imp.module))
                if not resolved:
                    findings.append(Finding(
                        rule="unresolved_import",
                        severity="error",
                        path=path_key,
                        line=imp.line,
                        symbol=imp.module,
                        message=(
                            f"Local import '{imp.module}' does not resolve"
                            " to any indexed file"
                        ),
                    ))

            # ── unused_import ──────────────────────────────────────────────
            if is_init:
                continue  # __init__.py re-exports are intentional

            bound = _bound_name(imp)
            if bound is None:
                continue
            if bound == "*":
                continue  # wildcard imports — skip

            # Respect noqa/ignore annotations on the import line
            if 0 < imp.line <= len(source_lines) and _has_noqa(source_lines[imp.line - 1]):
                continue

            if bound not in body_refs:
                findings.append(Finding(
                    rule="unused_import",
                    severity="warn",
                    path=path_key,
                    line=imp.line,
                    symbol=bound,
                    message=f"Imported name '{bound}' is never used in this file",
                    actions=[Action(kind="remove_import", auto_fixable=True)],
                    metadata={"module": imp.module},
                ))

    return findings
