"""SessionService: Handles connection, session management, and authentication."""

import os
from pathlib import Path
from loguru import logger

from ...config.thresholds import ThresholdConfig
from ...core.database import ChromaVectorDatabase
from ...core.embeddings import create_embedding_function
from ...core.exceptions import ProjectNotFoundError
from ...core.indexer import SemanticIndexer
from ...core.project import ProjectManager
from ...core.search import SemanticSearchEngine
from ...core.watcher import FileWatcher
from ...core.llm_client import LLMClient
from ...core.config_utils import (
    get_openai_api_key,
    get_openrouter_api_key,
    get_preferred_llm_provider,
)
from ...core.lsp_proxy import stop_proxies


class SessionService:
    """Manages MCP server sessions, connections, and authentication."""

    def __init__(self, project_root: Path, enable_file_watching: bool = True):
        """Initialize session service.

        Args:
            project_root: Project root directory
            enable_file_watching: Enable file watching for automatic reindexing
        """
        self.project_root = project_root
        self.project_manager = ProjectManager(self.project_root)

        # Session state
        self.search_engine: SemanticSearchEngine | None = None
        self.file_watcher: FileWatcher | None = None
        self.indexer: SemanticIndexer | None = None
        self.database: ChromaVectorDatabase | None = None
        self.llm_client: LLMClient | None = None
        self.guardian = None

        self.enable_file_watching = enable_file_watching
        self._initialized = False
        self._enable_guardian = False
        self._enable_logic_check = False

    def _setup_logging(self) -> None:
        """Setup logging to file for background activity monitoring."""
        try:
            log_dir = self.project_root / ".mcp-code-intelligence" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "activity.log"

            # Add file logger (keep last 5MB of logs, rotation)
            logger.add(
                log_file,
                rotation="5 MB",
                retention="1 week",
                level="INFO",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
            )
            logger.info("--- MCP Session Started ---")
            logger.info(f"Project Root: {self.project_root}")
        except Exception as e:
            # Fallback to stdout if file logging fails
            print(f"Warning: Could not setup file logging: {e}")

    def _setup_database(self, config) -> None:
        """Setup database and embedding function.

        Args:
            config: Project configuration
        """
        # Setup embedding function
        embedding_function, _ = create_embedding_function(
            model_name=config.embedding_model
        )

        # Setup database
        self.database = ChromaVectorDatabase(
            persist_directory=config.index_path,
            embedding_function=embedding_function,
        )

    def _setup_search_engine(self, config) -> None:
        """Setup search engine.

        Args:
            config: Project configuration
        """
        if not self.database:
            raise RuntimeError("Database not initialized")

        self.search_engine = SemanticSearchEngine(
            database=self.database,
            project_root=self.project_root,
            reranker_model_name=config.reranker_model,
        )

    def _setup_llm_client(self) -> None:
        """Setup LLM client if API keys are available."""
        try:
            config_dir = self.project_root / ".mcp-code-intelligence"
            openai_key = get_openai_api_key(config_dir)
            openrouter_key = get_openrouter_api_key(config_dir)
            preferred = get_preferred_llm_provider(config_dir)

            if openai_key or openrouter_key:
                self.llm_client = LLMClient(
                    openai_api_key=openai_key,
                    openrouter_api_key=openrouter_key,
                    provider=preferred if preferred in ("openai", "openrouter") else None,
                )
                # Attach search engine for context injection
                try:
                    self.llm_client.search_engine = self.search_engine
                except Exception:
                    pass
                logger.info("LLM client initialized for context injection")
            else:
                logger.debug("No LLM API keys found; skipping LLM client initialization")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM client: {e}")

    def _setup_guardian(self) -> None:
        """Setup Guardian Manager for project health monitoring."""
        try:
            from ...analysis.guardian import GuardianManager
            if not self.database:
                raise RuntimeError("Database not initialized")
            self.guardian = GuardianManager(self.database, self.project_root)
        except Exception as e:
            logger.warning(f"Failed to initialize Guardian: {e}")

    def _setup_file_watcher(self, config) -> None:
        """Setup file watcher for automatic reindexing.

        Args:
            config: Project configuration
        """
        if not self.enable_file_watching:
            logger.info("File watching disabled")
            return

        if not self.database:
            raise RuntimeError("Database not initialized")

        self.indexer = SemanticIndexer(
            database=self.database,
            project_root=self.project_root,
            config=config,
        )

        # Setup file watcher
        self.file_watcher = FileWatcher(
            project_root=self.project_root,
            config=config,
            indexer=self.indexer,
            database=self.database,
        )

    async def initialize(self) -> None:
        """Initialize the session and all components.

        Raises:
            ProjectNotFoundError: If project is not initialized
        """
        if self._initialized:
            return

        try:
            # Setup logging
            self._setup_logging()

            # Load project configuration
            config = self.project_manager.load_config()

            # Setup database
            self._setup_database(config)
            await self.database.__aenter__()

            # Check if index is empty and auto-index if needed
            try:
                collection = self.database.get_collection()
                chunk_count = collection.count()

                if chunk_count == 0:
                    logger.info("Index is empty, starting automatic indexing...")
                    from ...cli.commands.index_runner import run_indexing

                    await run_indexing(
                        project_root=self.project_root,
                        force_reindex=False,
                        show_progress=False,
                        workers=None,
                        throttle=0.5,
                        max_size=10240,
                        important_only=False,
                    )
                    logger.info(f"Automatic indexing completed: {collection.count()} chunks indexed")
                else:
                    logger.info(f"Index already contains {chunk_count} chunks")
            except Exception as e:
                logger.warning(f"Could not check/create index: {e}")
                logger.info("You can manually run 'mcp-code-intelligence index' to create the index")

            # Setup search engine
            self._setup_search_engine(config)

            # Setup LLM client
            self._setup_llm_client()

            # Setup Guardian
            self._setup_guardian()
            self._enable_guardian = config.enable_guardian
            self._enable_logic_check = config.enable_logic_check

            # Setup file watcher
            await self._setup_file_watcher_async(config)

            self._initialized = True
            logger.info(f"Session initialized for project: {self.project_root}")

        except ProjectNotFoundError:
            logger.error(f"Project not initialized at {self.project_root}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            raise

    async def _setup_file_watcher_async(self, config) -> None:
        """Async wrapper for file watcher setup."""
        self._setup_file_watcher(config)
        if self.file_watcher:
            await self.file_watcher.start()
            logger.info("File watching enabled for automatic reindexing")

    async def cleanup(self) -> None:
        """Cleanup session resources."""
        # Stop file watcher if running
        if self.file_watcher and self.file_watcher.is_running:
            logger.info("Stopping file watcher...")
            await self.file_watcher.stop()
            self.file_watcher = None

        # Cleanup database connection
        if self.database and hasattr(self.database, "__aexit__"):
            await self.database.__aexit__(None, None, None)
            self.database = None

        # Clear references
        self.search_engine = None
        self.indexer = None
        self._initialized = False

        # Stop any running LSP proxies
        try:
            await stop_proxies(self.project_root)
        except Exception:
            logger.debug("Failed to stop LSP proxies during cleanup")

        logger.info("Session cleanup completed")

    @property
    def is_initialized(self) -> bool:
        """Check if session is initialized."""
        return self._initialized
