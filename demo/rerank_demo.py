"""Rerank demo: run a semantic search and show whether Jina or transformers reranker was attempted.

Run:
python demo/rerank_demo.py
"""
import asyncio
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mcp_code_intelligence.core.search import SemanticSearchEngine
from mcp_code_intelligence.core.models import SearchResult

# Minimal mock DB returning two results with different initial scores
class MockDB:
    async def search(self, query, limit=10, filters=None, similarity_threshold=0.0):
        r1 = SearchResult(content="def foo(): pass", file_path=Path("a.py"), start_line=1, end_line=1, language="python", similarity_score=0.6, rank=1, chunk_type="function", function_name="foo", class_name=None)
        r2 = SearchResult(content="def bar(): pass", file_path=Path("b.py"), start_line=1, end_line=1, language="python", similarity_score=0.5, rank=2, chunk_type="function", function_name="bar", class_name=None)
        return [r1, r2]

async def main():
    db = MockDB()
    engine = SemanticSearchEngine(database=db, project_root=Path('.'), reranker_model_name='jinaai/jina-reranker-v2-base-multilingual')
    results = await engine.search('performance critical function', limit=2)
    print('Results after ranking:')
    for r in results:
        print(r.function_name, r.similarity_score)

if __name__ == '__main__':
    asyncio.run(main())
