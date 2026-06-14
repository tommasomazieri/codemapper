"""Normalize fallow's JSON output into codemapper's shared ``Finding`` model.

fallow ships several commands, each with its own JSON shape. We run only the
commands the requested scope needs, then map their findings onto our rules so
JS/TS diagnostics look identical to Python diagnostics downstream (MCP, API,
annotator).

The parsers are deliberately tolerant: fallow's contract (`CheckOutput`) is
version-pinned and a few sub-shapes are not fully documented, so we dig for the
common location keys and skip anything we don't recognize rather than crash.
Captured-JSON fixtures in tests pin the documented shapes.
"""

from pathlib import Path

from codemapper.analysis.findings import Action, Finding
from codemapper.languages import detect_language

# fallow's categories that map to a fallow CLI command.
FALLOW_CATEGORIES = {"dead", "deps", "complexity", "circular", "dupes", "security"}

# fallow action `type` (kebab-case) -> our Action.kind
_ACTION_KIND = {
    "remove-export": "remove_symbol",
    "remove-file": "remove_symbol",
    "remove-import": "remove_import",
    "remove-dependency": "remove_dependency",
    "remove-dep": "remove_dependency",
    "add-dependency": "add_dependency",
    "add-dep": "add_dependency",
}

# complexity error threshold (fallow default --max-cyclomatic 20)
_CC_ERROR = 20


def _lang_for(path: str) -> str:
    lang = detect_language(path)
    return lang if lang in ("javascript", "typescript") else "javascript"


def _actions(raw: list | None) -> list[Action]:
    out: list[Action] = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        atype = a.get("type", "")
        out.append(Action(
            kind=_ACTION_KIND.get(atype, atype.replace("-", "_")),
            auto_fixable=bool(a.get("auto_fixable", False)),
            detail=a.get("description") or a.get("comment"),
        ))
    return out


def _loc(d: dict) -> tuple[str | None, int | None]:
    """Best-effort (path, line) extraction from an arbitrary fallow record."""
    path = d.get("path") or d.get("file") or d.get("filepath")
    line = d.get("line") or d.get("start_line") or d.get("lineno")
    return path, (int(line) if isinstance(line, int) else None)


# --------------------------------------------------------------------------- #
# Per-command parsers
# --------------------------------------------------------------------------- #

def _parse_dead(data: dict, want_deps: bool, want_dead: bool) -> list[Finding]:
    findings: list[Finding] = []
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):
            continue
        path, line = _loc(f)
        if not path:
            continue
        export = f.get("export_name") or f.get("name")
        actions = _actions(f.get("actions"))
        is_dep = bool(f.get("dependency") or f.get("package")) or f.get("kind") == "unused-dependency"
        if is_dep:
            if not want_deps:
                continue
            dep = f.get("dependency") or f.get("package") or export
            findings.append(Finding(
                rule="unused_dependency", severity="warn", path=path, line=line,
                symbol=dep, language=_lang_for(path),
                message=f"Unused dependency '{dep}'", actions=actions))
        elif export:
            if not want_dead:
                continue
            findings.append(Finding(
                rule="dead_code", severity="warn", path=path, line=line,
                symbol=export, language=_lang_for(path),
                message=f"Unused export '{export}'", actions=actions))
        else:
            if not want_dead:
                continue
            findings.append(Finding(
                rule="dead_file", severity="info", path=path, line=line,
                language=_lang_for(path),
                message="Unused file (not imported anywhere)", actions=actions))
    # Some fallow versions break unused deps into a top-level array.
    if want_deps:
        for dep in data.get("unused_dependencies", []) or []:
            name = dep if isinstance(dep, str) else (dep.get("name") if isinstance(dep, dict) else None)
            if name:
                findings.append(Finding(
                    rule="unused_dependency", severity="warn", path="package.json",
                    symbol=name, language="typescript",
                    message=f"Unused dependency '{name}'"))
    return findings


