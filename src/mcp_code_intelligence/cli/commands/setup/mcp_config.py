import json
import os
from pathlib import Path
from rich.console import Console
from ....core.git_hooks import GitHookManager

class MCPConfigManager:
    """Manages MCP server registration and tool injection."""

    def __init__(self, project_root: Path, console: Console):
        self.project_root = project_root
        self.console = console

    def write_local_config(self, mcp_servers: dict, language_lsps: dict | None = None) -> Path:
        """Create or update local .mcp/mcp.json.

        If `language_lsps` is provided, include it under the `languageLsps` key so
        other components can discover available external LSP binaries.
        """
        local_mcp_path = self.project_root / ".mcp" / "mcp.json"
        local_mcp_path.parent.mkdir(parents=True, exist_ok=True)
        out = {"mcpServers": mcp_servers}
        if language_lsps:
            out["languageLsps"] = language_lsps
        with open(local_mcp_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)
        return local_mcp_path

    def inject_global_config(self, platforms, mcp_servers: dict):
        """Inject server configurations into detected AI tools."""
        for platform_info in platforms:
            try:
                if not platform_info.config_path or not platform_info.config_path.exists():
                    continue

                with open(platform_info.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                config.setdefault("mcpServers", {}).update(mcp_servers)

                with open(platform_info.config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)

                self.console.print(f"   ✅ Configured {platform_info.platform.value}")
            except Exception as e:
                self.console.print(f"   ⚠️  Failed to configure {platform_info.platform.value}: {e}")

    def setup_git_hooks(self) -> bool:
        """Install git hooks for auto-indexing."""
        git_manager = GitHookManager(self.project_root)
        if git_manager.is_git_repo():
            return git_manager.install_hooks()
        return False
