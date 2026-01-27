"""Python LSP discovery helpers for MCP registry.

This module exposes a lightweight, discovery-safe `get_advertised_tools(project_root)`
that the registry uses to learn about available Python/LSP capabilities without
starting any server processes or importing heavyweight runtime dependencies.

The implementation below is intentionally conservative: imports that may fail
in minimal environments are guarded and discovery only performs non-invasive
checks. If the LSP is missing or not configured for the project, the function
returns a single `python_lsp_unavailable` Tool with actionable instructions.
"""

from pathlib import Path
from typing import List

from mcp.types import Tool

# Import the LSP proxy manager lazily; absence is tolerated during discovery.
try:
    from ..core.lsp_proxy import get_manager  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    get_manager = None  # type: ignore


# Lightweight check for python-lsp-server (pylsp). We don't rely on it being
# present at import time; discovery will inspect availability and advertise
# an actionable fix if missing.
try:
    import pylsp  # type: ignore
    PYLSP_AVAILABLE = True
except Exception:
    PYLSP_AVAILABLE = False


class PythonLSPServer:  # pragma: no cover - small compatibility stub
    """Compatibility stub so `from ... import PythonLSPServer` continues to work.

    The real server implementation lives in the runtime code; this stub keeps
    package imports safe during discovery.
    """
    pass


def get_advertised_tools(project_root: Path) -> List[Tool]:
    """Return discovery-only `Tool` descriptors for Python LSP support.

    This function performs only lightweight checks and never starts or manages
    server processes. The returned `Tool` objects are safe for the registry
    to inspect and present to the Agent.
    """
    # If the language server package isn't available, advertise an unavailable tool.
    if not PYLSP_AVAILABLE:
        return [
            Tool(
                name="python_lsp_unavailable",
                description=(
                    "LSP unavailable: python-lsp-server (pylsp) is not installed. "
                    "Install with: pip install python-lsp-server"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # Try to inspect per-project manager configuration; treat failures as
    # non-fatal and fall back to advertising the LSP tools.
    try:
        if get_manager is not None:
            mgr = get_manager(project_root)
            try:
                cfg = mgr._load_config() if hasattr(mgr, "_load_config") else {}
            except Exception:
                cfg = {}
            if not cfg:
                return [
                    Tool(
                        name="python_lsp_unavailable",
                        description=(
                            "LSP unavailable: no language LSPs configured for this project. "
                            "Add .mcp/mcp.json languageLsps entries or run `mcp start-lsp`."
                        ),
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
    except Exception:
        # Non-fatal: continue to advertise tools below.
        pass

    # Discovery-only tool descriptors (do not start servers here).
    return [
        Tool(
            name="goto_definition",
            description="Find definition of a symbol at given position (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="find_references",
            description="Find all references to a symbol (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="get_hover_info",
            description="Get type and documentation for symbol at position (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="get_completions",
            description="Get code completion suggestions (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
    ]
