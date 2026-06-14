"""Manages the fallow subprocess — the only file in codemapper2 that knows fallow exists.

fallow (https://github.com/fallow-rs/fallow) is a Rust-native, MIT-licensed static
analyzer for TypeScript/JavaScript. codemapper2 shells out to it the same way
``graphify_runner`` shells out to graphify, then normalizes its JSON
(``analysis/fallow_adapter.py``) into the shared ``Finding`` model.

Verified against the fallow CLI docs (docs.fallow.tools):
  dead code:     fallow dead-code --format json --quiet -r <root>
  health/cx:     fallow health --score --file-scores --format json --quiet -r <root>
  duplication:   fallow dupes --format json --quiet -r <root>
  security:      fallow security --format json --quiet -r <root>
  changed-file:  fallow audit --changed-since <ref> --format json --quiet -r <root>

We never pass --fail-on-issues, so the process exits 0 even when findings exist;
a non-zero exit therefore signals a real tool error.
"""

import json
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 120


def _fallow_exe(root: Path) -> str | None:
    """Resolve the fallow binary: project-local node_modules first, then PATH.

    Returns None if fallow is not installed (callers degrade gracefully).
    """
    local = root / "node_modules" / ".bin"
    for name in ("fallow.cmd", "fallow.exe", "fallow"):
        cand = local / name
        if cand.exists():
            return str(cand)
    return shutil.which("fallow")


def is_available(root: Path) -> bool:
    """True if the fallow binary can be resolved for this repo."""
    return _fallow_exe(root.resolve()) is not None


def _run(cmd: str, root: Path, extra: list[str] | None = None) -> dict:
    """Run ``fallow <cmd> --format json --quiet -r <root>`` and parse stdout JSON.

    Raises RuntimeError if fallow is missing, times out, or emits unparseable output.
    """
    root = root.resolve()
    exe = _fallow_exe(root)
    if exe is None:
        raise RuntimeError("fallow binary not found (install via 'npm i -D fallow' or 'cargo install fallow-cli').")
    argv = [exe, cmd, "--format", "json", "--quiet", "-r", str(root), *(extra or [])]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"fallow {cmd} timed out after {TIMEOUT}s") from exc
    out = (proc.stdout or "").strip()
    if not out:
        # No JSON on stdout: surface stderr (it usually explains why).
        raise RuntimeError(f"fallow {cmd} produced no JSON (exit {proc.returncode}): {proc.stderr.strip()[:300]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"fallow {cmd} returned non-JSON output: {out[:300]}") from exc


def dead_code(root: Path) -> dict:
    """fallow dead-code — unused files/exports/deps."""
    return _run("dead-code", root)


def health(root: Path) -> dict:
    """fallow health — complexity hotspots, maintainability, health score."""
    return _run("health", root, ["--score", "--file-scores"])


def dupes(root: Path) -> dict:
    """fallow dupes — copy-pasted code blocks."""
    return _run("dupes", root)


def security(root: Path) -> dict:
    """fallow security — security candidates."""
    return _run("security", root)


def audit(root: Path, base: str = "HEAD") -> dict:
    """fallow audit — changed-file risk gate vs a git ref (deferred scope)."""
    return _run("audit", root, ["--changed-since", base])
