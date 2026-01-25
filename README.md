# 🚀 MCP Code Intelligence

**Transform your AI Assistant (Claude, Cursor, Windsurf) into a Senior Developer who *actually* knows your codebase.**

`mcp-code-intelligence` is a high-performance Model Context Protocol (MCP) server that provides **deep semantic understanding**, **smart navigation**, and **extreme token efficiency** using local vector embeddings (Jina v3) and Language Server Protocol (LSP) integration.

---

## 💎 Why choose this over standard AI chat?

| Feature | Standard AI Chat | MCP Code Intelligence |
| :--- | :--- | :--- |
| **Context Window** | Fills up with redundant code | **Used only for critical logic** |
| **Token Cost** | $$$ (sends whole files) | **$ (sends only relevant chunks)** |
| **Understanding** | Path-based keywords | **Semantic/Meaning-based search** |
| **Speed** | Slow file listing | **Instant symbol navigation** |
| **Large Projects** | Chokes on 100+ files | **Prioritized indexing (Top-Down)** |

---

## 📈 Token Efficiency & Cost Reduction

Our **Smart Chunking** and **Semantic Retrieval** strategy dramatically reduces the amount of "noise" sent to the LLM (Claude/GPT-4).

- **📉 60-80% Lower Token Usage:** Instead of sending 500 lines of a file, we send 2-3 relevant 20-line chunks.
- **🧠 2x Smarter Context:** By using **Jina v3 embeddings** locally, the AI receives only the most semantically relevant code, leading to fewer hallucinations and more accurate bug fixes.
- **⚡ Incremental Indexing:** MD5 fingerprinting ensures we only index what you change. Your CPU stays cool.

---

## ✨ Cutting-Edge Features

- **🌍 Multi-Language Zeka (LSP Integration):**
  - **Python:** Full type intelligence via `python-lsp-server`.
  - **JS/TS:** Smart navigation via `typescript-language-server`.
  - **Dart/Flutter:** Mobile development optimized zeka.
  - **Rust / Go / C++:** Fully supported high-performance LSPs.
- **⚡ Smart Priority Indexing:** Large project? No problem. The system indexes your **Git changes**, **Entry Points**, and **READMEs** in the first 60 seconds, so you can start working while the rest finishes in the background.
- **🏠 100% Local Intelligence:** All vector operations and embeddings stay on your machine. No code ever leaves your project.

---

## 🚀 Quick Start (One-Command Setup)

Get up and running in any project in under a minute:

```bash
# 1. Clone the repository
git clone https://github.com/mahkande/mcp-code-intelligence.git
cd mcp-code-intelligence

# 2. Install the package locally (Editable mode)
pip install -e .

# 3. Run the smart setup wizard
mcp-code-intelligence setup
```

The smart setup will:
1.  **Detect** your languages & platforms (Claude Desktop, Cursor, etc.)
2.  **Download** optimized Jina v3 weights.
3.  **Prioritize** and index your codebase.
4.  **Inject** configurations into your AI tools automatically.

---

## 📖 Command Reference

### 🧠 Intelligence & Search
- `mcp-code-intelligence setup`: The recommended way to start. Auto-detects everything and configures your environment.
- `mcp-code-intelligence search "query"`: Semantic search using natural language.
- `mcp-code-intelligence chat "question"`: Interactive LLM chat about your codebase (requires OpenRouter API key).
- `mcp-code-intelligence analyze`: Run complexity and quality analysis (Cognitive/Cyclomatic complexity, Code Smells).

### 📊 Status & Visualization
- `mcp-code-intelligence status`: Check indexing progress, database health, and project statistics.
- `mcp-code-intelligence visualize serve`: Launch a local 3D interactive graph of your code structure in your browser.
- `mcp-code-intelligence doctor`: Diagnostic tool to check dependencies (Python, Node, Git) and path configurations.

### 🛠️ Maintenance & Advanced
- `mcp-code-intelligence index`: Manually trigger or force re-indexing of the codebase.
- `mcp-code-intelligence reset`: Clean slate. Deletes existing indexes and restores factory settings.
- `mcp-code-intelligence config`: Fine-tune settings like `similarity_threshold` or change embedding models.

### 📺 Monitoring
- `mcp-code-intelligence onboarding logs`: **The Live Dashboard.** Monitor background activities, search logs, and AI tool interactions in real-time.

---

## 🛠️ Requirements
- **Python 3.10+**
- **Git** (for smart prioritization)
- **Node.js** (Optional, for JS/TS LSP support)

---

**Built by developers, for developers who value their context window (and their wallet).** 🛡️✨
