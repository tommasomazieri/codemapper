"""fallow-style deterministic quality analyzer for Python codebases.

Exposes ``analyze()`` as the main entry point and ``ANALYZERS`` as the
registry of available passes. Every finding is a reproducible, traceable fact
— no AI inside the analyzer.
"""

from pathlib import Path

from codemapper.analysis.complexity import find_complexity
from codemapper.analysis.deadcode import find_dead_code
from codemapper.analysis.deps import find_dependency_issues
from codemapper.analysis.findings import Action, AnalysisResult, Finding
from codemapper.index import CodeIndex

__all__ = [
    "ANALYZERS",
    "analyze",
    "Action",
    "Finding",
    "AnalysisResult",
]

ANALYZERS: dict = {
    "dead": find_dead_code,
    "complexity": find_complexity,
    "deps": find_dependency_issues,
}


def _score(findings: list[Finding], index: CodeIndex) -> int:
    """0-100 health score (deterministic heuristic, size-normalised).

    penalty = Σ {error: 5, warn: 2, info: 0.5}
    score = max(0, round(100 * n / (n + penalty)))   where n = number of .py files
    """
    weights = {"error": 5, "warn": 2, "info": 0.5}
    penalty = sum(weights.get(f.severity, 0) for f in findings)
    n = max(1, len(index.all_files()))
    return max(0, round(100 * n / (n + penalty)))


def _summarize(findings: list[Finding]) -> dict:
    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
    return {"total": len(findings), "by_rule": by_rule, "by_severity": by_severity}


def analyze(
    index: CodeIndex,
    root: Path,
    scope: list[str] | None = None,
) -> AnalysisResult:
    """Run the requested analysis passes and return a consolidated result."""
    scope = scope if scope is not None else list(ANALYZERS)
    findings: list[Finding] = []
    for name in scope:
        if name in ANALYZERS:
            findings.extend(ANALYZERS[name](index, root))
    findings.sort(key=lambda f: (f.path, f.line or 0, f.rule))
    return AnalysisResult(
        root=str(root),
        scope=list(scope),
        score=_score(findings, index),
        summary=_summarize(findings),
        findings=findings,
    )
