
import sys
import shutil
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel

# Import from py-mcp-installer library
# Ensure this runs within the package context or after dependencies are installed
try:
    from py_mcp_installer import (
        MCPInstaller,
        MCPServerConfig,
        Platform,
        PlatformDetector,
        PlatformInfo,
    )
except ImportError:
    # If running as script, might need to adjust path or env
    sys.exit("Error: py_mcp_installer not found. Run this within the installed environment.")

console = Console()
app = typer.Typer(help="Onboarding and setup for standard MCP servers")

def detect_platforms() -> List[PlatformInfo]:
    """Detect all available platforms on the system using py_mcp_installer."""
    detector = PlatformDetector()
    detected_platforms = []

    # Map of platform enums to their detection methods
    platform_detectors = {
        Platform.CLAUDE_CODE: detector.detect_claude_code,
        Platform.CLAUDE_DESKTOP: detector.detect_claude_desktop,
        Platform.CURSOR: detector.detect_cursor,
        Platform.AUGGIE: detector.detect_auggie,
        Platform.CODEX: detector.detect_codex,
        Platform.WINDSURF: detector.detect_windsurf,
        Platform.GEMINI_CLI: detector.detect_gemini_cli,
    }

    for platform_enum, detector_func in platform_detectors.items():
        try:
            confidence, config_path = detector_func()
            if confidence > 0.0 and config_path:
                 detected_platforms.append(
                    PlatformInfo(
                        platform=platform_enum,
                        confidence=confidence,
                        config_path=config_path,
                        cli_available=False
                    )
                )
        except Exception:
            continue


            
    return detected_platforms

def install_server(platform_info: PlatformInfo, config: MCPServerConfig) -> bool:
    """Install a generic server configuration to a platform."""
    installer = MCPInstaller(platform=platform_info.platform)
    try:
        console.print(f"[dim]  Installing {config.name} to {platform_info.platform.value}...[/dim]")
        result = installer.install_server(
            name=config.name,
            command=config.command,
            args=config.args,
            env=config.env,
            description=config.description
        )
        if result.success:
            console.print(f"  ✅ [green]{config.name}[/green] installed to {platform_info.platform.value}")
            return True
        else:
            console.print(f"  ❌ Failed to install {config.name}: {result.message}")
            return False
    except Exception as e:
        # Handle "already exists" gracefully if possible, or just report error
        if "already exists" in str(e).lower():
             console.print(f"  ✅ [green]{config.name}[/green] already exists in {platform_info.platform.value}")
             return True
        console.print(f"  ❌ Error installing {config.name}: {e}")
        return False

