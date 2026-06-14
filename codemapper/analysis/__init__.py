"""Deterministic multi-language quality analyzer.

``analyze()`` is the single entry point; it auto-detects each file's language and
dispatches to the right engine, returning one consolidated ``AnalysisResult`` whose
findings share a common shape (+ a ``language`` tag). Every finding is a
reproducible, traceable fact — no AI inside the analyzer.

Engines
  python  -> in-process AST analyzers (this package) + git docstring staleness
  js/ts   -> the fallow binary (subprocess), normalized by ``fallow_adapter``
  html    -> tree-sitter-html pass (``analysis/html.py``)

Scope is a cross-language *category* set; ``analyze`` runs each category on
whichever engines support it (see ``CATEGORY_ENGINES``).
"""

from pathlib import Path

from codemapper.analysis.complexity import find_complexity
from codemapper.analysis.deadcode import find_dead_code
from codemapper.analysis.deps import find_dependency_issues
from codemapper.analysis.findings import Action, AnalysisResult, Finding

__all__ = [
    "ANALYZERS",
    "ALL_CATEGORIES",
    "CATEGORY_ENGINES",
    "analyze",
    "Action",
    "Finding",
    "AnalysisResult",
]

# Python AST passes, keyed by category.
ANALYZERS: dict = {
    "dead": find_dead_code,
    "complexity": find_complexity,
    "deps": find_dependency_issues,
}

# Every diagnostic category and which engines cover it (for docs / introspection).
CATEGORY_ENGINES: dict[str, list[str]] = {
    "dead": ["python", "fallow"],
    "complexity": ["python", "fallow"],
    "deps": ["python", "fallow"],
    "staleness": ["python"],
    "dupes": ["fallow"],
    "circular": ["fallow"],
    "security": ["fallow"],
    "html": ["html"],
}
ALL_CATEGORIES = list(CATEGORY_ENGINES)

_PENALTY = {"error": 5, "warn": 2, "info": 0.5}


def _score(findings: list[Finding], n_files: int) -> int:
    """0-100 health score (deterministic, size-normalised across all languages).

    penalty = Σ {error: 5, warn: 2, info: 0.5}
    score = max(0, round(100 * n / (n + penalty)))   where n = analyzed source files
    """
    penalty = sum(_PENALTY.get(f.severity, 0) for f in findings)
    n = max(1, n_files)
    return max(0, round(100 * n / (n + penalty)))


def _summarize(findings: list[Finding]) -> dict:
    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        if f.language:
            by_language[f.language] = by_language.get(f.language, 0) + 1
    return {
        "total": len(findings),
        "by_rule": by_rule,
        "by_severity": by_severity,
        "by_language": by_language,
    }


def analyze(
    index=None,
    root: Path | None = None,
    scope: list[str] | None = None,
    language: str | None = None,
) -> AnalysisResult:
    """Run the requested categories across all relevant languages.

    Args:
        index: An optional prebuilt Python ``CodeIndex`` (built lazily if None and
            Python files are in scope). Kept first/positional for back-compat.
        root: Repo root.
        scope: Category names (see ``ALL_CATEGORIES``); None = all categories.
        language: Restrict to one of python|javascript|typescript|html; None = all.
    """
    from codemapper import fallow_runner
    from codemapper.languages import collect_files_by_language

    root = (root or Path(".")).resolve()
    files = collect_files_by_language(root)
    counts = {lang: len(fs) for lang, fs in files.items()}

    cat_set = set(scope) if scope else None  # None == all categories

    def want(cat: str) -> bool:
        return cat_set is None or cat in cat_set

    def lang_on(lang: str) -> bool:
        return language is None or language == lang

    findings: list[Finding] = []
    summary_extra: dict = {}

    # -- Python (in-process AST) -------------------------------------------- #
    py_files = files.get("python", [])
    py_cats = {"dead", "complexity", "deps", "staleness"}
    if py_files and lang_on("python") and (cat_set is None or cat_set & py_cats):
        if index is None:
            from codemapper.index import CodeIndex
            index = CodeIndex(root)
            index.build()
        for cat, fn in ANALYZERS.items():
            if want(cat):
                for f in fn(index, root):
                    f.language = "python"
                    findings.append(f)
        if want("staleness"):
            from codemapper.staleness import analyze_staleness
            for s in analyze_staleness(root, index):
                if s.stale:
                    findings.append(Finding(
                        rule="stale_docstring", severity="info", path=s.path,
                        language="python", message=s.reason))

    # -- JS/TS (fallow subprocess) ------------------------------------------ #
    has_jsts = bool(files.get("javascript") or files.get("typescript"))
    jsts_on = lang_on("javascript") or lang_on("typescript")
    if has_jsts and jsts_on and fallow_runner.is_available(root):
        from codemapper.analysis import fallow_adapter
        f_findings = fallow_adapter.to_findings(root, scope=cat_set, summary_sink=summary_extra)
        if language in ("javascript", "typescript"):
            f_findings = [f for f in f_findings if f.language == language]
        findings += f_findings

    # -- HTML (tree-sitter) -------------------------------------------------- #
    html_files = files.get("html", [])
    if html_files and lang_on("html") and want("html"):
        from codemapper.analysis.html import find_html_issues
        findings += find_html_issues(root, html_files)

    findings.sort(key=lambda f: (f.path, f.line or 0, f.rule))

    n_files = counts.get(language, 0) if language else sum(counts.values())
    summary = _summarize(findings)
    summary.update(summary_extra)
    scope_out = sorted(cat_set) if cat_set else list(ALL_CATEGORIES)
    return AnalysisResult(
        root=str(root),
        scope=scope_out,
        score=_score(findings, n_files),
        summary=summary,
        findings=findings,
    )
