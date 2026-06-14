"""Data model for analysis findings, actions, and results."""

from dataclasses import dataclass, field


@dataclass
class Action:
    kind: str  # "remove_import"|"remove_symbol"|"remove_dependency"|"add_dependency"|"refactor_split"
    auto_fixable: bool
    detail: str | None = None


@dataclass
class Finding:
    rule: str   # python: "dead_code"|"dead_file"|"high_complexity"|"unused_import"|
                #   "unused_dependency"|"undeclared_dependency"|"unresolved_import"|"stale_docstring"
                # js/ts (fallow): + "duplicate_code"|"circular_dependency"|"security"
                # html: "duplicate_id"|"broken_local_ref"|"missing_alt"|"missing_lang"|"inline_script_loc"
    severity: str  # "info"|"warn"|"error"
    path: str
    message: str
    line: int | None = None
    symbol: str | None = None
    language: str | None = None  # "python"|"javascript"|"typescript"|"html"
    introduced: bool | None = None  # reserved for future git attribution (None in v1)
    actions: list[Action] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    root: str
    scope: list[str]
    score: int   # 0-100 deterministic heuristic
    summary: dict  # {"total", "by_rule", "by_severity", "by_language"[, "fallow_health"]}
    findings: list[Finding]
