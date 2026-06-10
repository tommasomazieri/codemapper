"""SessionStart hook: rebuild the codemapper2 graph (AST only) at every session.

Always runs with --no-llm: Tree-sitter extraction + codemapper annotations,
fully local, completes in under a minute. The LLM semantic pass is slow and
unreliable on the free OpenRouter tier — trigger it manually when needed.
Silent when graphify-out/graph.json doesn't exist (codemapper not set up).
"""

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd = Path(payload.get("cwd") or ".").resolve()
    if not (cwd / "graphify-out" / "graph.json").exists():
        sys.exit(0)

    try:
        subprocess.run(
            [sys.executable, "-m", "codemapper.cli", "build", str(cwd), "--no-llm"],
            capture_output=True,
            timeout=280,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
