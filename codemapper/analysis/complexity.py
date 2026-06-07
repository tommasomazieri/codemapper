"""Complexity analyzer: cyclomatic and cognitive complexity per function."""

import ast
from pathlib import Path

from codemapper.analysis.findings import Action, Finding
from codemapper.analysis.util import iter_functions
from codemapper.index import CodeIndex


def _cyclomatic(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Cyclomatic complexity = 1 + number of branching decision points."""
    count = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.If, ast.IfExp)):
            count += 1
        elif isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
            count += 1
        elif isinstance(child, ast.ExceptHandler):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            count += len(child.ifs)
        elif isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.match_case):
            count += 1
    return count


def _cognitive(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Simplified cognitive complexity with nesting-weighted structural increments."""

    def _structural(stmts: list, depth: int) -> int:
        c = 0
        for s in stmts:
            if isinstance(s, ast.If):
                c += 1 + depth
                c += _structural(s.body, depth + 1)
                if s.orelse:
                    is_elif = len(s.orelse) == 1 and isinstance(s.orelse[0], ast.If)
                    c += 1  # else/elif adds a flat 1
                    c += _structural(s.orelse, depth if is_elif else depth + 1)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                c += 1 + depth
                c += _structural(s.body, depth + 1)
                c += _structural(s.orelse, depth + 1)
            elif isinstance(s, ast.While):
                c += 1 + depth
                c += _structural(s.body, depth + 1)
                c += _structural(s.orelse, depth + 1)
            elif isinstance(s, ast.Try):
                c += _structural(s.body, depth + 1)
                for h in s.handlers:
                    c += 1 + depth
                    c += _structural(h.body, depth + 1)
                c += _structural(getattr(s, "finalbody", []), depth + 1)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                c += _structural(s.body, depth + 1)
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                c += _structural(s.body, depth + 1)
        return c

    structural = _structural(node.body, 0)
    bool_extra = sum(
        len(n.values) - 1
        for n in ast.walk(node)
        if isinstance(n, ast.BoolOp)
    )
    return structural + bool_extra


def find_complexity(
    index: CodeIndex,
    root: Path,
    cc_warn: int = 10,
    cc_error: int = 20,
    cog_warn: int = 15,
) -> list[Finding]:
    findings: list[Finding] = []

    for path_key in index.all_files():
        abs_path = root / Path(path_key)
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(abs_path))
        except (OSError, SyntaxError):
            continue

        for qualname, func_node, lineno in iter_functions(tree):
            cc = _cyclomatic(func_node)
            cog = _cognitive(func_node)

            if cc >= cc_warn or cog >= cog_warn:
                if cc >= cc_error:
                    severity = "error"
                else:
                    severity = "warn"

                if cc >= cc_warn:
                    msg = (
                        f"Function '{qualname}' is complex:"
                        f" cyclomatic {cc} (threshold {cc_warn})"
                    )
                else:
                    msg = (
                        f"Function '{qualname}' is complex:"
                        f" cognitive {cog} (threshold {cog_warn})"
                    )

                findings.append(Finding(
                    rule="high_complexity",
                    severity=severity,
                    path=path_key,
                    line=lineno,
                    symbol=qualname,
                    message=msg,
                    actions=[Action(kind="refactor_split", auto_fixable=False)],
                    metadata={"cyclomatic": cc, "cognitive": cog},
                ))

    return findings
