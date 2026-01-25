"""Memory MCP Server - Python implementation.

Provides persistent key-value storage via MCP protocol.
Uses SQLite for reliable storage.
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


class MemoryServer:
    """MCP Server for persistent memory/knowledge graph."""

    def __init__(self, db_path: Path | None = None):
        """Initialize memory server.
        
        Args:
            db_path: Path to SQLite database (default: ~/.mcp_memory.db)
        """
        if db_path is None:
            db_path = Path.home() / ".mcp_memory.db"
        
        self.db_path = Path(db_path)
        self.server = Server("memory")
        self._init_database()
        self._setup_handlers()

    def _init_database(self):
        """Initialize SQLite database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def _setup_handlers(self):
        """Setup MCP protocol handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available memory tools."""
            return [
                Tool(
                    name="store",
                    description="Store a value with a key",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to store value under"
                            },
                            "value": {
                                "type": "string",
                                "description": "Value to store (will be JSON stringified)"
                            }
                        },
                        "required": ["key", "value"]
                    }
                ),
                Tool(
                    name="retrieve",
                    description="Retrieve a value by key",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to retrieve"
                            }
                        },
                        "required": ["key"]
                    }
                ),
                Tool(
                    name="delete",
                    description="Delete a key-value pair",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to delete"
                            }
                        },
                        "required": ["key"]
                    }
                ),
                Tool(
                    name="list_keys",
                    description="List all stored keys",
                    inputSchema={"type": "object", "properties": {}}
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            
            try:
                conn = self._get_connection()
                
                if name == "store":
                    key = arguments["key"]
                    value = arguments["value"]
                    
                    # Store as JSON string
                    if not isinstance(value, str):
                        value = json.dumps(value)
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO memory (key, value, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (key, value))
                    conn.commit()
                    conn.close()
                    
                    return [TextContent(type="text", text=f"Stored: {key}")]

                elif name == "retrieve":
                    key = arguments["key"]
                    
                    cursor = conn.execute(
                        "SELECT value FROM memory WHERE key = ?",
                        (key,)
                    )
                    row = cursor.fetchone()
                    conn.close()
                    
                    if row is None:
                        return [TextContent(type="text", text=f"Key not found: {key}")]
                    
                    return [TextContent(type="text", text=row[0])]

                elif name == "delete":
                    key = arguments["key"]
                    
                    cursor = conn.execute(
                        "DELETE FROM memory WHERE key = ?",
                        (key,)
                    )
                    conn.commit()
                    deleted = cursor.rowcount
                    conn.close()
                    
                    if deleted == 0:
                        return [TextContent(type="text", text=f"Key not found: {key}")]
                    
                    return [TextContent(type="text", text=f"Deleted: {key}")]

                elif name == "list_keys":
                    cursor = conn.execute(
                        "SELECT key, created_at FROM memory ORDER BY key"
                    )
                    rows = cursor.fetchall()
                    conn.close()
                    
                    if not rows:
                        return [TextContent(type="text", text="No keys stored")]
                    
                    keys_list = "\n".join(f"{key} (created: {created})" for key, created in rows)
                    return [TextContent(type="text", text=keys_list)]

                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            except Exception as e:
                return [TextContent(type="text", text=f"Memory error: {e}")]

    async def run(self):
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point for memory server."""
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    
    server = MemoryServer(db_path)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
