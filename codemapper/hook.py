"""PreToolUse hook: block file-search tools and redirect to codemapper2 MCP.

Fires on Grep, Glob, and nav-pattern Bash commands when a codemapper2 graph
exists. Always blocks with a specific "for X use Y" message so the model knows
exactly which MCP tool to call instead. Logs every decision to mcp_usage.jsonl.
"""

import datetime
import json
import re
import sys
from pathlib import Path

# Always-nav: block wherever they appear in the command
_ALWAYS_NAV = re.compile(
    r'\b(grep|rg|find|ls|dir|wc|Get-ChildItem|gci)\b',
    re.IGNORECASE,
)

# Primary-nav: only block when used as a primary command, not as a pipe destination
# e.g. `head file.py` → block; `pytest ... | head -60` → pass
_PRIMARY_NAV = re.compile(r'\b(cat|head|tail|sed|awk)\b', re.IGNORECASE)


def _is_primary_nav(command: str) -> bool:
    for m in _PRIMARY_NAV.finditer(command):
        prefix = command[:m.start()].rstrip()
        if prefix and prefix[-1] == '|':
            continue  # pipe destination — output filter, not file navigation
        return True
    return False


def _log(cwd: Path, record: dict) -> None:
    try:
        log_path = cwd / "graphify-out" / "mcp_usage.jsonl"
        record["ts"] = datetime.datetime.now().isoformat(timespec="milliseconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _block_reason(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "…")
        path = tool_input.get("path") or ""
        lines = [f'For `grep "{pattern}"` → use `explore("{pattern}")` (semantic graph search).']
        if path:
            lines.append(f'For callers/imports of a specific file → `neighbors("node_id")`.')
            lines.append(f'For dead code / complexity in a path → `diagnose("{path}")`.')
        return "\n".join(lines)

    if tool_name == "Glob":
        pat = tool_input.get("pattern", "…")
        return (
            f'For `Glob("{pat}")` → use `god_nodes()` to list the most central files, '
            f'or `explore("{pat}")` to find files matching this concept, '
            f'or `community("node_id")` to browse a cluster of related files.'
        )

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        grep_m = re.search(r'\bgrep\b\s+(?:-[\w]+\s+)*["\']?([^"\'|\s\\;]+)', command)
        if grep_m:
            term = grep_m.group(1).strip('"\'')
            return f'For `grep "{term}"` → use `explore("{term}")` (semantic graph search).'
        if re.search(r'\b(find|ls|dir|Get-ChildItem|gci)\b', command, re.IGNORECASE):
            return (
                'For file listing / find → use `god_nodes()` to list important files, '
                '`explore("what you need")` for semantic search, '
                'or `neighbors("node_id")` to see a file\'s imports and callers.'
            )
        if re.search(r'\b(cat|head|tail)\b', command):
            return (
                'For `cat`/`head`/`tail` on a known path → use the `Read` tool directly. '
                'To find the file first → use `explore("concept")` then `Read` the result.'
            )
        if re.search(r'\bwc\b', command):
            return 'For line counts / file stats → use `god_nodes()` or `diagnose("path")`.'
        return (
            'Use codemapper2 MCP tools instead of shell navigation:\n'
            '  explore("concept")       — semantic search\n'
            '  god_nodes()              — most central/complex files\n'
            '  neighbors("node_id")     — imports and callers\n'
            '  diagnose("path")         — dead code, complexity, staleness'
        )

    return 'Use codemapper2 MCP tools: explore(), god_nodes(), neighbors(), community(), path_between(), diagnose().'


def _extract_explicit_paths(tool_name: str, tool_input: dict) -> list:
    """Return all explicit path arguments present in the tool call."""
    paths = []
    if tool_name in ("Grep", "Glob"):
        p = tool_input.get("path")
        if p:
            paths.append(p)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        # Quoted Windows absolute paths
        paths += re.findall(r'"([A-Za-z]:[\\\/][^"]*)"', command)
        paths += re.findall(r"'([A-Za-z]:[\\\/][^']*)'", command)
        # Unquoted Windows absolute paths
        for m in re.finditer(r'(?<!["\'])([A-Za-z]:[\\\/]\S+)', command):
            candidate = m.group(1).rstrip("'\"")
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _all_outside_cwd(paths: list, cwd: Path) -> bool:
    """Return True only when paths is non-empty and every path resolves outside cwd."""
    if not paths:
        return False
    cwd_str = str(cwd.resolve()).lower()
    for p in paths:
        try:
            if str(Path(p).resolve()).lower().startswith(cwd_str):
                return False
        except Exception:
            return False  # can't resolve → assume inside
    return True


def should_block(tool_name: str, tool_input: dict) -> bool:
    if tool_name in ("Grep", "Glob"):
        return True
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return bool(_ALWAYS_NAV.search(command)) or _is_primary_nav(command)
    return False


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

    # Pass through if every explicit path target is outside this project tree.
    explicit_paths = _extract_explicit_paths(tool_name, tool_input)
    if _all_outside_cwd(explicit_paths, cwd):
        _log(cwd, {"event": "hook", "tool": tool_name, "decision": "pass",
                   "pass_reason": "target outside project"})
        sys.exit(0)

    if not should_block(tool_name, tool_input):
        record: dict = {"event": "hook", "tool": tool_name, "decision": "pass",
                        "pass_reason": "no nav pattern"}
        if command:
            record["cmd_snippet"] = command[:80]
        _log(cwd, record)
        sys.exit(0)

    record: dict = {"event": "hook", "tool": tool_name, "decision": "block"}
    if command:
        record["cmd_snippet"] = command[:80]
    _log(cwd, record)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _block_reason(tool_name, tool_input),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
