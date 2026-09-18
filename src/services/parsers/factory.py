from src.services.parsers.pdf import PDFParser
from src.services.parsers.docx import DOCXParser
from src.services.parsers.pptx import PPTXParser
from src.services.parsers.xlsx import XLSXParser
from src.services.parsers.md import MarkdownParser
from src.services.parsers.txt import TextParser

PARSER_MAP = {
    "application/pdf": PDFParser,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DOCXParser,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": PPTXParser,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XLSXParser,
    "text/markdown": MarkdownParser,
    "text/plain": TextParser,
}


def get_parser(content_type: str):
    parser_cls = PARSER_MAP.get(content_type)
    if not parser_cls:
        raise ValueError(f"No parser for content type: {content_type}")
    return parser_cls()
