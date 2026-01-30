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
from mcp_code_intelligence.core.languages import SUPPORTED_LANGUAGES as available_lsps

from .discovery import DiscoveryManager
from .intelligence import IntelligenceManager
from .mcp_config import MCPConfigManager
from .wizard import SetupWizard
from ....core.exceptions import ProjectInitializationError
from ...output import print_error, print_info, print_success, print_warning
from collections import Counter
from ....core.project import ProjectManager
from ....config.defaults import get_language_from_extension

async def run_setup_workflow(ctx: typer.Context, force: bool, verbose: bool):
    # Pre-flight dependency check
    import importlib.util
    missing = []
    for pkg in ["einops", "torch", "sentence_transformers", "chromadb"]:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    if missing:
        print_warning(f"\n⚠️  Eksik Python paketleri: {', '.join(missing)}\nKurulumdan önce şu komutu çalıştırın:\n    pip install {' '.join(missing)}\n")
        if not force:
            if not typer.confirm("Eksik paketlerle devam etmek istiyor musunuz? (Kurulum başarısız olabilir)", default=False):
                print_info("Kurulum iptal edildi.")
                return

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
    print_info("\n🔍 Proje dilleri tespit ediliyor...")
    languages = discovery.detect_languages()
    extensions = discovery.scan_file_extensions()
    platforms = discovery.detect_ai_platforms()

    # Projedeki en yaygın dili otomatik tespit et
    pm = ProjectManager(project_root)
    file_langs = []
    for file_path in pm._iter_source_files():
        lang = get_language_from_extension(file_path.suffix)
        if lang and lang != "text":
            file_langs.append(lang.lower())
    if not file_langs:
        main_lang = "python"
    else:
        main_lang = Counter(file_langs).most_common(1)[0][0]
    print_info(f"\nProjenin ana dili otomatik tespit edildi: {main_lang}")
    selected_langs = [main_lang.capitalize() if main_lang == "python" else main_lang.title()]

    # Node.js ve npm kontrolü (JS/TS için)
    import shutil as _shutil
    if any(l in ["JavaScript", "TypeScript"] for l in languages):
        if not _shutil.which("npm"):
            print_warning("\n⚠️  TypeScript/JavaScript desteği için Node.js ve npm bulunamadı!\nLütfen https://nodejs.org adresinden Node.js kurun veya --force ile devam edin.\n")
            if not force:
                if not typer.confirm("Node.js/npm olmadan devam etmek istiyor musunuz? (JS/TS LSP kurulamaz)", default=False):
                    print_info("Kurulum iptal edildi.")
                    return
    # Java kontrolü (JDTLS için)
    if "Java" in languages:
        if not _shutil.which("java"):
            print_warning("\n⚠️  Java desteği için Java JDK bulunamadı!\nLütfen https://adoptium.net/ adresinden JDK kurun veya --force ile devam edin.\n")
            if not force:
                if not typer.confirm("Java olmadan devam etmek istiyor musunuz? (Java LSP kurulamaz)", default=False):
                    print_info("Kurulum iptal edildi.")
                    return

    # Platformları filtrele
    from py_mcp_installer import Platform
    EXCLUDED = {Platform.CLAUDE_DESKTOP}
    configurable = [p for p in platforms if p.platform not in EXCLUDED]

    # 2. Planlama: Sadece ana dili yükle
    available_langs = {}
    langs_dir = Path(__file__).parent.parent.parent.parent / "languages"
    if langs_dir.exists():
        for f in langs_dir.glob("*.json"):
            with open(f) as ld:
                data = json.load(ld)
                available_langs[data["name"].lower()] = data
    # Sadece ana dilin datasını ekle
    detected_lang_names = [main_lang.capitalize() if main_lang == "python" else main_lang.title()]
    if not selected_langs:
        print_warning("Hiçbir dil seçilmedi, sadece Python kurulacak.")
        selected_langs = ["Python"]

    # planned_lsp: Match selected languages against available language configs
    planned_lsp = []
    selected_langs_data = []

    # Normalize selected languages for matching
    normalized_selected = [s.lower() for s in selected_langs]

    for name_key, data in available_langs.items():
        config_name = data["name"].lower()
        # Check if config_name is in selected_langs or if any selected_lang is in config_name
        # (e.g., "javascript" should match "javascript/typescript")
        if any(s in config_name or config_name in s for s in normalized_selected):
            selected_langs_data.append(data)
            planned_lsp.append(data['name'])
            logger.debug(f"Matched language config: {data['name']} for selected: {selected_langs}")

    python_cmd = sys.executable
    # Determine command for main server
    import shutil
    mcp_cmd = shutil.which("mcp-code-intelligence")
    if mcp_cmd:
        # Use the absolute path to the CLI command to support virtual environments
        # (If we just used "mcp-code-intelligence", it wouldn't work if the venv isn't active in the editor)
        server_cmd = mcp_cmd
        server_args = ["mcp"]
    else:
        # Fallback to python module execution
        server_cmd = sys.executable
        server_args = ["-m", "mcp_code_intelligence.mcp"]

    mcp_servers = {
        "mcp-code-intelligence": {
            "command": server_cmd,
            "args": server_args,
            "env": {
                "MCP_PROJECT_ROOT": str(project_root.resolve()),
                "MCP_ENABLE_FILE_WATCHING": "true",
            }
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

    # Add dynamic LSPs (Tekrar başlatmayı önle)
    lsp_registry = intel.get_lsp_configs()
    for lp in planned_lsp:
        low = lp.lower()
        if low in lsp_registry:
            cfg = lsp_registry[low]
            lsp_id = cfg["id"]
            if lsp_id in mcp_servers:
                continue  # Aynı LSP zaten eklenmişse tekrar ekleme
            cmd = cfg.get("win_cmd", cfg["cmd"]) if os.name == 'nt' else cfg["cmd"]
            if shutil.which(cmd) or cfg["cmd"] == python_cmd:
                mcp_servers[lsp_id] = {"command": cmd, "args": cfg["args"]}

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
    mcp_man.write_local_config(mcp_servers, available_lsps)
    mcp_man.inject_global_config(configurable, mcp_servers)

    # Universal Rule Injection (All AI assistants)
    # Rules files are always created regardless of editor type
    mcp_man.inject_universal_rules(mcp_servers)
    mcp_man.inject_cursor_rules(mcp_servers)
    mcp_man.inject_copilot_instructions(mcp_servers)

    # Start LSP proxies for any available external LSPs so MCP can route requests
    try:
        from ...core.lsp_proxy import start_proxies

        # start_proxies is async; run in event loop
        try:
            asyncio.get_event_loop().run_until_complete(start_proxies(project_root))
        except RuntimeError:
            # If there is already a running loop (e.g., in some contexts), create a task
            asyncio.create_task(start_proxies(project_root))
    except Exception as e:
        logger.debug(f"Could not start LSP proxies: {e}")
    mcp_man.setup_git_hooks()

    # Finish
    wizard.show_completion([
        "mcp-code-intelligence search 'query'",
        "mcp-code-intelligence status"
    ])

    # MCP sunucularını otomatik başlat (Düzeltilmiş girinti)
    print_info("\n🚦 MCP sunucuları başlatılıyor...")
    import subprocess
    started_servers = []
    for server_name, server_cfg in mcp_servers.items():
        try:
            cmd = [server_cfg["command"]] + server_cfg["args"]
            env = os.environ.copy()
            env.update(server_cfg.get("env", {}))
            # Sunucuyu arka planda başlat
            subprocess.Popen(cmd, env=env, cwd=str(project_root))
            started_servers.append(server_name)
            print_success(f"Başlatıldı: {server_name}")
        except Exception as e:
            print_error(f"{server_name} başlatılamadı: {e}")
    print_info(f"\nToplam başlatılan sunucu: {len(started_servers)} → {', '.join(started_servers)}")

async def main_setup_task(ctx: typer.Context, force: bool, verbose: bool):
    try:
        await run_setup_workflow(ctx, force, verbose)
    except Exception as e:
        logger.error(f"Setup error: {e}")
        print_error(f"Setup failed: {e}")
        raise typer.Exit(1)
