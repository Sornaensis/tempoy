from __future__ import annotations

import unittest

from tempoy_app.formatting import markdown_to_adf


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


if __name__ == "__main__":
    unittest.main()
