#!/bin/bash
# Post-installation verification script for mcp-code-intelligence
# This script verifies that all dependencies are correctly installed

set -e

echo "🔍 Verifying MCP Vector Search Installation..."
echo

# Check if mcp-code-intelligence is available
if ! command -v mcp-code-intelligence &> /dev/null; then
    echo "❌ mcp-code-intelligence command not found"
    echo "   Please install: pip install mcp-code-intelligence"
    exit 1
fi

echo "✓ mcp-code-intelligence command found"

# Run the doctor command
echo
echo "Running dependency check..."
echo

if mcp-code-intelligence doctor; then
    echo
    echo "✅ Installation verified successfully!"
    echo
    echo "Next steps:"
    echo "  1. Navigate to your project directory"
    echo "  2. Run: mcp-code-intelligence setup"
    echo "  3. Start searching: mcp-code-intelligence search \"your query\""
    echo
else
    echo
    echo "⚠️  Some dependencies are missing"
    echo
    echo "Try reinstalling:"
    echo "  pip install --upgrade --force-reinstall mcp-code-intelligence"
    echo
    exit 1
fi

