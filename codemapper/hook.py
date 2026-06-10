"""PreToolUse hook: nudge Claude to query the codemapper2 graph before blind search.

Reads the hook payload on stdin. If the current repo has a built codemapper2
graph, injects a non-blocking system-reminder (additionalContext) pointing Claude
at the MCP tools. Stays silent (exit 0, no output) when no graph exists, so it is
inert in repos that haven't run setup.
"""

import json
import sys
from pathlib import Path

BLOCK_REASON = (
    "codemapper2 graph is available — use MCP tools instead of broad file search:\n"
    "  • explore(query)            semantic graph search for any code concept\n"
    "  • god_nodes()               most central/complex/stale files (ranked by degree)\n"
    "  • neighbors(node)           what a file imports / is imported by\n"
    "  • community(node)           architectural cluster a file belongs to\n"
    "  • path_between(a, b)        dependency chain between two nodes\n"
    "  • diagnose(path)            dead code, complexity, staleness findings\n"
    "  • python_sig(path, symbol)  type-annotated signature\n"
    "Call build() first if the graph is stale."
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = Path(payload.get("cwd") or ".")
    if not (cwd / "graphify-out" / "graph_annotated.json").exists():
        sys.exit(0)
    print(json.dumps({"decision": "block", "reason": BLOCK_REASON}))
    sys.exit(0)


if __name__ == "__main__":
    main()
