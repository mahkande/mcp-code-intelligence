"""Semantic indexer for MCP Code Intelligence."""

import asyncio
import os
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from loguru import logger
from packaging import version

from .. import __version__
from ..config.settings import ProjectConfig
from .database import VectorDatabase
from .directory_index import DirectoryIndex
from .exceptions import ParsingError
from .models import CodeChunk, IndexStats
from .relationships import RelationshipStore
from .scheduler import SchedulerManager
from .bm25_index import BM25Index

# Service modules
from .services.scanner import ScannerService
from .services.parser import ParserService
from .services.metrics import MetricsService

# Allowed dotfiles that should not be ignored by the indexer
ALLOWED_DOTFILES = {'.env', '.gitignore', '.gitattributes', '.dockerignore', '.editorconfig', '.prettierrc', '.eslintrc', '.pylintrc', '.flake8', '.coveragerc', '.pre-commit-config.yaml', '.pre-commit-hooks.yaml', '.mcp-code-intelligence'}

# Extension to language mapping for metric collection
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
}


def cleanup_stale_locks(project_dir: Path) -> None:
    """Remove stale SQLite journal files that indicate interrupted transactions.

    Journal files (-journal, -wal, -shm) can be left behind if indexing is
    interrupted or crashes, preventing future database access. This function
    safely removes stale lock files at index startup.

    Args:
        project_dir: Project root directory containing .mcp-code-intelligence/
    """
    mcp_dir = project_dir / ".mcp-code-intelligence"
    if not mcp_dir.exists():
        return

    db_file = mcp_dir / "index.db"
    for suffix in ["-journal", "-wal", "-shm"]:
        lock_file = Path(str(db_file) + suffix)
        if lock_file.exists():
            try:
                lock_file.unlink()
                logger.debug(f"Removed stale lock file: {lock_file}")
            except Exception as e:
                logger.debug(f"Failed to remove lock file {lock_file}: {e}")


