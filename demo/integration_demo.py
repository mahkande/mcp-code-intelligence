"""Integration demo: index a code file, store a relationship with content_hash,
then query vectors and recall via the relationships table.

Run from repository root:
python demo/integration_demo.py
"""
import asyncio
import os
import shutil
import sys
import sqlite3
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mcp_code_intelligence.core.indexer import SemanticIndexer
from mcp_code_intelligence.core.models import CodeChunk, SearchResult, IndexStats

# Minimal in-memory mock DB (same interface expected by SemanticIndexer)
class MockDatabase:
    def __init__(self):
        self._chunks = {}

    async def initialize(self):
        return

    async def close(self):
        return

    async def add_chunks(self, chunks, metrics=None):
        print(f"[MockDatabase] add_chunks called for {len(chunks)} chunks")
        for c in chunks:
            self._chunks[c.chunk_id] = c

    async def delete_by_file(self, file_path: Path):
        to_delete = [k for k, v in self._chunks.items() if str(v.file_path) == str(file_path)]
        for k in to_delete:
            del self._chunks[k]
        return len(to_delete)

    async def get_hashes_for_file(self, file_path: Path):
        return {k: v.content_hash for k, v in self._chunks.items() if str(v.file_path) == str(file_path)}

    async def delete_chunks(self, chunk_ids):
        count = 0
        for cid in chunk_ids:
            if cid in self._chunks:
                del self._chunks[cid]
                count += 1
        return count

    async def get_all_chunks(self):
        return list(self._chunks.values())

    async def get_stats(self):
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

    async def search(self, query: str, limit: int = 10, filters: dict | None = None, similarity_threshold: float = 0.0):
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
            similarity_score=0.95,
            rank=1,
            chunk_type=c.chunk_type,
            function_name=c.function_name,
            class_name=c.class_name,
            navigation_hint=f"{c.file_path}:{c.start_line}",
            symbol_context=("function" if c.chunk_type in ("function","method") else "global"),
        )
        return [sr]


async def run_integration():
    sample_root = REPO_ROOT / "demo_sample_repo"
    if sample_root.exists():
        shutil.rmtree(sample_root)
    (sample_root / "src").mkdir(parents=True, exist_ok=True)

    f1 = sample_root / "src" / "onnx_handler.py"
    f1.write_text("""
# Example file discussing ONNX threading

def configure_onnx_threads():
    # We limit OMP/BLAS threads when running ONNX inference
    pass
""")

    mock_db = MockDatabase()
    indexer = SemanticIndexer(
        database=mock_db,
        project_root=sample_root,
        file_extensions=[".py"],
        config=None,
        max_workers=1,
        batch_size=2,
        embedding_batch_size=1,
        onnx_num_threads=1,
        use_multiprocessing=False,
    )

    print("--- Indexing sample files ---")
    all_files, files_to_index = await indexer.get_files_to_index(force_reindex=False)
    async for file_path, chunks_added, success in indexer.index_files_with_progress(files_to_index, force_reindex=False):
        print(f"Indexed {file_path}: chunks_added={chunks_added} success={success}")

    chunks = await mock_db.get_all_chunks()
    if not chunks:
        print("No chunks indexed; aborting demo")
        return
    c = chunks[0]
    # determine content_hash
    content_hash = getattr(c, "content_hash", None)
    if not content_hash:
        content_hash = hashlib.md5(c.content.encode("utf-8")).hexdigest()

    nav_hint = f"{c.file_path}:{c.start_line}"
    print("Indexed chunk navigation_hint=", nav_hint, " content_hash=", content_hash)

    # Create a lightweight relationships DB for demo in the sample_root
    mem_db_path = sample_root / "memory.db"
    if mem_db_path.exists():
        mem_db_path.unlink()
    conn = sqlite3.connect(mem_db_path)
    conn.execute('''
        CREATE TABLE relationships (
            key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            source_id TEXT,
            target_id TEXT,
            relationship_type TEXT,
            note TEXT,
            navigation_hint TEXT,
            content_hash TEXT,
            symbol_type TEXT,
            vector_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('CREATE INDEX idx_rel_content_hash ON relationships(content_hash)')
    conn.execute('CREATE INDEX idx_rel_nav ON relationships(navigation_hint)')

    rel_key = 'rel:demo1'
    note = 'This function is performance-critical; ONNX thread limits are managed here.'
    conn.execute(
        'INSERT INTO relationships (key, source, target, note, navigation_hint, content_hash, relationship_type, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
        (rel_key, 'onnx_handler', 'configure_onnx_threads', note, nav_hint, content_hash, 'performance')
    )
    conn.commit()

    # Now simulate a vector query
    print('--- Running semantic query ---')
    results = await mock_db.search('How do we handle ONNX threads?', limit=5)
    if not results:
        print('No search results')
        return
    r = results[0]
    print('Search returned navigation_hint=', r.navigation_hint)

    # Try recall via content_hash first
    cursor = conn.execute('SELECT key, source, target, note FROM relationships WHERE content_hash = ?', (content_hash,))
    row = cursor.fetchone()
    if row:
        print('Recall by content_hash found:', row)
    else:
        # fallback to navigation_hint LIKE
        cursor = conn.execute('SELECT key, source, target, note FROM relationships WHERE navigation_hint LIKE ?', (f"%{r.navigation_hint}%",))
        row2 = cursor.fetchone()
        if row2:
            print('Recall by navigation_hint found:', row2)
        else:
            print('Recall failed to find related note')

    conn.close()

    if row or row2:
        print('\nIntegration demo SUCCESS: recall found the stored note')
    else:
        print('\nIntegration demo FAILED: note not found')


if __name__ == '__main__':
    asyncio.run(run_integration())
