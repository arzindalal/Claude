"""
Vector store wrapper over ChromaDB using local sentence-transformer embeddings.

Collections
-----------
  requirements  — requirement text + title
  test_cases    — title + objective + steps + expected result
  defects       — summary + description

All collections use cosine distance so `similarity = 1 - distance` is valid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb import Settings
from sentence_transformers import SentenceTransformer

_EMBED_MODEL = "all-MiniLM-L6-v2"
_COLLECTION_NAMES = ("requirements", "test_cases", "defects")


class KBEmbedder:
    def __init__(self, chroma_path: str = "data/chroma") -> None:
        Path(chroma_path).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._model = SentenceTransformer(_EMBED_MODEL)

        # cosine distance: similarity = 1 - distance (range [0, 1])
        self._reqs = self._client.get_or_create_collection(
            "requirements", metadata={"hnsw:space": "cosine"}
        )
        self._tests = self._client.get_or_create_collection(
            "test_cases", metadata={"hnsw:space": "cosine"}
        )
        self._defects = self._client.get_or_create_collection(
            "defects", metadata={"hnsw:space": "cosine"}
        )

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    # ── Upsert helpers ────────────────────────────────────────────────────────

    def _upsert(
        self,
        collection: chromadb.Collection,
        records: list[dict],
    ) -> None:
        """
        Upsert records into a ChromaDB collection.

        Each record must have keys: id (str), text (str), metadata (dict).
        Metadata values must be str | int | float | bool — no nested objects.
        """
        if not records:
            return

        ids = [r["id"] for r in records]
        texts = [r["text"] for r in records]
        metadatas = [_sanitise_metadata(r.get("metadata", {})) for r in records]
        embeddings = self._embed(texts)

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    # ── Public write API ──────────────────────────────────────────────────────

    def add_requirements(self, records: list[dict]) -> None:
        """Upsert requirement records. Each dict: {id, text, metadata}."""
        self._upsert(self._reqs, records)

    def add_test_cases(self, records: list[dict]) -> None:
        """Upsert test-case records. Each dict: {id, text, metadata}."""
        self._upsert(self._tests, records)

    def add_defects(self, records: list[dict]) -> None:
        """Upsert defect records. Each dict: {id, text, metadata}."""
        self._upsert(self._defects, records)

    # ── Public query API ──────────────────────────────────────────────────────

    def query_similar_tests(self, requirement_text: str, n_results: int = 5) -> list[dict]:
        """Return test cases semantically similar to the given requirement text."""
        return self._query(self._tests, requirement_text, n_results)

    def query_similar_requirements(self, text: str, n_results: int = 5) -> list[dict]:
        """Return requirements semantically similar to the query text."""
        return self._query(self._reqs, text, n_results)

    def query_related_defects(self, requirement_text: str, n_results: int = 5) -> list[dict]:
        """Return defects semantically related to the given requirement text."""
        return self._query(self._defects, requirement_text, n_results)

    def _query(
        self,
        collection: chromadb.Collection,
        text: str,
        n_results: int,
    ) -> list[dict]:
        count = collection.count()
        if count == 0:
            return []

        safe_n = min(n_results, count)
        embedding = self._embed([text])
        results = collection.query(
            query_embeddings=embedding,
            n_results=safe_n,
            include=["documents", "metadatas", "distances"],
        )
        return _format_results(results)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        return {
            "requirements": self._reqs.count(),
            "test_cases": self._tests.count(),
            "defects": self._defects.count(),
        }


# ── Private utilities ─────────────────────────────────────────────────────────

def _sanitise_metadata(metadata: dict) -> dict[str, Any]:
    """Flatten metadata to ChromaDB-safe scalar types."""
    safe: dict[str, Any] = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            safe[k] = v
        elif v is None:
            safe[k] = ""
        else:
            safe[k] = str(v)
    return safe


def _format_results(results: dict) -> list[dict]:
    output = []
    if not results.get("ids") or not results["ids"][0]:
        return output
    for i, doc_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        output.append({
            "id": doc_id,
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "similarity": round(1.0 - distance, 4),
        })
    return output
