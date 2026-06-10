"""Python-specific depth that graphify's Tree-sitter pass does not provide:
full type-annotated signatures (e.g. 'def f(x: int, y: str = "d") -> bool').

Thin reuse layer over parser.parse_file — Tree-sitter gives function names but
not Python type annotations, so this stays AST-based and Python-only.
"""

from pathlib import Path

from codemapper.parser import parse_file


def signature(root: Path, rel_path: str, symbol: str) -> dict | None:
    """Return the type-annotated signature for `symbol` in `rel_path`, or None.

    Matches by symbol name (bare, no parens). For methods, the first match wins.
    """
    abs_path = (Path(root) / rel_path).resolve()
    if not abs_path.exists() or abs_path.suffix != ".py":
        return None
    try:
        pf = parse_file(abs_path, Path(root))
    except (OSError, SyntaxError):
        return None

    want = symbol.split("(")[0].strip()
    for s in pf.symbols:
        if s.name == want:
            return {
                "path": rel_path,
                "symbol": s.name,
                "kind": s.kind,
                "line": s.line,
                "parent": s.parent,
                "signature": s.signature or s.name,
            }
    return None
