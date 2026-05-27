"""AST-based Python file parser."""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportInfo:
    module: str
    alias: str | None
    kind: str  # "local" | "stdlib" | "package"
    line: int


@dataclass
class Symbol:
    name: str
    kind: str  # "class" | "function" | "method" | "constant"
    line: int
    signature: str | None
    parent: str | None


@dataclass
class ParsedFile:
    path: str  # relative to repo root, posix slashes
    module_doc: str | None
    imports: list[ImportInfo]
    symbols: list[Symbol]


def _build_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []

    # Build positional + keyword args with their annotations and defaults
    # Defaults are right-aligned to the args list
    n_args = len(args.args)
    n_defaults = len(args.defaults)
    offset = n_args - n_defaults

    for i, arg in enumerate(args.args):
        piece = arg.arg
        if arg.annotation:
            piece += f": {ast.unparse(arg.annotation)}"
        default_idx = i - offset
        if default_idx >= 0:
            piece += f" = {ast.unparse(args.defaults[default_idx])}"
        parts.append(piece)

    # *args
    if args.vararg:
        piece = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            piece += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(piece)
    elif args.kwonlyargs:
        parts.append("*")

    # keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        piece = arg.arg
        if arg.annotation:
            piece += f": {ast.unparse(arg.annotation)}"
        if args.kw_defaults[i] is not None:
            piece += f" = {ast.unparse(args.kw_defaults[i])}"
        parts.append(piece)

    # **kwargs
    if args.kwarg:
        piece = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            piece += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(piece)

    sig = f"{node.name}({', '.join(parts)})"
    if node.returns:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _is_constant_name(name: str) -> bool:
    return name.isupper() and len(name) > 0


def _collect_imports(node: ast.Import | ast.ImportFrom) -> list[ImportInfo]:
    infos: list[ImportInfo] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            infos.append(ImportInfo(
                module=alias.name,
                alias=alias.asname,
                kind="package",  # classified later
                line=node.lineno,
            ))
    else:  # ImportFrom
        if node.level and node.level > 0:
            # relative import
            for alias in node.names:
                infos.append(ImportInfo(
                    module="",
                    alias=alias.name,
                    kind="local",
                    line=node.lineno,
                ))
        else:
            module = node.module or ""
            for alias in node.names:
                infos.append(ImportInfo(
                    module=module,
                    alias=alias.asname or alias.name,
                    kind="package",  # classified later
                    line=node.lineno,
                ))
    return infos


def parse_file(path: Path, root: Path | None = None) -> ParsedFile:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        rel = path.relative_to(root).as_posix() if root else path.name
        return ParsedFile(path=rel, module_doc=None, imports=[], symbols=[])

    rel_path = path.relative_to(root).as_posix() if root else path.name

    raw_doc = ast.get_docstring(tree)
    module_doc = raw_doc.splitlines()[0] if raw_doc else None

    imports: list[ImportInfo] = []
    symbols: list[Symbol] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_collect_imports(node))

        elif isinstance(node, ast.ClassDef):
            symbols.append(Symbol(
                name=node.name,
                kind="class",
                line=node.lineno,
                signature=None,
                parent=None,
            ))
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(Symbol(
                        name=child.name,
                        kind="method",
                        line=child.lineno,
                        signature=_build_signature(child),
                        parent=node.name,
                    ))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol(
                name=node.name,
                kind="function",
                line=node.lineno,
                signature=_build_signature(node),
                parent=None,
            ))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_constant_name(target.id):
                    symbols.append(Symbol(
                        name=target.id,
                        kind="constant",
                        line=node.lineno,
                        signature=None,
                        parent=None,
                    ))

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and _is_constant_name(node.target.id):
                symbols.append(Symbol(
                    name=node.target.id,
                    kind="constant",
                    line=node.lineno,
                    signature=None,
                    parent=None,
                ))

    return ParsedFile(path=rel_path, module_doc=module_doc, imports=imports, symbols=symbols)


def parse_repo(root: Path) -> dict[str, ParsedFile]:
    py_files = [
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and ".git" not in p.parts and ".venv" not in p.parts
    ]

    parsed: dict[str, ParsedFile] = {}
    for path in py_files:
        pf = parse_file(path, root)
        parsed[pf.path] = pf

    # Collect local module stems for import classification
    local_stems: set[str] = set()
    for path in py_files:
        rel = path.relative_to(root)
        local_stems.add(rel.stem)
        # also add package-style dotted path top-level
        local_stems.add(rel.parts[0].removesuffix(".py"))

    stdlib = sys.stdlib_module_names  # frozenset, available Python 3.10+

    for pf in parsed.values():
        for imp in pf.imports:
            if imp.kind == "local":
                continue
            top = imp.module.split(".")[0] if imp.module else ""
            if top in stdlib:
                imp.kind = "stdlib"
            elif top in local_stems:
                imp.kind = "local"
            else:
                imp.kind = "package"

    return parsed
