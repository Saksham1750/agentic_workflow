from src.vectorstore.chroma_client import get_documents_collection


class EmbeddingService:
    def __init__(self):
        self.collection = get_documents_collection()

    def chunk_text(self, text: str, max_chunk_size: int = 1000, overlap: int = 200) -> list[str]:
        if len(text) <= max_chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_chunk_size
            chunk = text[start:end]

            if end < len(text):
                last_period = chunk.rfind(".")
                last_newline = chunk.rfind("\n")
                split_point = max(last_period, last_newline)
                if split_point > max_chunk_size * 0.5:
                    chunk = text[start:start + split_point + 1]
                    end = start + split_point + 1

            if chunk.strip():
                chunks.append(chunk.strip())
            start = end - overlap

        return chunks

    async def upsert_chunks(
        self,
        project_id: str,
        document_id: str,
        sections: list[dict],
    ) -> int:
        ids = []
        documents = []
        metadatas = []

        for section in sections:
            chunks = self.chunk_text(section.get("content", ""))
            for i, chunk in enumerate(chunks):
                chunk_id = f"{document_id}_{section['id']}_{i}"
                ids.append(chunk_id)
                documents.append(chunk)
                metadatas.append({
                    "project_id": project_id,
                    "document_id": document_id,
                    "section_id": section["id"],
                    "section_title": section.get("title", ""),
                    "page": section.get("page", 0),
                    "kind": "other",
                })

        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        return len(ids)

    async def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 5,
        document_id: str | None = None,
    ) -> list[dict]:
        where_filter = {"project_id": project_id}
        if document_id:
            where_filter["document_id"] = document_id

        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter,
        )

        output = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                output.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "score": results["distances"][0][i] if results["distances"] else 0,
                })
        return output


embedding_service = EmbeddingService()
