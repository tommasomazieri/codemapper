"""Tests for codemapper.staleness (git-based docstring drift detection)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from codemapper.index import CodeIndex
from codemapper.staleness import STALE_COMMIT_THRESHOLD, analyze_staleness

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def _findings_by_path(repo: Path) -> dict:
    index = CodeIndex(repo)
    index.build()
    return {f.path: f for f in analyze_staleness(repo, index)}


def test_no_docstring_is_stale(repo: Path):
    (repo / "nodoc.py").write_text("X = 1\n", encoding="utf-8")
    _commit(repo, "add nodoc")
    f = _findings_by_path(repo)["nodoc.py"]
    assert f.has_docstring is False
    assert f.stale is True
    assert f.reason == "no_module_docstring"


def test_fresh_docstring_not_stale(repo: Path):
    (repo / "fresh.py").write_text('"""Header."""\nX = 1\n', encoding="utf-8")
    _commit(repo, "add fresh")
    f = _findings_by_path(repo)["fresh.py"]
    assert f.has_docstring is True
    assert f.code_commits_since == 0
    assert f.stale is False
    assert f.reason == "ok"
    assert f.doc_last_touched is not None


def test_code_churn_makes_docstring_stale(repo: Path):
    path = repo / "drift.py"
    path.write_text('"""Original header."""\nVALUE = 0\n', encoding="utf-8")
    _commit(repo, "initial drift")

    for i in range(STALE_COMMIT_THRESHOLD):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"VALUE_{i} = {i}\n")
        _commit(repo, f"code change {i}")

    f = _findings_by_path(repo)["drift.py"]
    assert f.code_commits_since == STALE_COMMIT_THRESHOLD
    assert f.stale is True
    assert f.reason == f"code_changed_{STALE_COMMIT_THRESHOLD}x_since_doc"


def test_below_threshold_not_stale(repo: Path):
    path = repo / "minor.py"
    path.write_text('"""Header."""\nVALUE = 0\n', encoding="utf-8")
    _commit(repo, "initial minor")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("VALUE_1 = 1\n")
    _commit(repo, "one small change")

    f = _findings_by_path(repo)["minor.py"]
    assert f.code_commits_since == 1
    assert f.stale is False
    assert f.reason == "ok"


def test_non_git_dir_degrades(tmp_path: Path):
    (tmp_path / "withdoc.py").write_text('"""Header."""\nX = 1\n', encoding="utf-8")
    (tmp_path / "nodoc.py").write_text("X = 1\n", encoding="utf-8")
    findings = _findings_by_path(tmp_path)
    assert findings["withdoc.py"].stale is False
    assert findings["withdoc.py"].reason == "ok"
    assert findings["nodoc.py"].stale is True
    assert findings["nodoc.py"].reason == "no_module_docstring"
