"""Python LSP MCP Server - Language Server Protocol integration.

Provides Python language intelligence via MCP protocol.
Uses python-lsp-server (pylsp) for code analysis.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

try:
    from pylsp import lsp
    from pylsp.workspace import Workspace, Document
    from pylsp.config.config import Config
    PYLSP_AVAILABLE = True
except ImportError:
    PYLSP_AVAILABLE = False


class PythonLSPServer:
    """MCP Server for Python Language Server Protocol."""

    def __init__(self, workspace_path: Path | None = None):
        """Initialize Python LSP server.
        
        Args:
            workspace_path: Path to workspace root (default: current directory)
        """
        self.workspace_path = Path(workspace_path or Path.cwd()).resolve()
        self.server = Server("python-lsp")
        
        if PYLSP_AVAILABLE:
            self.workspace = Workspace(str(self.workspace_path), None)
            self.config = Config(str(self.workspace_path), {}, 0, {})
        else:
            self.workspace = None
            self.config = None
            
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup MCP protocol handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available LSP tools."""
            return [
                Tool(
                    name="goto_definition",
                    description="Find definition of a symbol at given position",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "File path"},
                            "line": {"type": "number", "description": "Line number (0-indexed)"},
                            "character": {"type": "number", "description": "Character position (0-indexed)"}
                        },
                        "required": ["file", "line", "character"]
                    }
                ),
                Tool(
                    name="find_references",
                    description="Find all references to a symbol",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "File path"},
                            "line": {"type": "number", "description": "Line number (0-indexed)"},
                            "character": {"type": "number", "description": "Character position (0-indexed)"}
                        },
                        "required": ["file", "line", "character"]
                    }
                ),
                Tool(
                    name="get_hover_info",
                    description="Get type and documentation for symbol at position",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "File path"},
                            "line": {"type": "number", "description": "Line number (0-indexed)"},
                            "character": {"type": "number", "description": "Character position (0-indexed)"}
                        },
                        "required": ["file", "line", "character"]
                    }
                ),
                Tool(
                    name="get_completions",
                    description="Get code completion suggestions",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "File path"},
                            "line": {"type": "number", "description": "Line number (0-indexed)"},
                            "character": {"type": "number", "description": "Character position (0-indexed)"}
                        },
                        "required": ["file", "line", "character"]
                    }
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            
            if not PYLSP_AVAILABLE:
                return [TextContent(
                    type="text",
                    text="Error: python-lsp-server not installed. Run: pip install python-lsp-server"
                )]
            
            try:
                file_path = self.workspace_path / arguments["file"]
                if not file_path.exists():
                    return [TextContent(type="text", text=f"File not found: {file_path}")]
                
                # Create document
                doc = Document(str(file_path), self.workspace)
                position = {
                    "line": arguments["line"],
                    "character": arguments["character"]
                }
                
                if name == "goto_definition":
                    from pylsp.plugins.definition import pylsp_definitions
                    
                    result = pylsp_definitions(self.config, doc, position)
                    if not result:
                        return [TextContent(type="text", text="No definition found")]
                    
                    locations = []
                    for loc in result:
                        uri = loc["uri"]
                        range_info = loc["range"]
                        locations.append(
                            f"{uri} (line {range_info['start']['line']})"
                        )
                    
                    return [TextContent(type="text", text="\n".join(locations))]

                elif name == "find_references":
                    from pylsp.plugins.references import pylsp_references
                    
                    result = pylsp_references(self.config, doc, position)
                    if not result:
                        return [TextContent(type="text", text="No references found")]
                    
                    refs = []
                    for ref in result:
                        uri = ref["uri"]
                        range_info = ref["range"]
                        refs.append(
                            f"{uri} (line {range_info['start']['line']})"
                        )
                    
                    return [TextContent(type="text", text="\n".join(refs))]

                elif name == "get_hover_info":
                    from pylsp.plugins.hover import pylsp_hover
                    
                    result = pylsp_hover(self.config, doc, position)
                    if not result or not result.get("contents"):
                        return [TextContent(type="text", text="No hover information")]
                    
                    contents = result["contents"]
                    if isinstance(contents, dict):
                        text = contents.get("value", str(contents))
                    else:
                        text = str(contents)
                    
                    return [TextContent(type="text", text=text)]

                elif name == "get_completions":
                    from pylsp.plugins.completion import pylsp_completions
                    
                    result = pylsp_completions(self.config, doc, position)
                    if not result or not result.get("items"):
                        return [TextContent(type="text", text="No completions available")]
                    
                    items = result["items"][:10]  # Limit to 10
                    completions = []
                    for item in items:
                        label = item["label"]
                        kind = item.get("kind", "")
                        detail = item.get("detail", "")
                        completions.append(f"{label} ({kind}): {detail}")
                    
                    return [TextContent(type="text", text="\n".join(completions))]

                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            except Exception as e:
                return [TextContent(type="text", text=f"LSP error: {e}")]

    async def run(self):
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point for Python LSP server."""
    workspace_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    
    server = PythonLSPServer(workspace_path)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
