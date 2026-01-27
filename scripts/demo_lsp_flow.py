"""Demo: start a Python LSP from project .mcp/mcp.json, create a sample file,
call goto_definition via the proxy and print rich formatted output.

Run from repo root with PYTHONPATH set to mcp-vector-search/src
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp_code_intelligence.core.lsp_proxy import start_proxies, get_manager, stop_proxies
from mcp_code_intelligence.core import formatters


async def main():
    repo = Path.cwd() / "mcp-vector-search"
    project_root = repo

    # Ensure .mcp exists and write config for python LSP
    mcp_dir = project_root / ".mcp"
    mcp_dir.mkdir(exist_ok=True)
    cfg = {
        "languageLsps": {
            "python": {
                "command": sys.executable,
                "args": ["-m", "pylsp"]
            }
        }
    }
    cfg_path = mcp_dir / "mcp.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Wrote {cfg_path}")

    # Create a demo Python file
    demo_dir = project_root / "demo"
    demo_dir.mkdir(exist_ok=True)
    sample = demo_dir / "sample.py"
    lines = [
        "def helper(x):\n",
        "    return x * 2\n",
        "\n",
        "def target(y):\n",
        "    return helper(y)\n",
        "\n",
        "def main():\n",
        "    a = helper(3)\n",
        "    return a\n",
    ]
    sample.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote demo file: {sample}")

    # Start proxies
    print("Starting LSP proxies...")
    await start_proxies(project_root)
    mgr = get_manager(project_root)
    # Wait a bit for LSP to be ready
    await asyncio.sleep(1.0)

    # Call goto_definition from the call site in main (line index 7 -> 0-based 7)
    # Find the position of 'helper' in line 8 (1-based)
    ref_line = 7  # zero-based index for line containing 'a = helper(3)'
    char_pos = lines[ref_line].index("helper")

    params = {
        "textDocument": {"uri": sample.as_uri()},
        "position": {"line": ref_line, "character": char_pos},
    }

    try:
        print("Requesting definition from LSP...")
        res = await mgr.request("python", "textDocument/definition", params)
        print("Raw LSP response:\n", res)

        # Format for MCP-rich output
        contents = formatters.format_definition_response(res)
        print("\nFormatted MCP TextContent blocks:")
        for c in contents:
            # EmbeddedResource may not be present; handle generically
            if hasattr(c, "text") and c.text:
                print("--- TextContent ---")
                print(c.text)
            else:
                # Attempt to print fields for EmbeddedResource-like objects
                try:
                    print("--- EmbeddedResource ---")
                    print(f"name={c.name}, media_type={getattr(c, 'media_type', '')}")
                    print(getattr(c, "data", ""))
                except Exception:
                    print(repr(c))

    finally:
        print("Stopping LSP proxies...")
        await stop_proxies(project_root)


if __name__ == "__main__":
    asyncio.run(main())