def _parse_health(data: dict, want_complexity: bool, want_circular: bool) -> list[Finding]:
    findings: list[Finding] = []
    if want_complexity:
        for f in data.get("findings", []) or []:
            if not isinstance(f, dict):
                continue
            path, line = _loc(f)
            if not path:
                continue
            cc = f.get("cyclomatic")
            cog = f.get("cognitive")
            exceeded = f.get("exceeded", "")
            sev = "error" if (isinstance(cc, int) and cc >= _CC_ERROR and exceeded in ("cyclomatic", "both")) else "warn"
            findings.append(Finding(
                rule="high_complexity", severity=sev, path=path, line=line,
                symbol=f.get("name"), language=_lang_for(path),
                message=f"cyclomatic {cc} / cognitive {cog} exceed thresholds",
                metadata={"cyclomatic": cc, "cognitive": cog}))
    if want_circular:
        count = (data.get("vital_signs") or {}).get("circular_dep_count")
        cycles = data.get("circular_dependencies") or data.get("cycles")
        if isinstance(cycles, list) and cycles:
            for c in cycles:
                members = c if isinstance(c, list) else (c.get("members") if isinstance(c, dict) else None)
                first = members[0] if isinstance(members, list) and members else None
                path = first if isinstance(first, str) else "package.json"
                findings.append(Finding(
                    rule="circular_dependency", severity="warn", path=path,
                    language=_lang_for(path),
                    message="Circular dependency: " + " -> ".join(str(m) for m in (members or []))))
        elif isinstance(count, int) and count > 0:
            findings.append(Finding(
                rule="circular_dependency", severity="warn", path="package.json",
                language="typescript",
                message=f"{count} circular dependency group(s) detected"))
    return findings


def _parse_dupes(data: dict) -> list[Finding]:
    findings: list[Finding] = []
    groups = data.get("findings") or data.get("duplicates") or []
    for g in groups:
        if not isinstance(g, dict):
            continue
        occ = g.get("occurrences") or g.get("blocks") or g.get("locations") or []
        lines = g.get("lines") or g.get("line_count")
        for o in occ:
            if not isinstance(o, dict):
                continue
            path, line = _loc(o)
            if not path:
                continue
            findings.append(Finding(
                rule="duplicate_code", severity="warn", path=path, line=line,
                language=_lang_for(path),
                message=f"Duplicated block ({lines} lines) repeated {len(occ)}x"))
    return findings


def _parse_security(data: dict) -> list[Finding]:
    findings: list[Finding] = []
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):
            continue
        path, line = _loc(f)
        if not path:
            continue
        findings.append(Finding(
            rule="security", severity=f.get("severity", "warn"), path=path, line=line,
            symbol=f.get("rule") or f.get("name"), language=_lang_for(path),
            message=f.get("message") or f.get("description") or "Security candidate"))
    return findings


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def to_findings(root: Path, *, scope: set[str] | None = None, summary_sink: dict | None = None) -> list[Finding]:
    """Run the fallow commands the scope needs and return normalized Findings.

    ``scope`` is the cross-language category set; only the intersection with
    fallow's categories runs. ``summary_sink`` (optional) receives fallow's own
    ``health_score`` under key ``fallow_health`` when health runs.
    """
    from codemapper import fallow_runner

    cats = (scope & FALLOW_CATEGORIES) if scope else set(FALLOW_CATEGORIES)
    if not cats:
        return []

    findings: list[Finding] = []

    if cats & {"dead", "deps"}:
        try:
            data = fallow_runner.dead_code(root)
            findings += _parse_dead(data, want_deps="deps" in cats, want_dead="dead" in cats)
        except RuntimeError:
            pass

    if cats & {"complexity", "circular"}:
        try:
            data = fallow_runner.health(root)
            findings += _parse_health(data, want_complexity="complexity" in cats, want_circular="circular" in cats)
            if summary_sink is not None and data.get("health_score"):
                summary_sink["fallow_health"] = data["health_score"]
        except RuntimeError:
            pass

    if "dupes" in cats:
        try:
            findings += _parse_dupes(fallow_runner.dupes(root))
        except RuntimeError:
            pass

    if "security" in cats:
        try:
            findings += _parse_security(fallow_runner.security(root))
        except RuntimeError:
            pass

    return findings
