"""Index command module — lightweight entrypoint that registers submodules.

This file is intentionally small: it exposes `index_app` and delegates
work to the split modules in the same folder so each file stays under
~200-300 lines for maintainability.
"""

from pathlib import Path
import asyncio
import typer

# CLI app for `mcp-code-intelligence index`
index_app = typer.Typer(help="Index codebase for semantic search", invoke_without_command=True)


@index_app.callback(invoke_without_command=True)
def main(ctx: typer.Context, **kwargs) -> None:
    """Entrypoint for `mcp-code-intelligence index`.

    Delegates to `index_runner` or spawns a background indexer.
    """
    if ctx.invoked_subcommand is not None:
        return

    # Lazy imports to avoid heavy module loads during CLI discovery
    from .index_runner import run_indexing
    from .index_background import _spawn_background_indexer

    project_root = (ctx.obj.get("project_root") if ctx.obj else None) or Path.cwd()
    background = bool(kwargs.get("background", False))

    if background:
        _spawn_background_indexer(project_root, **{k: kwargs.get(k) for k in ("force", "extensions", "workers", "throttle", "max_size", "important_only")})
        return

    asyncio.run(run_indexing(project_root=project_root, **kwargs))


# Import submodules to register CLI subcommands (they import `index_app` from this file)
from . import index_progress, index_background, index_runner, index_reindex, index_status



