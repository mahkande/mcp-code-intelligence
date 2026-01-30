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

    def inject_vscode_settings(self, mcp_servers: dict):
        """Inject MCP server configurations into .vscode/settings.json."""
        vscode_dir = self.project_root / ".vscode"
        vscode_dir.mkdir(exist_ok=True)
        settings_path = vscode_dir / "settings.json"

        settings = {}
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception as e:
                # Assuming 'logger' is defined elsewhere or should be 'self.console.print'
                # For now, keeping it as is, but noting the potential undefined 'logger'
                # If 'logger' is not defined, this would cause a NameError.
                # Given the context, it's likely intended to be self.console.print
                # However, the instruction did not ask to change this line, only to use 'mcpServers'
                # which is already being done.
                self.console.print(f"   ⚠️  Failed to load existing VS Code settings: {e}")

        # Update mcpServers (Standard key for Cursor and VS Code MCP extensions)
        current_servers = settings.get("mcpServers", {})
        current_servers.update(mcp_servers)
        settings["mcpServers"] = current_servers

        # Also add under github.copilot.chat.mcpServers for the official Copilot extension support
        # Note: This is a newer/experimental path and might require specific Copilot versions
        copilot_mcp = settings.get("github.copilot.chat.mcpServers", {})
        copilot_mcp.update(mcp_servers)
        settings["github.copilot.chat.mcpServers"] = copilot_mcp

        try:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            self.console.print("   ✅ Configured .vscode/settings.json (mcpServers + github.copilot)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to configure .vscode/settings.json: {e}")

    def inject_copilot_instructions(self, mcp_servers: dict):
        """Generate .github/copilot-instructions.md for GitHub Copilot."""
        copilot_dir = self.project_root / ".github"
        copilot_dir.mkdir(exist_ok=True)
        instructions_path = copilot_dir / "copilot-instructions.md"

        tool_list = "\n".join([f"- `{name}`: {info.get('description', '')}" for name, info in mcp_servers.items()])
        connection_info = json.dumps({"mcpServers": mcp_servers}, indent=2)
        
        content = f"""# GitHub Copilot Instructions for MCP Code Intelligence
This project is equipped with MCP (Model Context Protocol) tools that provide deep semantic understanding and codebase intelligence.

## 🛠 Available MCP Tools
The following tools are available via the `mcp-code-intelligence` server:
{tool_list}

## 🔌 Physical Connection
If MCP tools are not automatically recognized, ensure your client is configured with:
```json
{connection_info}
```

## 💡 Guidelines
- When I ask about the codebase, prioritize using `search_code` for semantic discovery.
- Before refactoring or changing symbols, use `analyze_impact` to understand the ripple effects.
- If you need to find similar logic, use `search_similar`.
- Use `find_smells` to identify technical debt.
- All tools can be invoked via the standard MCP interface.

## 🔗 References
Detailed rules are maintained in [.mcp-rules.md](../../.mcp-rules.md).
"""
        try:
            with open(instructions_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print("   ✅ Created Copilot Instructions (.github/copilot-instructions.md)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create Copilot instructions: {e}")

    def inject_universal_rules(self, mcp_servers: dict):
        """Generate a universal .mcp-rules.md file in the project root."""
        rules_path = self.project_root / ".mcp-rules.md"
        
        content = f"""# 🧠 MCP Code Intelligence: Universal Rules
This file defines the interaction protocols for all AI assistants (Gemini, Claude, Cursor, Copilot) in this project.

## 🛠 Active MCP Servers
This project uses the following MCP servers for deep code analysis:
{chr(10).join([f"- **{name}**" for name in mcp_servers.keys()])}

## 📜 Core Instructions
1. **Semantic Awareness**: Do not rely solely on filename matching. Always use `search_code` for intent-based discovery.
2. **Impact First**: Refactoring is high-risk. Always trace dependencies using `analyze_impact` before proposing changes.
3. **Consistency**: Use `search_similar` to ensure new code follows existing project patterns.
4. **Health Protocols**: Check for long methods and high complexity using `find_smells` and `analyze_project`.

## 📂 Configuration Sources
Individual assistants may use specific files which reference these rules:
- **Cursor/IDX**: [`.cursorrules`](.cursorrules)
- **GitHub Copilot**: [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- **VS Code**: [`.vscode/settings.json`](.vscode/settings.json)
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print("   ✅ Created Universal Rules (.mcp-rules.md)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create universal rules: {e}")

    def inject_cursor_rules(self, mcp_servers: dict):
        """Generate .cursorrules file with tool definitions and instructions."""
        rules_path = self.project_root / ".cursorrules"
        
        # Tool summaries for the LLM
        tool_descriptions = [
            "- `search_code`: Hybrid (Keyword + Semantic) search for finding logic and intent.",
            "- `search_similar`: Find similar code patterns or duplicate logic.",
            "- `analyze_project`: Get a high-level health and complexity overview.",
            "- `find_smells`: Detect technical debt and anti-patterns.",
            "- `analyze_impact`: Trace ripple effects before refactoring symbols.",
            "- `get_relationships`: See callers/callees and semantic siblings of a symbol.",
            "- `goto_definition/find_references`: High-precision navigation via LSP."
        ]

        rules_content = f"""# MCP Code Intelligence Rules
You are an AI assistant equipped with powerful MCP tools to explore, analyze, and refactor this codebase.

## 🛠 Available Tools
These tools are provided by the `mcp-code-intelligence` server:
{chr(10).join(tool_descriptions)}

## 💡 Best Practices
1. **Search Before You Leap**: Use `search_code` to understand existing patterns before implementing new features.
2. **Refactor Safely**: Always run `analyze_impact` before changing a widely used function or class.
3. **Avoid Duplication**: Use `search_similar` or `propose_logic` if you suspect the logic might already exist.
4. **Health Check**: Periodically run `find_smells` to keep the code clean.
5. **Precision Navigation**: Prefer `goto_definition` and `find_references` for navigating symbols as they are backed by real Language Servers (LSPs).

## 🚀 How to Use
Simply ask for what you need:
- "Search for how authentication is handled."
- "What is the impact of changing the 'User' class?"
- "Find any code smells in the 'core' directory."

## 🔗 Universal Reference
See [.mcp-rules.md](.mcp-rules.md) for core protocol definitions.
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(rules_content)
            self.console.print("   ✅ Created .cursorrules for AI guidance")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create .cursorrules: {e}")