@app.command("setup")
def setup(
    allowed_path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Absolute path for the project index"
    )
):
    """
    Interactive Setup Wizard: Guided configuration for your AI intelligence tools.
    """
    import os
    import json
    console.print(Panel.fit("🚀 [bold]MCP Intelligence Setup Wizard[/bold]\n[dim]I will help you configure your AI assistant correctly.[/dim]", border_style="cyan"))

    # 1. Ask for languages
    languages_str = typer.prompt("Which programming languages do you use? (comma separated)", default="python")
    languages = [l.strip().lower() for l in languages_str.split(",")]
    
    # 2. Optional features
    install_git = typer.confirm("Enable Git integration (requires git CLI)?", default=True)
    install_memory = typer.confirm("Enable Memory/Knowledge Graph (stores project info)?", default=True)
    global_install = typer.confirm("\nShould I automatically inject these into Claude, Cursor, and Windsurf global settings?", default=False)

    console.print("\n[bold yellow]⚙️ Initializing Setup...[/bold yellow]")

    python_cmd = sys.executable
    import subprocess

    servers_to_install = []

    # Main Intelligence Server (Always)
    servers_to_install.append(MCPServerConfig(
        name="mcp-code-intelligence",
        command=python_cmd,
        args=["-m", "mcp_code_intelligence.mcp", "mcp"],
        env={"MCP_PROJECT_ROOT": str(allowed_path.resolve()), "MCP_ENABLE_FILE_WATCHING": "true"},
        description="Semantic Search (Jina v3)"
    ))

    # Python LSP
    if "python" in languages:
        try:
            import pylsp
        except ImportError:
            console.print("[dim]📦 Installing Python LSP...[/dim]")
            subprocess.run([python_cmd, "-m", "pip", "install", "python-lsp-server"], check=True, capture_output=True)
        
        servers_to_install.append(MCPServerConfig(
            name="python-lsp",
            command=python_cmd,
            args=["-m", "mcp_code_intelligence.servers.python_lsp_server", str(allowed_path.resolve())],
            env={},
            description="LSP (Type Intel)"
        ))

    # Generic Filesystem (Always recommended)
    servers_to_install.append(MCPServerConfig(
        name="filesystem",
        command=python_cmd,
        args=["-m", "mcp_code_intelligence.servers.filesystem_server", str(allowed_path.resolve())],
        env={},
        description="Filesystem Access"
    ))

    # Optional Git
    if install_git:
        try:
            import git
        except ImportError:
            console.print("[dim]📦 Installing GitPython...[/dim]")
            subprocess.run([python_cmd, "-m", "pip", "install", "gitpython"], check=True, capture_output=True)
        
        servers_to_install.append(MCPServerConfig(
            name="git",
            command=python_cmd,
            args=["-m", "mcp_code_intelligence.servers.git_server", str(allowed_path.resolve())],
            env={},
            description="Git Operations"
        ))

    # Optional Memory
    if install_memory:
        servers_to_install.append(MCPServerConfig(
            name="memory",
            command=python_cmd,
            args=["-m", "mcp_code_intelligence.servers.memory_server"],
            env={},
            description="Knowledge Memory"
        ))

    # --- ACTION: Writing local config ---
    console.print(f"\n[bold blue]Writing Workspace Configuration...[/bold blue]")
    local_roo_path = allowed_path / ".roo" / "mcp.json"
    local_roo_path.parent.mkdir(parents=True, exist_ok=True)
    
    config_data = {"mcpServers": {}}
    for s in servers_to_install:
        config_data["mcpServers"][s.name] = {"command": s.command, "args": s.args, "env": s.env}
    
    with open(local_roo_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2)
    console.print(f"  ✅ [green]Updated .roo/mcp.json[/green]")

    # --- ACTION: Global ---
    if global_install:
        # (Platform detection and global injection logic remains the same)
        console.print(f"\n[bold blue]2. Scanning for AI Clients (Claude, Cursor, Windsurf)...[/bold blue]")
        platforms = detect_platforms()
        if not platforms:
            console.print("  [yellow]No other global AI clients detected.[/yellow]")
        else:
            for p in platforms:
                console.print(f"  Configuring [cyan]{p.platform.value}[/cyan]...")
                for s in servers:
                     install_server(p, s)
        
        # Roo Code Global handling
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roo_paths = [
                Path(appdata) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
                Path(appdata) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp.json"
            ]
            for rp in roo_paths:
                if rp.exists():
                    try:
                        with open(rp, 'r') as f: data = json.load(f)
                        data.setdefault("mcpServers", {}).update({s.name: {"command": s.command, "args": s.args, "env": s.env} for s in servers})
                        with open(rp, 'w') as f: json.dump(data, f, indent=2)
                        console.print(f"  ✅ [green]Updated Roo Code Global Config[/green]")
                        break
                    except Exception: continue

    console.print(Panel("[bold green]✨ Universal Setup Complete![/bold green]\n\n[white]Restart your AI tools to apply changes.[/white]\n[dim]To watch background activity, run:[/dim]\n[cyan]mcp-code-intelligence logs[/cyan]"))

@app.command("logs")
def view_logs():
    """Live monitor background MCP activity."""
    import asyncio # Import asyncio here as it's only needed for this command
    log_file = Path.cwd() / ".mcp-code-intelligence" / "logs" / "activity.log"
    if not log_file.exists():
        console.print(f"[red]Error: Log file not found at {log_file}[/red]")
        console.print("[dim]Ensure the project is being indexed by an MCP server.[/dim]")
        return

    console.print(Panel.fit(f"👀 [bold]Live Activity Stream[/bold]\n[dim]{log_file}[/dim]", border_style="cyan"))
    try:
        # Simple tail -f implementation in Python
        with open(log_file, "r", encoding="utf-8") as f:
            f.seek(0, 2) # Go to end
            while True:
                line = f.readline()
                if not line:
                    asyncio.run(asyncio.sleep(0.5))
                    continue
                console.print(line.strip(), style="dim" if "INFO" in line else "bold white")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped log monitoring.[/yellow]")

@app.command("install-standard-servers")
def install_standard_servers(allowed_path: Path = Path.cwd()):
    """DEPRECATED: Use 'setup' instead."""
    setup(allowed_path=allowed_path, global_install=False)
