"""PreToolUse hook: nudge Claude to query the codemapper2 graph before blind search.

Reads the hook payload on stdin. If the current repo has a built codemapper2
graph, injects a non-blocking system-reminder (additionalContext) pointing Claude
at the MCP tools. Stays silent (exit 0, no output) when no graph exists, so it is
inert in repos that haven't run setup.
"""

import datetime
import json
import re
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

NAV_PATTERNS = re.compile(r'\b(grep|rg|find|cat|head|tail|sed|awk)\b')


def _log(cwd: Path, record: dict) -> None:
    try:
        log_path = cwd / "graphify-out" / "mcp_usage.jsonl"
        record["ts"] = datetime.datetime.now().isoformat(timespec="milliseconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def should_block(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return bool(NAV_PATTERNS.search(command))
    return True


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cwd = Path(payload.get("cwd") or ".")
    if not (cwd / "graphify-out" / "graph_annotated.json").exists():
        sys.exit(0)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if tool_name == "Bash" else ""
    if not should_block(tool_name, tool_input):
        record: dict = {"event": "hook", "tool": tool_name, "decision": "pass",
                        "pass_reason": "no nav pattern"}
        if command:
            record["cmd_snippet"] = command[:80]
        _log(cwd, record)
        sys.exit(0)
    record = {"event": "hook", "tool": tool_name, "decision": "nav_pattern"}
    if command:
        record["cmd_snippet"] = command[:80]
    _log(cwd, record)
    sys.exit(0)


if __name__ == "__main__":
    main()
