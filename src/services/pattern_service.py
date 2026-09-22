import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pattern import Pattern
from src.vectorstore.chroma_client import get_patterns_collection

logger = logging.getLogger(__name__)


class PatternService:
    def __init__(self):
        self.collection = get_patterns_collection()

    def _build_embedding_text(self, pattern: Pattern) -> str:
        parts = [
            f"Name: {pattern.name}",
            f"Intent: {pattern.intent}",
            f"Structure: {pattern.structure}",
            f"When to use: {pattern.when_to_use}",
        ]
        if pattern.strengths:
            parts.append(f"Strengths: {pattern.strengths}")
        if pattern.weaknesses:
            parts.append(f"Weaknesses: {pattern.weaknesses}")
        if pattern.example_use_case:
            parts.append(f"Example: {pattern.example_use_case}")
        if pattern.when_not_to_use:
            parts.append(f"When not to use: {pattern.when_not_to_use}")
        if pattern.prerequisites:
            parts.append(f"Prerequisites: {pattern.prerequisites}")
        if pattern.references:
            parts.append(f"References: {pattern.references}")
        if pattern.tags:
            parts.append(f"Tags: {', '.join(pattern.tags)}")
        return "\n".join(parts)

    async def upsert_pattern_embedding(self, pattern: Pattern) -> str:
        embedding_id = pattern.embedding_id or str(uuid.uuid4())
        text = self._build_embedding_text(pattern)
        metadata = {
            "name": pattern.name,
        }
        if pattern.tags:
            metadata["tags"] = pattern.tags
        self.collection.upsert(
            ids=[embedding_id],
            documents=[text],
            metadatas=[metadata],
        )
        return embedding_id

    async def remove_pattern_embedding(self, embedding_id: str):
        try:
            self.collection.delete(ids=[embedding_id])
        except Exception:
            pass

    async def search_patterns(
        self,
        query: str,
        tags: list[str] | None = None,
        n_results: int = 5,
    ) -> list[dict]:
        where_filter = None
        if tags:
            where_filter = {"tags": {"$in": tags}}

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter if where_filter else None,
        )

        output = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 0
                score = 1.0 - dist
                output.append({
                    "content": doc,
                    "metadata": meta,
                    "score": score,
                })
        return output


pattern_service = PatternService()
