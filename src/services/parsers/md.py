import uuid
import markdown


class MarkdownParser:
    def parse(self, content: bytes) -> dict:
        text = content.decode("utf-8", errors="replace")
        sections = []
        current_section = {"id": str(uuid.uuid4()), "title": "Untitled", "page": 1, "content": ""}

        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                if current_section["content"].strip():
                    sections.append(current_section)
                current_section = {
                    "id": str(uuid.uuid4()),
                    "title": stripped.lstrip("#").strip(),
                    "page": 1,
                    "content": "",
                }
            else:
                current_section["content"] += line + "\n"

        if current_section["content"].strip():
            sections.append(current_section)

        if not sections:
            sections = [{"id": str(uuid.uuid4()), "title": "Document", "page": 1, "content": text}]

        return {"sections": sections, "total_pages": 1}
