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
    "mcp_code_intelligence.core.exceptions",
    "mcp_code_intelligence.core.project",
    "mcp_code_intelligence.core.lsp_proxy",
    "mcp_code_intelligence.parsers.registry",
    "mcp_code_intelligence.mcp.services",
    "mcp_code_intelligence.analysis",
    "mcp_code_intelligence.mcp.server"
]

for m in modules:
    test_import(m)