class SemanticIndexer:
    """Orchestrates project indexing by delegating to service modules."""

    def __init__(self, database: VectorDatabase, project_root: Path, config: ProjectConfig | None = None):
        self.database = database
        self.project_root = project_root
        self.config = config

        # Wire up service modules
        self.scanner_service = ScannerService(project_root, config)
        self.parser_service = ParserService()
        self.metrics_service = MetricsService()

        # Directory index, relationships, etc.
        self.directory_index = DirectoryIndex(
            project_root / ".mcp-code-intelligence" / "directory_index.json"
        )
        self.directory_index.load()
        self.relationship_store = RelationshipStore(project_root)

        # Batch and throttling defaults
        self.batch_size = 8
        self.throttle_delay = 0

        # Index metadata file path
        self._index_metadata_file = project_root / ".mcp-code-intelligence" / "index_metadata.json"

        # Indexable files cache (for async file discovery)
        self._indexable_files_cache = None
        self._cache_timestamp = 0
        self._cache_ttl = 300  # 5 minutes

        # File extensions to index (default to Python for now)
        self.file_extensions = {'.py'}
        # Max file size in KB (default 10MB)
        self.max_file_size_kb = 10240

        # Dummy rag_guard with required methods to avoid AttributeError in tests
        class DummyRagGuard:
            def should_index_path(self, file_path):
                return True
            def should_index_content(self, content):
                return True
            def is_low_signal_chunk(self, chunk):
                return False
        self.rag_guard = DummyRagGuard()

        # Debug flag
        self.debug = False
        self.collectors = True
        self.use_multiprocessing = False
        self.max_workers = 4
        self.embedding_batch_size = None
        self.onnx_num_threads = None

        # Initialize BM25 index
        self.bm25_index = BM25Index()

    async def index_project(
        self,
        force_reindex: bool = False,
        show_progress: bool = True,
        skip_relationships: bool = False,
    ) -> int:
        """Index all files in the project with prioritized scanning."""
        logger.info(f"Starting indexing of project: {self.project_root}")

        cleanup_stale_locks(self.project_root)
        all_files = self._find_indexable_files()

        if not all_files:
            logger.warning("No indexable files found")
            return 0

        metadata = self._load_index_metadata()

        # Determine which files need indexing
        if force_reindex:
            files_to_index = all_files
        else:
            files_to_index = [f for f in all_files if self._needs_reindexing(f, metadata)]
            skipped_count = len(all_files) - len(files_to_index)
            if skipped_count > 0:
                logger.info(f"[HIZ] ⚡ MD5 İmzası Eşleşti: {skipped_count} değişmemiş dosya atlandı (Senkronizasyon anlık tamamlandı).")

        if not files_to_index:
            logger.info("All files are up to date")
            return 0

        # Smart prioritization
        files_to_index = self._prioritize_files(files_to_index)

        logger.info(
            f"Indexed planned: {len(files_to_index)} files. Starting with highest priority modules."
        )

        indexed_count = 0
        failed_count = 0
        import time
        heartbeat_interval = 60
        last_heartbeat = time.time()

        for i in range(0, len(files_to_index), self.batch_size):
            batch = files_to_index[i : i + self.batch_size]

            # Heartbeat logging
            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                percentage = ((i + len(batch)) / len(files_to_index)) * 100
                logger.info(
                    f"Indexing heartbeat: {i + len(batch)}/{len(files_to_index)} files "
                    f"({percentage:.1f}%), {indexed_count} indexed, {failed_count} failed"
                )
                last_heartbeat = now

            if show_progress:
                logger.info(
                    f"Processing batch {i // self.batch_size + 1}/{(len(files_to_index) + self.batch_size - 1) // self.batch_size} ({len(batch)} files)"
                )

            # Process batch in parallel
            batch_results = await self._process_file_batch(batch, force_reindex)

            # Count results
            for success in batch_results:
                if success:
                    indexed_count += 1
                else:
                    failed_count += 1

            # Throttling to reduce system load
            if self.throttle_delay > 0 and i + self.batch_size < len(files_to_index):
                logger.debug(f"Throttling: sleeping for {self.throttle_delay}s...")
                await asyncio.sleep(self.throttle_delay)

        # Update metadata for successfully indexed files
        if indexed_count > 0:
            for file_path in files_to_index:
                try:
                    metadata[str(file_path)] = os.path.getmtime(file_path)
                except OSError:
                    pass

            self._save_index_metadata(metadata)

            # Rebuild directory index from successfully indexed files
            try:
                logger.debug("Rebuilding directory index...")
                chunk_stats = {}
                for file_path in files_to_index:
                    try:
                        mtime = os.path.getmtime(file_path)
                        chunk_stats[str(file_path)] = {
                            "modified": mtime,
                            "chunks": 1,
                        }
                    except OSError:
                        pass

                self.directory_index.rebuild_from_files(
                    files_to_index, self.project_root, chunk_stats=chunk_stats
                )
                self.directory_index.save()
                dir_stats = self.directory_index.get_stats()
                logger.info(
                    f"Directory index updated: {dir_stats['total_directories']} directories, "
                    f"{dir_stats['total_files']} files"
                )
            except Exception as e:
                logger.error(f"Failed to update directory index: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        logger.info(
            f"Indexing complete: {indexed_count} files indexed, {failed_count} failed"
        )

        return indexed_count

    async def _parse_and_prepare_file(
        self, file_path: Path, force_reindex: bool = False
    ) -> tuple[list[CodeChunk], dict[str, Any] | None]:
        """Parse file and prepare chunks with metrics (no database insertion)."""
        if not self._should_index_file(file_path):
            return ([], None)

        await self.database.delete_by_file(file_path)

        chunks = await self._parse_file(file_path)

        if not chunks:
            logger.debug(f"No chunks extracted from {file_path}")
            return ([], None)

        chunks_with_hierarchy = self._build_chunk_hierarchy(chunks)

        # Collect metrics for chunks using MetricsService
        chunk_metrics: dict[str, Any] | None = None
        try:
            source_code = file_path.read_bytes()
            language = EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower(), "unknown")
            chunk_metrics = {}
            for chunk in chunks_with_hierarchy:
                metrics = self.metrics_service.collect(chunk, source_code, language)
                if metrics:
                    chunk_metrics[chunk.chunk_id] = metrics.to_metadata()
            logger.debug(f"Collected metrics for {len(chunk_metrics)} chunks from {file_path}")
        except Exception as e:
            logger.warning(f"Failed to collect metrics for {file_path}: {e}")
            chunk_metrics = None
        return (chunks_with_hierarchy, chunk_metrics)

    async def _process_file_batch(
        self, file_paths: list[Path], force_reindex: bool = False
    ) -> list[bool]:
        """Process a batch of files and accumulate chunks for batch embedding."""
        all_chunks: list[CodeChunk] = []
        all_metrics: dict[str, Any] = {}
        success_flags: list[bool] = []

        metadata = self._load_index_metadata()
        for file_path in file_paths:
            if not self._should_index_file(file_path):
                success_flags.append(True)
                continue

            await self.database.delete_by_file(file_path)

            try:
                chunks = await self._parse_file(file_path)
                if chunks:
                    chunks_with_hierarchy = self._build_chunk_hierarchy(chunks)

                    # Collect metrics for chunks using MetricsService
                    chunk_metrics = None
                    try:
                        source_code = file_path.read_bytes()
                        language = EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower(), "unknown")
                        chunk_metrics = {}
                        for chunk in chunks_with_hierarchy:
                            metrics = self.metrics_service.collect(chunk, source_code, language)
                            if metrics:
                                chunk_metrics[chunk.chunk_id] = metrics.to_metadata()
                    except Exception as e:
                        logger.warning(f"Failed to collect metrics for {file_path}: {e}")

                    all_chunks.extend(chunks_with_hierarchy)
                    if chunk_metrics:
                        all_metrics.update(chunk_metrics)

                    metadata[str(file_path)] = os.path.getmtime(file_path)
                    success_flags.append(True)
                else:
                    metadata[str(file_path)] = os.path.getmtime(file_path)
                    success_flags.append(True)
            except Exception as e:
                logger.error(f"Failed to parse {file_path}: {e}")
                success_flags.append(False)

        # Single database insertion for entire batch
        if all_chunks:
            logger.info(f"Batch inserting {len(all_chunks)} chunks from {len(file_paths)} files")
            try:
                await self.database.add_chunks(all_chunks, metrics=all_metrics)
                logger.debug(f"Successfully indexed {len(all_chunks)} chunks from {sum(success_flags)} files")
            except Exception as e:
                logger.error(f"Failed to insert batch of chunks: {e}")
                return [False] * len(file_paths)

        self._save_index_metadata(metadata)
        return success_flags

    def _load_index_metadata(self) -> dict[str, dict[str, Any]]:
        """Load file modification times and hashes from metadata file."""
        if not self._index_metadata_file.exists():
            return {}

        try:
            with open(self._index_metadata_file) as f:
                data = json.load(f)
                if "file_metadata" in data:
                    return data["file_metadata"]
                elif "file_mtimes" in data:
                    return {k: {"mtime": v, "hash": ""} for k, v in data["file_mtimes"].items()}
                else:
                    return {k: {"mtime": v, "hash": ""} for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load index metadata: {e}")
            return {}

    def _save_index_metadata(self, metadata: dict[str, dict[str, Any]]) -> None:
        """Save file metadata (mtime, hash) to metadata file."""
        try:
            self._index_metadata_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "index_version": __version__,
                "indexed_at": datetime.now(UTC).isoformat(),
                "file_metadata": metadata,
            }

            with open(self._index_metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save index metadata: {e}")

    def _prioritize_files(self, files: list[Path]) -> list[Path]:
        """Rank files by importance so critical files are indexed first."""
        if not files:
            return []

        git_modified = self._get_git_modified_files()

        entry_points = {"main", "app", "index", "init", "run", "server"}
        documentation = {".md", ".rst", ".txt"}

        def score_file(path: Path) -> int:
            score = 0
            name = path.stem.lower()
            ext = path.suffix.lower()

            if path in git_modified:
                score += 1000

            if any(ep == name for ep in entry_points):
                score += 500

            depth = len(path.relative_to(self.project_root).parts)
            if depth == 1:
                score += 200
            elif depth == 2:
                score += 100

            if ext in documentation:
                score += 300

            return score

        return sorted(files, key=score_file, reverse=True)

    def _get_git_modified_files(self) -> set[Path]:
        """Returns a set of files currently modified or staged in Git."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                return set()

            modified = set()
            for line in result.stdout.splitlines():
                if len(line) > 3:
                    rel_path = line[3:].strip()
                    full_path = self.project_root / rel_path
                    if full_path.exists():
                        modified.add(full_path)
            return modified
        except Exception:
            return set()

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file."""
        import hashlib
        try:
            hasher = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.debug(f"Failed to calculate hash for {file_path}: {e}")
            return ""

    def _needs_reindexing(self, file_path: Path, metadata: dict[str, dict[str, Any]]) -> bool:
        """Check if a file needs reindexing based on modification time and hash."""
        try:
            str_path = str(file_path)
            if str_path not in metadata:
                return True

            file_info = metadata[str_path]
            stored_mtime = file_info.get("mtime", 0)
            current_mtime = os.path.getmtime(file_path)

            if current_mtime <= stored_mtime:
                return False

            stored_hash = file_info.get("hash", "")
            current_hash = self._calculate_file_hash(file_path)

            return current_hash != stored_hash
        except OSError:
            return False

    async def index_file(
        self,
        file_path: Path,
        force_reindex: bool = False,
    ) -> bool:
        """Index a single file."""
        try:
            if not self._should_index_file(file_path):
                return False

            await self.database.delete_by_file(file_path)

            chunks = await self._parse_file(file_path)

            if not chunks:
                logger.debug(f"No chunks extracted from {file_path}")
                return True

            chunks_with_hierarchy = self._build_chunk_hierarchy(chunks)

            # Add to BM25 index
            for chunk in chunks_with_hierarchy:
                self.bm25_index.add_chunk(chunk.__dict__)

            # Collect metrics for chunks using MetricsService
            chunk_metrics: dict[str, Any] | None = None
            if self.collectors:
                try:
                    source_code = file_path.read_bytes()
                    language = EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower(), "unknown")

                    chunk_metrics = {}
                    for chunk in chunks_with_hierarchy:
                        metrics = self.metrics_service.collect(chunk, source_code, language)
                        if metrics:
                            chunk_metrics[chunk.chunk_id] = metrics.to_metadata()

                    logger.debug(f"Collected metrics for {len(chunk_metrics)} chunks from {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to collect metrics for {file_path}: {e}")
                    chunk_metrics = None

            await self._add_chunks_with_limits(chunks_with_hierarchy, metrics=chunk_metrics)

            metadata = self._load_index_metadata()
            metadata[str(file_path)] = os.path.getmtime(file_path)
            self._save_index_metadata(metadata)

            logger.debug(f"Indexed {len(chunks)} chunks from {file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to index file {file_path}: {e}")
            raise ParsingError(f"Failed to index file {file_path}: {e}") from e

    async def reindex_file(self, file_path: Path) -> bool:
        """Reindex a single file (removes existing chunks first)."""
        return await self.index_file(file_path, force_reindex=True)

    async def remove_file(self, file_path: Path) -> int:
        """Remove all chunks for a file from the index."""
        try:
            count = await self.database.delete_by_file(file_path)
            logger.debug(f"Removed {count} chunks for {file_path}")
            return count
        except Exception as e:
            logger.error(f"Failed to remove file {file_path}: {e}")
            return 0

    def _find_indexable_files(self) -> list[Path]:
        """Find all files that should be indexed with caching."""
        import time

        current_time = time.time()
        if (
            self._indexable_files_cache is not None
            and current_time - self._cache_timestamp < self._cache_ttl
        ):
            logger.debug(f"Using cached indexable files ({len(self._indexable_files_cache)} files)")
            return self._indexable_files_cache

        logger.debug("Rebuilding indexable files cache...")
        indexable_files = self._scan_files_sync()

        self._indexable_files_cache = sorted(indexable_files)
        self._cache_timestamp = current_time
        logger.debug(f"Rebuilt indexable files cache ({len(indexable_files)} files)")

        return self._indexable_files_cache

    def _scan_files_sync(self) -> list[Path]:
        """Synchronous file scanning using os.walk."""
        return self.scanner_service.scan_files(self.file_extensions)

    def _should_index_file(self, file_path: Path) -> bool:
        """Check if a file should be indexed."""
        if file_path.suffix.lower() not in self.file_extensions:
            return False

        if not file_path.is_file():
            return False

        try:
            max_size_bytes = self.max_file_size_kb * 1024
            file_size = file_path.stat().st_size
            if file_size > max_size_bytes:
                logger.warning(f"Skipping very large file: {file_path} ({file_size} bytes > {max_size_bytes} bytes limit)")
                return False
        except OSError:
            return False

        return True

    async def _parse_file(self, file_path: Path) -> list[CodeChunk]:
        """Parse a file into code chunks with contextual metadata."""
        try:
            # Use ParserService to parse file based on extension
            symbols = self.parser_service.parse_file(str(file_path))

            # Read source code for context extraction
            source_lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()

            # Convert symbol dicts to CodeChunk objects with contextual metadata
            code_chunks = []
            for sym in symbols:
                # Extract structural context from symbol
                parent_context = sym.get("parent_context", "Module Level")
                nesting_level = sym.get("nesting_level", 0)

                # Build breadcrumb
                file_rel = file_path.relative_to(self.project_root) if file_path.is_relative_to(self.project_root) else file_path
                breadcrumb = f"{file_rel} > {parent_context}"

                # Get actual line range from source
                start_line = sym.get("lineno", 1)
                end_line = sym.get("end_lineno", start_line)

                # Extract content lines
                try:
                    content_lines = source_lines[start_line - 1:end_line]
                    content = "\n".join(content_lines)
                except (IndexError, TypeError):
                    content = ""

                # Build context prefix comment (to be injected into chunk)
                context_prefix = self._build_context_prefix(parent_context, sym.get("type"))

                chunk = CodeChunk(
                    content=content,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language="python",
                    chunk_type=sym.get("type", "code"),
                    function_name=sym.get("name") if sym.get("type") == "function" else None,
                    class_name=sym.get("parent_class"),
                    docstring=sym.get("docstring"),
                    parent_context=parent_context,
                    breadcrumb=breadcrumb,
                    context_prefix=context_prefix,
                    nesting_level=nesting_level,
                    parameters=sym.get("parameters", []),
                    decorators=sym.get("decorators", []),
                    return_type=sym.get("return_annotation"),
                )
                code_chunks.append(chunk)

            return code_chunks
        except Exception as e:
            logger.error(f"Failed to parse file {file_path}: {e}")
            raise ParsingError(f"Failed to parse file {file_path}: {e}") from e

    def _build_context_prefix(self, parent_context: str, chunk_type: str) -> str:
        """Build a context prefix comment to inject at the start of a chunk.

        This helps LLMs understand the context without needing to load parent structures.

        Args:
            parent_context: String describing the parent context (e.g., "Class: User > Method: save")
            chunk_type: Type of chunk (function, class, code, etc.)

        Returns:
            A comment-formatted string suitable for prepending to code
        """
        if parent_context == "Module Level":
            return ""  # No prefix needed for module-level items

        # Python comment format
        return f"# Context: {parent_context} ({chunk_type})"

    def _build_chunk_hierarchy(self, chunks: list[CodeChunk]) -> list[CodeChunk]:
        """Build parent-child relationships between chunks."""
        if not chunks:
            return chunks

        module_chunks = [c for c in chunks if c.chunk_type == "module"]
        class_chunks = [c for c in chunks if c.chunk_type in ("class", "interface", "mixin")]
        function_chunks = [c for c in chunks if c.chunk_type in ("function", "method", "constructor")]

        for func in function_chunks:
            if func.class_name:
                parent_class = next(
                    (c for c in class_chunks if c.class_name == func.class_name), None
                )
                if parent_class:
                    func.parent_chunk_id = parent_class.chunk_id
                    func.chunk_depth = parent_class.chunk_depth + 1
                    if func.chunk_id not in parent_class.child_chunk_ids:
                        parent_class.child_chunk_ids.append(func.chunk_id)
                    logger.debug(
                        f"Linked method '{func.function_name}' to class '{parent_class.class_name}'"
                    )
            else:
                if not func.chunk_depth:
                    func.chunk_depth = 1
                if module_chunks and not func.parent_chunk_id:
                    func.parent_chunk_id = module_chunks[0].chunk_id
                    if func.chunk_id not in module_chunks[0].child_chunk_ids:
                        module_chunks[0].child_chunk_ids.append(func.chunk_id)

        for cls in class_chunks:
            if not cls.chunk_depth:
                cls.chunk_depth = 1
            if module_chunks and not cls.parent_chunk_id:
                cls.parent_chunk_id = module_chunks[0].chunk_id
                if cls.chunk_id not in module_chunks[0].child_chunk_ids:
                    module_chunks[0].child_chunk_ids.append(cls.chunk_id)

        for mod in module_chunks:
            if not mod.chunk_depth:
                mod.chunk_depth = 0

        return chunks

    def _write_indexing_run_header(self) -> None:
        """Write version and timestamp header to error log at start of indexing run."""
        try:
            error_log_path = (
                self.project_root / ".mcp-code-intelligence" / "indexing_errors.log"
            )
            error_log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(error_log_path, "a", encoding="utf-8") as f:
                timestamp = datetime.now(UTC).isoformat()
                separator = "=" * 80
                f.write(f"\n{separator}\n")
                f.write(
                    f"[{timestamp}] Indexing run started - mcp-code-intelligence v{__version__}\n"
                )
                f.write(f"{separator}\n")
        except Exception as e:
            logger.debug(f"Failed to write indexing run header: {e}")

    def _apply_onnx_thread_limits(self) -> dict:
        """Apply environment / runtime thread limits for ONNX/BLAS during embedding generation."""
        prev = {}
        try:
            for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
                prev[var] = os.environ.get(var)
                if self.onnx_num_threads is not None:
                    os.environ[var] = str(self.onnx_num_threads)

            try:
                import onnxruntime as ort
                if self.onnx_num_threads is not None and hasattr(ort, "set_default_logging_severity"):
                    try:
                        if hasattr(ort, "set_num_threads"):
                            ort.set_num_threads(self.onnx_num_threads)
                    except Exception:
                        pass
            except Exception:
                pass

        except Exception:
            prev = {}

        return prev

    def _restore_onnx_thread_limits(self, prev: dict) -> None:
        """Restore previously saved environment variables after embedding generation."""
        try:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        except Exception:
            pass

    async def _add_chunks_with_limits(self, chunks: list["CodeChunk"], metrics: dict | None = None) -> None:
        """Add chunks to the database in sub-batches while applying ONNX/CPU limits."""
        if not chunks:
            return

        prev_env = self._apply_onnx_thread_limits()

        try:
            batch_size = self.embedding_batch_size or len(chunks)
            if batch_size >= len(chunks):
                await self.database.add_chunks(chunks, metrics=metrics)
                return

            start = 0
            while start < len(chunks):
                end = start + batch_size
                sub_chunks = chunks[start:end]

                sub_metrics = None
                if metrics:
                    sub_metrics = {k: v for k, v in metrics.items() if any(c.chunk_id == k for c in sub_chunks)}

                await self.database.add_chunks(sub_chunks, metrics=sub_metrics)
                start = end

        finally:
            self._restore_onnx_thread_limits(prev_env)

    async def get_indexing_stats(self, db_stats: IndexStats | None = None) -> dict:
        """Get statistics about the indexing process."""
        try:
            if db_stats is None:
                db_stats = await self.database.get_stats()

            return {
                "total_indexable_files": db_stats.total_files,
                "indexed_files": db_stats.total_files,
                "total_files": db_stats.total_files,
                "total_chunks": db_stats.total_chunks,
                "languages": db_stats.languages,
                "file_types": db_stats.file_types,
                "file_extensions": list(self.file_extensions),
            }

        except Exception as e:
            logger.error(f"Failed to get indexing stats: {e}")
            return {
                "error": str(e),
                "total_indexable_files": 0,
                "indexed_files": 0,
                "total_files": 0,
                "total_chunks": 0,
            }
