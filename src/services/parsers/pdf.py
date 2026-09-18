import uuid
from pypdf import PdfReader


class PDFParser:
    def parse(self, content: bytes) -> dict:
        import io
        reader = PdfReader(io.BytesIO(content))
        sections = []
        current_section = {"id": str(uuid.uuid4()), "title": "Untitled", "page": 0, "content": ""}

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            lines = text.split("\n")

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                if stripped.startswith("#") and len(stripped) > 1:
                    if current_section["content"].strip():
                        sections.append(current_section)
                    current_section = {
                        "id": str(uuid.uuid4()),
                        "title": stripped.lstrip("#").strip(),
                        "page": page_num + 1,
                        "content": "",
                    }
                else:
                    current_section["content"] += stripped + "\n"

        if current_section["content"].strip():
            sections.append(current_section)

        if not sections:
            full_text = "\n".join(p.extract_text() or "" for p in reader.pages)
            sections = [{"id": str(uuid.uuid4()), "title": "Document", "page": 1, "content": full_text}]

        return {"sections": sections, "total_pages": len(reader.pages)}
