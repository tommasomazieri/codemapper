"""SessionStart hook: rebuild the codemapper2 graph at every session.

- Runs the AST + annotation pass every time (fast, keeps graph structurally fresh).
- Runs the LLM semantic pass only when source files have changed since the last
  LLM build (tracked via a hash in graphify-out/last_llm_hash.txt).
- Silent when graphify-out/graph.json doesn't exist (codemapper not set up).
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_SOURCE_GLOBS = (
    "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx",
    "**/*.go", "**/*.rs", "**/*.java", "**/*.cs", "**/*.cpp", "**/*.c",
)
_IGNORE_DIRS = frozenset({
    ".venv", "venv", ".env", "node_modules", ".git",
    "__pycache__", "graphify-out", "dist", "build", ".mypy_cache", ".pytest_cache",
})


def _source_hash(root: Path) -> str:
    h = hashlib.sha1()
    for glob in _SOURCE_GLOBS:
        for f in sorted(root.glob(glob)):
            if any(part in _IGNORE_DIRS for part in f.parts):
                continue
            try:
                stat = f.stat()
                h.update(f"{f.relative_to(root)}:{stat.st_mtime_ns}:{stat.st_size}".encode())
            except OSError:
                pass
    return h.hexdigest()


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd = Path(payload.get("cwd") or ".").resolve()
    if not (cwd / "graphify-out" / "graph.json").exists():
        sys.exit(0)

    hash_file = cwd / "graphify-out" / "last_llm_hash.txt"
    current_hash = _source_hash(cwd)
    last_hash = hash_file.read_text(encoding="utf-8").strip() if hash_file.exists() else ""
    files_changed = current_hash != last_hash

    cmd = [sys.executable, "-m", "codemapper.cli", "build", str(cwd)]
    if not files_changed:
        cmd.append("--no-llm")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if files_changed and result.returncode == 0:
            hash_file.write_text(current_hash, encoding="utf-8")
    except (subprocess.TimeoutExpired, OSError):
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
