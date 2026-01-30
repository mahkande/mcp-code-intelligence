import asyncio
import os
import sys
from pathlib import Path

# Add src to sys.path
sys.path.append(str(Path("c:/Users/mahir/Desktop/mcp-server/mcp-vector-search/src")))

from mcp_code_intelligence.mcp.server import MCPVectorSearchServer

async def test_debug_ping():
    # Initialize server for the target project
    project_root = Path("C:/Users/mahir/Desktop/orm-drf")
    server = MCPVectorSearchServer(project_root=project_root)
    
    print(f"Server initialized with project root: {project_root}")
    
    # Try to call debug_ping logic directly
    try:
        # In the server, _handle_debug_ping is the handler
        result = await server._handle_debug_ping({})
        print("--- debug_ping result ---")
        print(result)
        print("-------------------------")
    except Exception as e:
        print(f"Error calling debug_ping: {e}")

if __name__ == "__main__":
    asyncio.run(test_debug_ping())
