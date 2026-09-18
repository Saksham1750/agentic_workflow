from src.services.embedding_service import embedding_service


class RAGService:
    async def query_documents(
        self,
        project_id: str,
        query: str,
        n_results: int = 5,
        document_id: str | None = None,
    ) -> list[dict]:
        return await embedding_service.query(
            project_id=project_id,
            query_text=query,
            n_results=n_results,
            document_id=document_id,
        )


rag_service = RAGService()
