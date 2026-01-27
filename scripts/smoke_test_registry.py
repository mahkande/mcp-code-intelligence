from pathlib import Path
import importlib

from mcp_code_intelligence.core.tool_registry import get_mcp_tools

FILE_TOOL_NAMES = {
    "read_file",
    "goto_definition",
    "find_references",
    "get_hover_info",
    "get_completions",
    "search_similar",
}


def print_tools(tools):
    for t in tools:
        try:
            name = t.name
        except Exception:
            name = t.get("name") if isinstance(t, dict) else str(t)
        schema = getattr(t, "inputSchema", {}) or (t.get("inputSchema") if isinstance(t, dict) else {}) or {}
        props = schema.get("properties", {})
        print(f"- {name}: properties={list(props.keys())}")


def check_relative_param(tools):
    ok = True
    for t in tools:
        try:
            name = t.name
        except Exception:
            name = t.get("name") if isinstance(t, dict) else str(t)
        if name in FILE_TOOL_NAMES:
            schema = getattr(t, "inputSchema", {}) or (t.get("inputSchema") if isinstance(t, dict) else {}) or {}
            props = schema.get("properties", {})
            if "relative_path" not in props:
                print(f"MISSING relative_path in tool: {name}")
                ok = False
    return ok


def main():
    project_root = Path.cwd()

    print("=== Initial discovery ===")
    tools = get_mcp_tools(project_root)
    print_tools(tools)
    rel_ok = check_relative_param(tools)
    print(f"Relative-path consistency: {'OK' if rel_ok else 'FAIL'}")

    print("\n=== Mocking python_lsp_server.PYLSP_AVAILABLE = False and rediscovering ===")
    try:
        mod = importlib.import_module("mcp_code_intelligence.servers.python_lsp_server")
        setattr(mod, "PYLSP_AVAILABLE", False)
        print("Mock applied: python_lsp_server.PYLSP_AVAILABLE = False")
    except Exception as e:
        print("Warning: could not import/mock python_lsp_server:", e)

    tools2 = get_mcp_tools(project_root)
    print_tools(tools2)

    names = [t.name for t in tools2]
    fix_present = "fix_python_lsp_unavailable" in names
    print(f"fix_python_lsp_unavailable present: {fix_present}")

    if rel_ok and fix_present:
        print("\nBAŞARILI")
    else:
        print("\nBAŞARISIZ")


if __name__ == '__main__':
    main()
