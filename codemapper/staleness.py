"""Git-based docstring drift detection — the deterministic anti-slop signal.

Module docstrings are brittle: writers forget to update them as code changes,
so the "context" they give an agent silently rots. Rather than regenerate that
context with an LLM (expensive, and itself goes stale), we *flag* it
deterministically: if a file's code churned through many commits since its
module docstring was last touched, the docstring is probably stale.

All signals come from git history. No git (or an untracked file) degrades
gracefully: we can still report a missing docstring, but not assess drift.
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codemapper.index import CodeIndex

STALE_COMMIT_THRESHOLD = 5


@dataclass
class StalenessFinding:
    path: str
    has_docstring: bool
    doc_last_touched: str | None  # "<short-sha> <YYYY-MM-DD>"
    code_commits_since: int  # commits touching the file after doc_last_touched
    stale: bool
    reason: str  # "no_module_docstring" | "code_changed_Nx_since_doc" | "ok"


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def _is_git_repo(root: Path) -> bool:
    out = _git(root, "rev-parse", "--is-inside-work-tree")
    return out is not None and out.strip() == "true"


def _doc_last_commit(root: Path, rel_path: str, start: int, end: int) -> tuple[str, str] | None:
    """Return (full_sha, 'short-sha YYYY-MM-DD') for the newest commit touching the span."""
    out = _git(root, "blame", "-L", f"{start},{end}", "--porcelain", "--", rel_path)
    if out is None:
        return None

    best_sha: str | None = None
    best_time = -1
    cur_sha: str | None = None
    for line in out.splitlines():
        parts = line.split(" ")
        if len(parts) >= 4 and len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
            cur_sha = parts[0]
        elif line.startswith("committer-time ") and cur_sha is not None:
            try:
                t = int(line.split(" ", 1)[1])
            except ValueError:
                continue
            if t > best_time:
                best_time = t
                best_sha = cur_sha

    if best_sha is None:
        return None
    date = datetime.fromtimestamp(best_time, tz=timezone.utc).strftime("%Y-%m-%d")
    return best_sha, f"{best_sha[:7]} {date}"


def _commits_since(root: Path, rel_path: str, doc_sha: str) -> int:
    out = _git(root, "log", "--format=%H", f"{doc_sha}..HEAD", "--", rel_path)
    if out is None:
        return 0
    return sum(1 for line in out.splitlines() if line.strip())


def analyze_staleness(root: Path, index: CodeIndex) -> list[StalenessFinding]:
    is_repo = _is_git_repo(root)
    findings: list[StalenessFinding] = []

    for path in index.all_files():
        pf = index.get_file(path)
        if pf is None:
            continue
        has_doc = pf.module_doc is not None

        if not has_doc:
            findings.append(StalenessFinding(
                path=path, has_docstring=False, doc_last_touched=None,
                code_commits_since=0, stale=True, reason="no_module_docstring",
            ))
            continue

        if not is_repo or pf.doc_start_line is None or pf.doc_end_line is None:
            findings.append(StalenessFinding(
                path=path, has_docstring=True, doc_last_touched=None,
                code_commits_since=0, stale=False, reason="ok",
            ))
            continue

        doc_commit = _doc_last_commit(root, path, pf.doc_start_line, pf.doc_end_line)
        if doc_commit is None:
            # tracked-but-unblameable (e.g. untracked/new file): can't assess drift
            findings.append(StalenessFinding(
                path=path, has_docstring=True, doc_last_touched=None,
                code_commits_since=0, stale=False, reason="ok",
            ))
            continue

        sha, label = doc_commit
        since = _commits_since(root, path, sha)
        stale = since >= STALE_COMMIT_THRESHOLD
        reason = f"code_changed_{since}x_since_doc" if stale else "ok"
        findings.append(StalenessFinding(
            path=path, has_docstring=True, doc_last_touched=label,
            code_commits_since=since, stale=stale, reason=reason,
        ))

    return findings
