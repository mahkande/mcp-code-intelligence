import asyncio
import sys
import json
import os
import shutil
import time
from pathlib import Path
from loguru import logger
import typer
from rich.console import Console

from .discovery import DiscoveryManager
from .intelligence import IntelligenceManager
from .mcp_config import MCPConfigManager
from .wizard import SetupWizard

from ....core.exceptions import ProjectInitializationError
from ...output import print_error, print_info, print_success, print_warning

async def run_setup_workflow(ctx: typer.Context, force: bool, verbose: bool):
    """Orchestrates the modular setup process."""
    console = Console()
    project_root = ctx.obj.get("project_root") or Path.cwd()
    
    # Initialize Managers
    discovery = DiscoveryManager(project_root)
    intel = IntelligenceManager(project_root, console)
    mcp_man = MCPConfigManager(project_root, console)
    wizard = SetupWizard(console)

    wizard.show_header()

    # 1. Discovery
    print_info("\n🔍 Discovering project...")
    languages = discovery.detect_languages()
    extensions = discovery.scan_file_extensions()
    platforms = discovery.detect_ai_platforms()
    
    # Filter platforms
    from py_mcp_installer import Platform
    EXCLUDED = {Platform.CLAUDE_DESKTOP}
    configurable = [p for p in platforms if p.platform not in EXCLUDED]
    
    # 2. Plan Actions
    planned_lsp = []
    available_langs = {}
    langs_dir = Path(__file__).parent.parent.parent.parent / "languages"
    if langs_dir.exists():
        for f in langs_dir.glob("*.json"):
            with open(f) as ld:
                data = json.load(ld)
                available_langs[data["name"].lower()] = data

    selected_langs_data = []
    for name, data in available_langs.items():
        if any(l.lower() in name.lower() or name.lower() in l.lower() for l in languages):
            selected_langs_data.append(data)
            planned_lsp.append(data['name'])

    # Prepare servers
    python_cmd = sys.executable
    mcp_servers = {
        "mcp-code-intelligence": {
            "command": python_cmd,
            "args": ["-m", "mcp_code_intelligence.mcp", "mcp"],
            "env": {"MCP_PROJECT_ROOT": str(project_root.resolve()), "MCP_ENABLE_FILE_WATCHING": "true"}
        },
        "filesystem": {
            "command": python_cmd,
            "args": ["-m", "mcp_code_intelligence.servers.filesystem_server", str(project_root.resolve())]
        },
        "git": {
            "command": python_cmd,
            "args": ["-m", "mcp_code_intelligence.servers.git_server", str(project_root.resolve())]
        },
        "memory": {
            "command": python_cmd,
            "args": ["-m", "mcp_code_intelligence.servers.memory_server"]
        }
    }

    # Add dynamic LSPs
    lsp_registry = intel.get_lsp_configs()
    for lp in planned_lsp:
        low = lp.lower()
        if low in lsp_registry:
            cfg = lsp_registry[low]
            cmd = cfg.get("win_cmd", cfg["cmd"]) if os.name == 'nt' else cfg["cmd"]
            if shutil.which(cmd) or cfg["cmd"] == python_cmd:
                mcp_servers[cfg["id"]] = {"command": cmd, "args": cfg["args"]}

    # 3. Present Summary
    planned_actions = [
        "Initialize vector index using [bold]Jina v3[/bold]",
        f"Enable Intelligence (LSP) for: {', '.join(planned_lsp) if planned_lsp else 'Generic mode'}",
        f"Configure {len(mcp_servers)} Python-based MCP servers",
        "Inject configuration into AI tools"
    ]
    
    wizard.show_discovery_summary(
        project_root.name, 
        planned_lsp, 
        [p.platform.value for p in configurable],
        planned_actions
    )

    if not wizard.confirm_execution():
        print_info("Setup cancelled.")
        return

    # 4. Execution
    print_info("\n⚙️  Processing dependencies...")
    for ld in selected_langs_data:
        intel.process_language_dependencies(ld)

    print_info("🚀 Initializing system...")
    embedding_model = "jinaai/jina-embeddings-v3"
    discovery.project_manager.initialize(
        file_extensions=list(set((extensions or []) + [e for ld in selected_langs_data for e in ld.get("extensions", [])])),
        embedding_model=embedding_model,
        similarity_threshold=0.5,
        force=force
    )
    
    intel.download_model_weights(embedding_model)
    
    # Indexing
    print_info("\n🔍 Indexing codebase...")
    print_info("[dim]💡 This is a one-time process. Changes will be updated incrementally later.[/dim]")
    from ..index import run_indexing
    try:
        await run_indexing(project_root=project_root, force_reindex=force, show_progress=True)
    except Exception as e:
        print_error(f"Indexing failed: {e}")

    # Config Injection
    print_info("\n🔗 Linking AI tools...")
    mcp_man.write_local_config(mcp_servers)
    mcp_man.inject_global_config(configurable, mcp_servers)
    mcp_man.setup_git_hooks()

    # Finish
    wizard.show_completion([
        "mcp-code-intelligence search 'query'",
        "mcp-code-intelligence status"
    ])

async def main_setup_task(ctx: typer.Context, force: bool, verbose: bool):
    try:
        await run_setup_workflow(ctx, force, verbose)
    except Exception as e:
        logger.error(f"Setup error: {e}")
        print_error(f"Setup failed: {e}")
        raise typer.Exit(1)
