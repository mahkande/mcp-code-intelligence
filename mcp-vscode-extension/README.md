
# MCP VS Code Extension

## Why choose this over standard AI chat?

**MCP Code Intelligence tools provide advanced, project-specific capabilities that outperform generic AI chat in speed, accuracy, and context-awareness.**

### Key Tool Advantages

- **search_code**: Fast semantic code search using local Jina V3 vector engine. No token limits, instant results, context-aware (unlike standard AI chat's slow, token-limited grep).
- **search_similar**: Detects duplicate or similar logic across your codebase, saving time and reducing technical debt.
- **search_context**: Finds code by natural language description, leveraging project embeddings for precise results.
- **get_project_status**: Instantly shows indexing, language, and health status—no manual inspection needed.
- **index_project**: Local, parallel indexing for large codebases. Much faster than cloud-based AI parsing.
- **analyze_project / analyze_file**: Deep analysis (complexity, health, code smells) with no token or context window limits. Results are project-wide and actionable.
- **find_smells**: Pinpoints anti-patterns and code smells, improving code quality and maintainability.
- **get_complexity_hotspots**: Highlights the most complex files/functions for targeted refactoring.
- **check_circular_dependencies**: Detects hidden import cycles instantly—no need for manual graph analysis.
- **find_symbol / get_relationships**: Symbol search and call graph mapping with full project context, not just open files.
- **interpret_analysis**: Summarizes analysis for human or AI consumption, enabling smarter decisions.
- **find_duplicates**: Locates duplicate code blocks, reducing redundancy and improving maintainability.
- **silence_health_issue**: Suppresses noisy warnings, keeping your workflow focused.
- **propose_logic**: Prevents logic duplication before you code, saving tokens and review time.
- **impact_analysis**: Predicts the effect of changes before you refactor, avoiding costly mistakes.
- **Guardian (health/logic checks)**: Real-time health and duplication guard, ensuring codebase integrity.

**Token & Speed Benefits:**
- All tools run locally, so there are no token limits or API rate restrictions.
- Results are instant, even for large projects (thanks to vector search and parallel analysis).
- No cloud latency—your data stays private and fast.

**Quality & Context Benefits:**
- Tools use your project's full graph and embeddings, not just file snippets.
- Results are always relevant, actionable, and tailored to your codebase.

---

This extension provides a chat panel in VS Code that communicates with your MCP server, enforces project rules from `.cursorrules` and `.github/copilot-instructions.md`, and forwards chat messages to your MCP tools.

## Features
- Chat panel UI (Command Palette: `Open MCP Chat Panel`)
- Reads and displays project rule files
- Forwards chat to MCP server (Python)
- Shows MCP server responses in chat

## Development

1. Install dependencies:
   ```sh
   npm install
   ```
2. Compile:
   ```sh
   npm run compile
   ```
3. Launch extension (F5 in VS Code)

## Requirements
- Python (for MCP server)
- MCP server code in `src/mcp_code_intelligence/mcp/server.py`

## Notes
- MCP server otomatik başlatılır ve chat paneli ile entegre çalışır.
- Proje kökünde `.cursorrules` veya `.github/copilot-instructions.md` varsa, chat panelinde gösterilir.
