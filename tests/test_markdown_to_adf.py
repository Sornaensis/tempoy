from __future__ import annotations

import unittest

from tempoy_app.formatting import markdown_to_adf
from tempoy_app.services.jira_analysis_service import JiraAnalysisService


class MarkdownToAdfTests(unittest.TestCase):
    # -- plain text --

    def test_plain_text_becomes_paragraph(self) -> None:
        result = markdown_to_adf("Hello world")
        self.assertEqual(result, {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello world"}]}],
        })

    def test_empty_string_produces_empty_paragraph(self) -> None:
        result = markdown_to_adf("")
        self.assertEqual(result, {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": []}]})

    def test_multiple_paragraphs(self) -> None:
        result = markdown_to_adf("Line one\n\nLine two")
        paragraphs = result["content"]
        self.assertEqual(len(paragraphs), 2)
        self.assertEqual(paragraphs[0]["content"][0]["text"], "Line one")
        self.assertEqual(paragraphs[1]["content"][0]["text"], "Line two")

    # -- headings --

    def test_heading_levels(self) -> None:
        for level in range(1, 7):
            md = "#" * level + " Heading"
            result = markdown_to_adf(md)
            node = result["content"][0]
            self.assertEqual(node["type"], "heading")
            self.assertEqual(node["attrs"]["level"], level)
            self.assertEqual(node["content"][0]["text"], "Heading")

    # -- bold / italic / code / link --

    def test_bold_asterisks(self) -> None:
        result = markdown_to_adf("some **bold** text")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[0], {"type": "text", "text": "some "})
        self.assertEqual(nodes[1], {"type": "text", "text": "bold", "marks": [{"type": "strong"}]})
        self.assertEqual(nodes[2], {"type": "text", "text": " text"})

    def test_bold_underscores(self) -> None:
        result = markdown_to_adf("some __bold__ text")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[1]["marks"], [{"type": "strong"}])

    def test_italic_asterisk(self) -> None:
        result = markdown_to_adf("some *italic* text")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[1]["marks"], [{"type": "em"}])

    def test_italic_underscore(self) -> None:
        result = markdown_to_adf("some _italic_ text")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[1]["marks"], [{"type": "em"}])

    def test_inline_code(self) -> None:
        result = markdown_to_adf("use `foo()` here")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[1], {"type": "text", "text": "foo()", "marks": [{"type": "code"}]})

    def test_link(self) -> None:
        result = markdown_to_adf("see [docs](https://example.com)")
        nodes = result["content"][0]["content"]
        self.assertEqual(nodes[1]["text"], "docs")
        self.assertEqual(nodes[1]["marks"][0]["type"], "link")
        self.assertEqual(nodes[1]["marks"][0]["attrs"]["href"], "https://example.com")

    # -- fenced code blocks --

    def test_fenced_code_block(self) -> None:
        md = "```python\nprint('hi')\n```"
        result = markdown_to_adf(md)
        node = result["content"][0]
        self.assertEqual(node["type"], "codeBlock")
        self.assertEqual(node["attrs"]["language"], "python")
        self.assertEqual(node["content"][0]["text"], "print('hi')")

    def test_fenced_code_block_no_language(self) -> None:
        md = "```\nsome code\n```"
        result = markdown_to_adf(md)
        node = result["content"][0]
        self.assertEqual(node["type"], "codeBlock")
        self.assertNotIn("attrs", node)

    # -- unordered list --

    def test_unordered_list(self) -> None:
        md = "- one\n- two\n- three"
        result = markdown_to_adf(md)
        node = result["content"][0]
        self.assertEqual(node["type"], "bulletList")
        self.assertEqual(len(node["content"]), 3)
        self.assertEqual(node["content"][0]["content"][0]["content"][0]["text"], "one")

    def test_unordered_list_asterisk_and_plus(self) -> None:
        for marker in ["*", "+"]:
            md = f"{marker} item"
            result = markdown_to_adf(md)
            self.assertEqual(result["content"][0]["type"], "bulletList")

    # -- ordered list --

    def test_ordered_list(self) -> None:
        md = "1. first\n2. second"
        result = markdown_to_adf(md)
        node = result["content"][0]
        self.assertEqual(node["type"], "orderedList")
        self.assertEqual(len(node["content"]), 2)

    # -- mixed document --

    def test_mixed_document(self) -> None:
        md = (
            "# Title\n"
            "\n"
            "A paragraph with **bold** and *italic*.\n"
            "\n"
            "- item one\n"
            "- item two\n"
            "\n"
            "```\ncode\n```\n"
        )
        result = markdown_to_adf(md)
        types = [n["type"] for n in result["content"]]
        self.assertEqual(types, ["heading", "paragraph", "bulletList", "codeBlock"])

    # -- backward compatibility --

    def test_plain_multiline_no_markdown(self) -> None:
        md = "Line 1\nLine 2\nLine 3"
        result = markdown_to_adf(md)
        texts = [n["content"][0]["text"] for n in result["content"]]
        self.assertEqual(texts, ["Line 1", "Line 2", "Line 3"])

    # -- tables --

    def test_simple_table(self) -> None:
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        result = markdown_to_adf(md)
        table = result["content"][0]
        self.assertEqual(table["type"], "table")
        self.assertEqual(len(table["content"]), 2)
        # header row
        header_row = table["content"][0]
        self.assertEqual(header_row["content"][0]["type"], "tableHeader")
        self.assertEqual(header_row["content"][1]["type"], "tableHeader")
        # body row
        body_row = table["content"][1]
        self.assertEqual(body_row["content"][0]["type"], "tableCell")

    def test_table_cell_text(self) -> None:
        md = "| Name | Value |\n|---|---|\n| foo | bar |"
        result = markdown_to_adf(md)
        table = result["content"][0]
        header_cells = table["content"][0]["content"]
        self.assertEqual(header_cells[0]["content"][0]["content"][0]["text"], "Name")
        self.assertEqual(header_cells[1]["content"][0]["content"][0]["text"], "Value")
        body_cells = table["content"][1]["content"]
        self.assertEqual(body_cells[0]["content"][0]["content"][0]["text"], "foo")
        self.assertEqual(body_cells[1]["content"][0]["content"][0]["text"], "bar")

    def test_table_with_inline_formatting(self) -> None:
        md = "| H |\n| --- |\n| **bold** |"
        result = markdown_to_adf(md)
        body_cell = result["content"][0]["content"][1]["content"][0]
        para = body_cell["content"][0]
        self.assertEqual(para["content"][0]["marks"], [{"type": "strong"}])

    def test_table_no_separator_is_not_table(self) -> None:
        md = "| just | pipes |"
        result = markdown_to_adf(md)
        # Without a separator line it's not a table — treated as paragraph
        self.assertEqual(result["content"][0]["type"], "paragraph")

    def test_table_without_leading_pipes(self) -> None:
        md = "A | B\n--- | ---\n1 | 2"
        result = markdown_to_adf(md)
        self.assertEqual(result["content"][0]["type"], "table")

    def test_table_multiple_body_rows(self) -> None:
        md = "| H1 | H2 |\n|---|---|\n| a | b |\n| c | d |\n| e | f |"
        result = markdown_to_adf(md)
        table = result["content"][0]
        self.assertEqual(len(table["content"]), 4)  # 1 header + 3 body


