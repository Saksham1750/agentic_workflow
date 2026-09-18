import uuid


class TextParser:
    def parse(self, content: bytes) -> dict:
        text = content.decode("utf-8", errors="replace")
        sections = []

        if text.strip():
            sections = [{"id": str(uuid.uuid4()), "title": "Document", "page": 1, "content": text}]

        return {"sections": sections, "total_pages": 1}
