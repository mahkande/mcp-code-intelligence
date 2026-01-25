"""Database abstraction and ChromaDB implementation for MCP Code Intelligence."""

from .base import VectorDatabase, EmbeddingFunction
from .chroma import ChromaVectorDatabase
from .pooling import PooledChromaVectorDatabase

__all__ = [
    "VectorDatabase",
    "EmbeddingFunction",
    "ChromaVectorDatabase",
    "PooledChromaVectorDatabase",
]