class AdfToMarkdownTableTests(unittest.TestCase):
    """Tests for ADF table → markdown table extraction."""

    def setUp(self) -> None:
        self.svc = JiraAnalysisService(jira_base_url="https://jira.example.com")

    def test_adf_table_to_markdown(self) -> None:
        adf = {
            "type": "doc", "version": 1,
            "content": [{
                "type": "table",
                "content": [
                    {"type": "tableRow", "content": [
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Name"}]}]},
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value"}]}]},
                    ]},
                    {"type": "tableRow", "content": [
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "foo"}]}]},
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "bar"}]}]},
                    ]},
                ],
            }],
        }
        result = self.svc._extract_description_text(adf)
        self.assertIn("| Name | Value |", result)
        self.assertIn("| --- | --- |", result)
        self.assertIn("| foo | bar |", result)

    def test_adf_table_with_bold(self) -> None:
        adf = {
            "type": "doc", "version": 1,
            "content": [{
                "type": "table",
                "content": [
                    {"type": "tableRow", "content": [
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "H"}]}]},
                    ]},
                    {"type": "tableRow", "content": [
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
                        ]}]},
                    ]},
                ],
            }],
        }
        result = self.svc._extract_description_text(adf)
        self.assertIn("**bold**", result)

    def test_roundtrip_table(self) -> None:
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        adf = markdown_to_adf(md)
        result = self.svc._extract_description_text(adf)
        self.assertIn("| A | B |", result)
        self.assertIn("| --- | --- |", result)
        self.assertIn("| 1 | 2 |", result)

    def test_adf_table_no_header(self) -> None:
        """Table with only tableCell rows (no tableHeader) — no separator line."""
        adf = {
            "type": "doc", "version": 1,
            "content": [{
                "type": "table",
                "content": [
                    {"type": "tableRow", "content": [
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}]},
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "y"}]}]},
                    ]},
                ],
            }],
        }
        result = self.svc._extract_description_text(adf)
        self.assertIn("| x | y |", result)
        self.assertNotIn("---", result)

    def test_description_with_table_and_text(self) -> None:
        adf = {
            "type": "doc", "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Before table"}]},
                {"type": "table", "content": [
                    {"type": "tableRow", "content": [
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Col"}]}]},
                    ]},
                    {"type": "tableRow", "content": [
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "val"}]}]},
                    ]},
                ]},
                {"type": "paragraph", "content": [{"type": "text", "text": "After table"}]},
            ],
        }
        result = self.svc._extract_description_text(adf)
        self.assertIn("Before table", result)
        self.assertIn("| Col |", result)
        self.assertIn("After table", result)


if __name__ == "__main__":
    unittest.main()
