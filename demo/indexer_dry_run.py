"""Indexer dry-run demo for mcp-code-intelligence

Creates a small sample project, a MockDatabase, runs the SemanticIndexer twice
to demonstrate incremental indexing (content_hash skipping) and applies ONNX
thread limits during embedding/add_chunks.

Run from repository root with: python demo/indexer_dry_run.py
"""
import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure local package import works
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mcp_code_intelligence.core.indexer import SemanticIndexer
from mcp_code_intelligence.core.models import CodeChunk, SearchResult, IndexStats

# Simple in-memory mock VectorDatabase matching the minimal interface used by the indexer
class MockDatabase:
    def __init__(self):
        # store chunks by chunk_id
        self._chunks: Dict[str, CodeChunk] = {}

    async def initialize(self):
        return

    async def close(self):
        return

    async def add_chunks(self, chunks: List[CodeChunk], metrics: Dict[str, Any] | None = None):
        # Observe environment thread limits to confirm indexer applied them
        thread_vars = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
        print("[MockDatabase] add_chunks called for", len(chunks), "chunks; thread env:", thread_vars)
        for c in chunks:
            self._chunks[c.chunk_id] = c

    async def delete_by_file(self, file_path: Path) -> int:
        to_delete = [k for k, v in self._chunks.items() if str(v.file_path) == str(file_path)]
        for k in to_delete:
            del self._chunks[k]
        return len(to_delete)

    async def get_hashes_for_file(self, file_path: Path) -> Dict[str, str]:
        result = {k: v.content_hash for k, v in self._chunks.items() if str(v.file_path) == str(file_path)}
        return result

    async def delete_chunks(self, chunk_ids: List[str]) -> int:
        count = 0
        for cid in chunk_ids:
            if cid in self._chunks:
                del self._chunks[cid]
                count += 1
        return count

    async def get_all_chunks(self) -> List[CodeChunk]:
        return list(self._chunks.values())

    async def get_stats(self) -> IndexStats:
        files = set(v.file_path for v in self._chunks.values())
        return IndexStats(
            total_files=len(files),
            total_chunks=len(self._chunks),
            languages={"python": len(self._chunks)},
            file_types={".py": len(self._chunks)},
            index_size_mb=0.0,
            last_updated="now",
            embedding_model="mock",
            database_size_bytes=0,
        )

    # minimal search stub for demo
    async def search(self, query: str, limit: int = 10, filters: dict | None = None, similarity_threshold: float = 0.0):
        # Return first chunk as a SearchResult if present
        chunks = list(self._chunks.values())
        if not chunks:
            return []
        c = chunks[0]
        sr = SearchResult(
            content=c.content,
            file_path=c.file_path,
            start_line=c.start_line,
            end_line=c.end_line,
            language=c.language,
            similarity_score=0.92,
            rank=1,
            chunk_type=c.chunk_type,
            function_name=c.function_name,
            class_name=c.class_name,
            navigation_hint=f"{c.file_path}:{c.start_line}",
            symbol_context=("function" if c.chunk_type in ("function", "method") else "global"),
        )
        return [sr]


async def run_dry_run():
    sample_root = REPO_ROOT / "demo_sample_repo"
    if sample_root.exists():
        shutil.rmtree(sample_root)
    (sample_root / "src").mkdir(parents=True, exist_ok=True)

    # Remove any stale index metadata from previous runs
    meta_path = sample_root / ".mcp-code-intelligence" / "index_metadata.json"
    if meta_path.exists():
        try:
            meta_path.unlink()
        except Exception:
            pass

    # Create two small python files
    f1 = sample_root / "src" / "onnx_handler.py"
    f1.write_text("""
# Example file discussing ONNX threading

def configure_onnx_threads():
    # We limit OMP/BLAS threads when running ONNX inference
    pass
""")

    f2 = sample_root / "src" / "util.py"
    f2.write_text("""
# Utility functions

def helper():
    return 42
""")

    # Initialize mock DB and indexer
    mock_db = MockDatabase()
    indexer = SemanticIndexer(
        database=mock_db,
        project_root=sample_root,
        file_extensions=[".py"],
        config=None,
        max_workers=1,
        batch_size=2,
        embedding_batch_size=1,
        onnx_num_threads=2,
        use_multiprocessing=False,
    )

    print("--- First indexing run (should index files and apply ONNX thread limits) ---")
    all_files, files_to_index = await indexer.get_files_to_index(force_reindex=False)
    # Run incremental index flow with progress
    indexed_total = 0
    async for file_path, chunks_added, success in indexer.index_files_with_progress(files_to_index, force_reindex=False):
        print(f"Indexed file: {file_path} -> chunks_added={chunks_added}, success={success}")
        if success and chunks_added >= 0:
            indexed_total += 1
    print("Indexed count (files):", indexed_total)

    print("--- Second indexing run (should skip files via content_hash) ---")
    all_files2, files_to_index2 = await indexer.get_files_to_index(force_reindex=False)
    indexed_total2 = 0
    async for file_path, chunks_added, success in indexer.index_files_with_progress(files_to_index2, force_reindex=False):
        print(f"Second run - file: {file_path} -> chunks_added={chunks_added}, success={success}")
        if success and chunks_added >= 0:
            indexed_total2 += 1
    print("Indexed count on second run (expected 0):", indexed_total2)

    print("--- Querying semantic search for 'How do we handle ONNX threads?' ---")
    results = await mock_db.search("How do we handle ONNX threads?", limit=5)
    if not results:
        print("No results returned")
    else:
        for r in results:
            d = r.to_dict()
            print("SearchResult:", d)


if __name__ == "__main__":
    asyncio.run(run_dry_run())
