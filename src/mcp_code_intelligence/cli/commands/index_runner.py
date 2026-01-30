"""Index runner: orchestrates indexing, embedding setup, and database init."""
import asyncio
from pathlib import Path
from loguru import logger

from ...config.defaults import get_default_cache_path
from ...core.database import ChromaVectorDatabase
from ...core.embeddings import create_embedding_function
from ...core.exceptions import ProjectNotFoundError
from ...core.indexer import SemanticIndexer
from ...core.project import ProjectManager
from ..output import print_error, print_info

from .index_progress import _run_batch_indexing, _run_watch_mode


async def run_indexing(
    project_root: Path,
    watch: bool = False,
    incremental: bool = True,
    extensions: str | None = None,
    force_reindex: bool = False,
    batch_size: int = 32,
    show_progress: bool = True,
    debug: bool = False,
    skip_relationships: bool = False,
    workers: int | None = None,
    throttle: float = 0.0,
    max_size: int = 1024,
    important_only: bool = False,
) -> None:
    """Run the indexing process."""
    project_manager = ProjectManager(project_root)

    if not project_manager.is_initialized():
        raise ProjectNotFoundError(
            f"Project not initialized at {project_root}. Run 'mcp-code-intelligence init' first."
        )

    config = project_manager.load_config()

    if extensions:
        file_extensions = [ext.strip() for ext in extensions.split(",")]
        file_extensions = [ext if ext.startswith(".") else f".{ext}" for ext in file_extensions]
        config = config.model_copy(update={
            "file_extensions": file_extensions,
            "max_workers": workers,
            "throttle_delay": throttle,
            "max_file_size_kb": max_size,
            "index_important_only": important_only,
        })
    else:
        config = config.model_copy(update={
            "max_workers": workers,
            "throttle_delay": throttle,
            "max_file_size_kb": max_size,
            "index_important_only": important_only,
        })

    print_info(f"Indexing project: {project_root}")
    print_info(f"File extensions: {', '.join(config.file_extensions)}")
    print_info(f"Embedding model: {config.embedding_model}")

    cache_dir = (get_default_cache_path(project_root) if config.cache_embeddings else None)
    embedding_function, cache = create_embedding_function(
        model_name=config.embedding_model, cache_dir=cache_dir, cache_size=config.max_cache_size
    )

    database = ChromaVectorDatabase(persist_directory=config.index_path, embedding_function=embedding_function)

    indexer = SemanticIndexer(database=database, project_root=project_root, config=config)

    try:
        async with database:
            if watch:
                await _run_watch_mode(indexer, show_progress)
            else:
                indexable_files = indexer.scanner_service.scan_files()
                print_info(f"Indexable files: {len(indexable_files)}")
                await _run_batch_indexing(indexer, force_reindex, show_progress, skip_relationships)

    except Exception as e:
        logger.error(f"Indexing error: {e}")
        raise
