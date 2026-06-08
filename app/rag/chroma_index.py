from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings


class KnowledgeDocLike(Protocol):
    id: str
    title: str
    category: str
    source: str
    tags: list[str]
    content: str


TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ChromaSearchHit:
    doc_id: str
    score: float
    excerpt: str
    metadata: dict[str, Any]


class HashEmbeddingFunction:
    """Deterministic local embeddings so Chroma works without model downloads."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def __call__(self, input: list[str]) -> list[list[float]]:  # Chroma embedding protocol
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 8) / 8
            vector[index] += sign * weight
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]


class ChromaKnowledgeIndex:
    def __init__(self, collection_name: str | None = None) -> None:
        import chromadb

        settings.resolved_chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.resolved_chroma_path))
        self.embedding = HashEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=collection_name or settings.chroma_collection,
            embedding_function=self.embedding,
            metadata={"hnsw:space": "cosine"},
        )

    def ensure_indexed(self, documents: list[KnowledgeDocLike], version: str) -> None:
        if not documents:
            return
        ids = [doc.id for doc in documents]
        metadatas = [
            {
                "title": doc.title,
                "category": doc.category,
                "source": doc.source,
                "tags": ",".join(doc.tags),
                "version": version,
            }
            for doc in documents
        ]
        contents = [_document_text(doc) for doc in documents]
        self.collection.upsert(ids=ids, documents=contents, metadatas=metadatas)

    def query(self, query: str, categories: list[str] | None = None, top_k: int = 5) -> list[ChromaSearchHit]:
        where = None
        if categories:
            if len(categories) == 1:
                where = {"category": categories[0]}
            else:
                where = {"$or": [{"category": category} for category in categories]}
        result = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[ChromaSearchHit] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for doc_id, document, metadata, distance in zip(ids, docs, metadatas, distances):
            score = max(0.0, 1.0 - float(distance))
            hits.append(
                ChromaSearchHit(
                    doc_id=str(doc_id),
                    score=score,
                    excerpt=_excerpt(str(document)),
                    metadata=dict(metadata or {}),
                )
            )
        return hits

    def evaluate(self, cases: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
        if not cases:
            return {"case_count": 0, "hit_rate": 0.0, "mrr": 0.0, "cases": []}
        evaluated = []
        hits = 0
        reciprocal_sum = 0.0
        for case in cases:
            expected = set(case.get("expected_doc_ids", []))
            retrieved = self.query(str(case["query"]), categories=case.get("categories"), top_k=top_k)
            retrieved_ids = [hit.doc_id for hit in retrieved]
            rank = next((idx + 1 for idx, doc_id in enumerate(retrieved_ids) if doc_id in expected), None)
            if rank:
                hits += 1
                reciprocal_sum += 1 / rank
            evaluated.append(
                {
                    "query": case["query"],
                    "expected_doc_ids": sorted(expected),
                    "retrieved_doc_ids": retrieved_ids,
                    "hit": rank is not None,
                    "rank": rank,
                }
            )
        return {
            "case_count": len(cases),
            "hit_rate": round(hits / len(cases), 3),
            "mrr": round(reciprocal_sum / len(cases), 3),
            "cases": evaluated,
        }


def _document_text(doc: KnowledgeDocLike) -> str:
    return f"{doc.title}\n分类：{doc.category}\n标签：{'、'.join(doc.tags)}\n来源：{doc.source}\n内容：{doc.content}"


def _excerpt(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."
