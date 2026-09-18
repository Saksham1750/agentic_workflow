import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config import get_settings

settings = get_settings()

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_documents_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="documents",
        metadata={"hnsw:space": "cosine"},
    )


def get_patterns_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="patterns",
        metadata={"hnsw:space": "cosine"},
    )


async def check_chroma_health() -> bool:
    try:
        client = get_chroma_client()
        client.heartbeat()
        return True
    except Exception:
        return False
