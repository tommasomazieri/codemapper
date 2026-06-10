"""Manages the graphify subprocess — the only file in codemapper2 that knows graphify exists.

Verified against graphify (graphifyy) 0.8.36 CLI:
  build (with LLM):  graphify extract <path> --backend openai --model <model>
  code-only update:  graphify update <path>            (no LLM)
  semantic query:    graphify query "<q>" --budget N   (no LLM, pure graph traversal)
  shortest path:     graphify path "A" "B"             (no LLM)

LLM semantic extraction is routed through OpenRouter (OpenAI-compatible) using the
free gpt-oss-120b model. The OpenRouter key is read from api_config.json and passed
to the subprocess as OPENAI_API_KEY + OPENAI_BASE_URL; it is never logged or exposed.
"""

import json
import os
import subprocess
import sysconfig
from pathlib import Path

# Verified free model on OpenRouter: 131K context, $0 in/out.
DEFAULT_MODEL = "openai/gpt-oss-120b:free"
DEFAULT_BACKEND = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PROVIDER_NAME = "openrouter"


def _codemapper_root() -> Path:
    return Path(__file__).parent.parent


def _graphify_exe() -> str:
    """Resolve the graphify console script in codemapper2's own environment.

    Uses the interpreter's Scripts/bin dir (sysconfig) so it resolves even when
    codemapper2's MCP server is launched by absolute path with no activated venv.
    Falls back to PATH.
    """
    scripts = Path(sysconfig.get_path("scripts"))
    for name in ("graphify.exe", "graphify"):
        cand = scripts / name
        if cand.exists():
            return str(cand)
    import shutil
    found = shutil.which("graphify")
    if found:
        return found
    raise RuntimeError(
        "graphify command not found. Install it in this environment: pip install graphifyy"
    )


def _read_openrouter_key() -> str:
    """Read OPENROUTER_API_KEY from api_config.json. Never logged or written to disk."""
    config_path = _codemapper_root() / "api_config.json"
    if not config_path.exists():
        return ""
    with config_path.open() as f:
        cfg = json.load(f)
    return cfg.get("OPENROUTER_API_KEY", "")


def _ensure_openrouter_provider() -> None:
    """Register an 'openrouter' OpenAI-compatible provider in graphify's global
    config (~/.graphify/providers.json). The key is NOT stored here — graphify
    reads it at runtime from the OPENROUTER_API_KEY env var (via env_key)."""
    providers_path = Path.home() / ".graphify" / "providers.json"
    providers_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "base_url": OPENROUTER_BASE_URL,
        "default_model": DEFAULT_MODEL,
        "env_key": "OPENROUTER_API_KEY",
        "pricing": {"input": 0.0, "output": 0.0},
        "temperature": 0,
        "max_completion_tokens": 16384,
        "vision": False,
    }
    data: dict = {}
    if providers_path.exists():
        try:
            loaded = json.loads(providers_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    if data.get(PROVIDER_NAME) != entry:
        data[PROVIDER_NAME] = entry
        providers_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _graph_json(root: Path) -> Path:
    return root / "graphify-out" / "graph.json"


def is_stale(root: Path) -> bool:
    """True if graph.json is missing or older than any tracked source file."""
    gj = _graph_json(root)
    if not gj.exists():
        return True
    graph_mtime = gj.stat().st_mtime
    ignored = {".git", "graphify-out", ".venv", "__pycache__", "node_modules"}
    for p in root.rglob("*"):
        if p.is_file() and not any(part in ignored for part in p.relative_to(root).parts):
            if p.stat().st_mtime > graph_mtime:
                return True
    return False


def build(
    root: Path,
    no_llm: bool = False,
    backend: str | None = None,
    model: str | None = None,
) -> None:
    """Build the knowledge graph.

    no_llm=True  -> 'graphify update' (AST/tree-sitter only, fully offline).
    no_llm=False -> 'graphify extract' with semantic LLM via OpenRouter
                    (backend defaults to 'openai', model to gpt-oss-120b:free).
    """
    exe = _graphify_exe()
    root = root.resolve()

    if no_llm:
        cmd = [exe, "update", str(root)]
        env = {**os.environ}
    else:
        _ensure_openrouter_provider()
        env = {**os.environ}
        key = _read_openrouter_key()
        if key:
            env["OPENROUTER_API_KEY"] = key
        cmd = [
            exe, "extract", str(root),
            "--backend", backend or DEFAULT_BACKEND,
            "--model", model or DEFAULT_MODEL,
        ]

    subprocess.run(cmd, env=env, check=True, stdin=subprocess.DEVNULL)


def query(text: str, root: Path, budget: int = 2000) -> str:
    """graphify query — BFS traversal of graph.json (no LLM)."""
    exe = _graphify_exe()
    gj = _graph_json(root)
    if not gj.exists():
        raise FileNotFoundError(f"graph.json not found at {gj}. Run 'codemapper2 build' first.")
    result = subprocess.run(
        [exe, "query", text, "--budget", str(budget), "--graph", str(gj)],
        capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL, timeout=60,
    )
    return result.stdout


def path_query(a: str, b: str, root: Path) -> str:
    """graphify path — shortest path between two nodes (no LLM)."""
    exe = _graphify_exe()
    gj = _graph_json(root)
    if not gj.exists():
        raise FileNotFoundError(f"graph.json not found at {gj}. Run 'codemapper2 build' first.")
    result = subprocess.run(
        [exe, "path", a, b, "--graph", str(gj)],
        capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL, timeout=60,
    )
    return result.stdout
