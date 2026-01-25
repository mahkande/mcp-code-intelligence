import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from mcp_code_intelligence.cli.main import app

runner = CliRunner()
with tempfile.TemporaryDirectory() as tmpdir:
    os.chdir(tmpdir)
    os.makedirs("test_project", exist_ok=True)
    os.chdir("test_project")

    # Initialize
    with patch(
        "mcp_code_intelligence.cli.commands.init.confirm_action", return_value=False
    ):
        result = runner.invoke(app, ["init", "main", "--extensions", ".py", "--force"])

    print(f"Init exit code: {result.exit_code}")

    # Index
    result = runner.invoke(app, ["index", "main"])

    print(f"Index exit code: {result.exit_code}")
    print(f"Index output snippet: {result.output[:500]}")

    # Check if index directory exists
    project_path = Path.cwd()
    index_dir = project_path / ".mcp-code-intelligence" / "index"
    print(f"Index dir exists: {index_dir.exists()}")
    print(f"Index dir: {index_dir}")

    # List all files in .mcp-code-intelligence
    mcp_dir = project_path / ".mcp-code-intelligence"
    if mcp_dir.exists():
        print(f"Files in .mcp-code-intelligence: {list(mcp_dir.iterdir())}")


