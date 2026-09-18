import pytest
from src.services.parsers.factory import get_parser
from src.services.parsers.txt import TextParser
from src.services.parsers.md import MarkdownParser
from src.services.parsers.pdf import PDFParser


def test_text_parser():
    parser = TextParser()
    result = parser.parse(b"Hello World\nSecond line")
    assert len(result["sections"]) == 1
    assert result["sections"][0]["title"] == "Document"
    assert "Hello World" in result["sections"][0]["content"]


def test_markdown_parser():
    parser = MarkdownParser()
    content = "# Title\nSome content\n## Sub\nMore content"
    result = parser.parse(content.encode())
    assert len(result["sections"]) == 2
    assert result["sections"][0]["title"] == "Title"
    assert result["sections"][1]["title"] == "Sub"


def test_parser_factory():
    parser = get_parser("text/plain")
    assert isinstance(parser, TextParser)

    parser = get_parser("text/markdown")
    assert isinstance(parser, MarkdownParser)

    with pytest.raises(ValueError):
        get_parser("application/unknown")
