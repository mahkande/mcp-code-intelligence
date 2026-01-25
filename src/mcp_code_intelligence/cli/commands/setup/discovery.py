import shutil
import time
from pathlib import Path
from loguru import logger
from ....core.project import ProjectManager
from ....config.defaults import get_language_from_extension
from ..install import detect_all_platforms

class DiscoveryManager:
    """Manages project analysis and environment discovery."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.project_manager = ProjectManager(project_root)

    def detect_languages(self) -> list[str]:
        """Detect project languages using ProjectManager."""
        return self.project_manager.detect_languages()

    def scan_file_extensions(self, timeout: float = 2.0) -> list[str] | None:
        """Scan project for unique file extensions with timeout."""
        extensions: set[str] = set()
        start_time = time.time()
        file_count = 0

        try:
            for path in self.project_root.rglob("*"):
                if time.time() - start_time > timeout:
                    logger.debug(f"File extension scan timed out after {timeout}s")
                    return None

                if not path.is_file():
                    continue

                if self.project_manager._should_ignore_path(path, is_directory=False):
                    continue

                ext = path.suffix
                if ext:
                    language = get_language_from_extension(ext)
                    if language != "text" or ext in [".txt", ".md", ".rst"]:
                        extensions.add(ext)
                file_count += 1

            return sorted(extensions) if extensions else None
        except Exception as e:
            logger.debug(f"File extension scan failed: {e}")
            return None

    def detect_ai_platforms(self):
        """Detect installed MCP platforms."""
        return detect_all_platforms()

    def check_claude_cli(self) -> bool:
        """Check if Claude CLI is available."""
        return shutil.which("claude") is not None

    def check_uv(self) -> bool:
        """Check if uv is available."""
        return shutil.which("uv") is not None
