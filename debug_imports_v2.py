import sys
from pathlib import Path
import time

sys.path.append(str(Path("c:/Users/mahir/Desktop/mcp-server/mcp-vector-search/src")))

def test_import(module_name):
    print(f"Importing {module_name}...", end="", flush=True)
    start = time.time()
    try:
        __import__(module_name)
        print(f" OK ({time.time() - start:.2f}s)")
    except Exception as e:
        print(f" FAIL: {e}")

modules = [
    "mcp_code_intelligence.core.database",
    "mcp_code_intelligence.core.embeddings",
    "mcp_code_intelligence.core.indexer",
    "mcp_code_intelligence.core.search",
    "mcp_code_intelligence.core.watcher",
    "mcp_code_intelligence.core.llm_client",
    "mcp_code_intelligence.mcp.services.session",
    "mcp_code_intelligence.mcp.services.router",
    "mcp_code_intelligence.mcp.services.protocol"
]

for m in modules:
    test_import(m)
