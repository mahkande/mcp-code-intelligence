# MCP VS Code Extension

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
