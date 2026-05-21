import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions


class StructureAwareTextChunkerTests(unittest.TestCase):
    def setUp(self):
        self.chunker = StructureAwareTextChunker()

    def chunk(self, text, min_chars=1, target_chars=20, max_chars=40, overlap_chars=0):
        return self.chunker.chunk(
            text,
            TextBoundaryOptions(
                min_chars=min_chars,
                target_chars=target_chars,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            ),
        )

    def test_blank_input_returns_empty_list(self):
        self.assertEqual([], self.chunker.chunk("", TextBoundaryOptions(1, 10, 20)))
        self.assertEqual([], self.chunker.chunk("   ", TextBoundaryOptions(1, 10, 20)))
        self.assertEqual([], self.chunker.chunk("\n\r\n\t", TextBoundaryOptions(1, 10, 20)))

    def test_windows_newlines_are_normalized(self):
        chunks = self.chunk("# Title\r\n\r\nBody\r\n\r\n![](img.png)\r\n", max_chars=100)

        self.assertEqual("# Title\n\nBody\n\n![](img.png)\n", "".join(c.content for c in chunks))

    def test_markdown_image_and_link_lines_remain_atomic(self):
        text = (
            "# Ragent\n\n"
            "Architecture overview.\n\n"
            "![Architecture](assets/ragent-module-layering-v2.png)\n\n"
            "[Docs](https://example.com/ragent)\n\n"
            "More text after the link.\n"
        )

        chunks = self.chunk(text, max_chars=55)
        contents = [chunk.content for chunk in chunks]

        self.assertEqual(text, "".join(contents))
        self.assertTrue(
            any("![Architecture](assets/ragent-module-layering-v2.png)\n\n" in content for content in contents)
        )
        self.assertTrue(any("[Docs](https://example.com/ragent)\n\n" in content for content in contents))

    def test_code_fence_is_kept_as_one_block(self):
        code_block = "```python\nprint('hello')\nprint('world')\n```\n\n"
        text = f"Intro paragraph.\n\n{code_block}Outro paragraph.\n"

        chunks = self.chunk(text, max_chars=35)

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertTrue(any(code_block in chunk.content for chunk in chunks))

    def test_unclosed_code_fence_is_kept_to_end(self):
        text = "Before.\n\n```python\nprint('open fence')\nno closing fence"

        chunks = self.chunk(text, max_chars=20)

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertTrue(any("```python\nprint('open fence')\nno closing fence" in chunk.content for chunk in chunks))

    def test_last_small_chunk_merges_with_previous_when_allowed(self):
        text = "First paragraph has enough text.\n\nTiny"

        chunks = self.chunk(text, min_chars=20, target_chars=20, max_chars=32)

        self.assertEqual(1, len(chunks))
        self.assertEqual(text, chunks[0].content)

    def test_overlap_prefixes_next_chunk_with_previous_tail(self):
        text = "Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph."

        chunks = self.chunk(text, min_chars=1, target_chars=10, max_chars=20, overlap_chars=5)

        self.assertGreaterEqual(len(chunks), 2)
        first_raw = "Alpha paragraph.\n\n"
        self.assertEqual(first_raw[-5:], chunks[1].content[:5])

    def test_chunk_file_reads_local_markdown_file(self):
        text = "# Local Markdown\n\nBody text.\n\n![](local.png)\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.md"
            path.write_text(text, encoding="utf-8")

            chunks = self.chunker.chunk_file(
                path,
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertTrue(any("![](local.png)" in chunk.content for chunk in chunks))

    def test_context_enhance_defaults_to_off_and_does_not_call_func(self):
        text = "# Raw\n\nOriginal text.\n"
        called = False

        def enhance(_):
            nonlocal called
            called = True
            return "# Enhanced\n\nUpdated text.\n"

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            enhance_func=enhance,
        )

        self.assertFalse(called)
        self.assertEqual(text, "".join(chunk.content for chunk in chunks))

    def test_context_enhance_uses_callback_result_for_chunking(self):
        raw = "# Raw\n\nOriginal text.\n"
        enhanced = "# Enhanced\n\nUpdated text.\n\n![](enhanced.png)\n"

        chunks = self.chunker.chunk(
            raw,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            context_enhance=True,
            enhance_func=lambda text: enhanced,
        )

        self.assertEqual(enhanced.strip(), "".join(chunk.content for chunk in chunks))
        self.assertTrue(any("![](enhanced.png)" in chunk.content for chunk in chunks))

    def test_context_enhance_requires_callback(self):
        with self.assertRaises(ValueError):
            self.chunker.chunk(
                "# Raw\n\nText.\n",
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
                context_enhance=True,
            )

    def test_context_enhance_strips_callback_result(self):
        chunks = self.chunker.chunk(
            "# Raw\n\nText.\n",
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            context_enhance=True,
            enhance_func=lambda text: "\n\n  # Enhanced\n\nText.  \n\n",
        )

        self.assertEqual("# Enhanced\n\nText.", "".join(chunk.content for chunk in chunks))

    def test_context_enhance_empty_callback_result_returns_empty_list(self):
        self.assertEqual(
            [],
            self.chunker.chunk(
                "# Raw\n\nText.\n",
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
                context_enhance=True,
                enhance_func=lambda text: "   \n",
            ),
        )
        self.assertEqual(
            [],
            self.chunker.chunk(
                "# Raw\n\nText.\n",
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
                context_enhance=True,
                enhance_func=lambda text: None,
            ),
        )

    def test_chunk_file_supports_context_enhance(self):
        raw = "# Local Markdown\n\nRaw text.\n"
        enhanced = "# Local Markdown\n\nEnhanced text.\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.md"
            path.write_text(raw, encoding="utf-8")

            chunks = self.chunker.chunk_file(
                path,
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
                context_enhance=True,
                enhance_func=lambda text: enhanced,
            )

        self.assertEqual(enhanced.strip(), "".join(chunk.content for chunk in chunks))

    def test_chunk_enhance_defaults_to_off_and_does_not_call_func(self):
        text = "Alpha paragraph.\n\nBeta paragraph."
        called = False

        def enhance(chunk, chunks, source_text):
            nonlocal called
            called = True
            return f"global\n\n{chunk.content}"

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
            chunk_enhance_func=enhance,
        )

        self.assertFalse(called)
        self.assertEqual(text, "".join(chunk.content for chunk in chunks))

    def test_chunk_enhance_updates_each_chunk_content(self):
        text = "Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
            chunk_enhance=True,
            chunk_enhance_func=lambda chunk, chunks, source_text: (
                f"Document context: greek letters\n\n{chunk.content}"
            ),
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertTrue(
            all(chunk.embedding_content.startswith("Document context: greek letters\n\n") for chunk in chunks)
        )
        self.assertEqual([0, 1, 2], [chunk.index for chunk in chunks])

    def test_chunk_enhance_receives_chunk_list_and_source_text(self):
        text = "Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph."
        seen = []

        def enhance(chunk, chunks, source_text):
            seen.append((chunk.index, len(chunks), source_text))
            return chunk.content

        self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
            chunk_enhance=True,
            chunk_enhance_func=enhance,
        )

        self.assertEqual([(0, 3, text), (1, 3, text), (2, 3, text)], seen)

    def test_chunk_enhance_none_result_keeps_original_chunk(self):
        text = "Alpha paragraph.\n\nBeta paragraph."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
            chunk_enhance=True,
            chunk_enhance_func=lambda chunk, chunks, source_text: None,
        )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))

    def test_chunk_enhance_requires_callback(self):
        with self.assertRaises(ValueError):
            self.chunker.chunk(
                "Alpha paragraph.",
                TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
                chunk_enhance=True,
            )

    def test_chunk_file_supports_chunk_enhance(self):
        text = "Alpha paragraph.\n\nBeta paragraph."

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.md"
            path.write_text(text, encoding="utf-8")

            chunks = self.chunker.chunk_file(
                path,
                TextBoundaryOptions(min_chars=1, target_chars=10, max_chars=20),
                chunk_enhance=True,
                chunk_enhance_func=lambda chunk, chunks, source_text: f"Global context\n\n{chunk.content}",
            )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertTrue(all(chunk.embedding_content.startswith("Global context\n\n") for chunk in chunks))

    def test_heading_path_metadata_tracks_markdown_hierarchy(self):
        text = (
            "# Ragent\n\n"
            "Overview paragraph.\n\n"
            "## Ingestion\n\n"
            "Parser paragraph.\n\n"
            "### Chunking\n\n"
            "Chunk paragraph.\n"
        )

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=26),
        )

        overview_chunk = next(chunk for chunk in chunks if "Overview paragraph." in chunk.content)
        ingestion_chunk = next(chunk for chunk in chunks if "Parser paragraph." in chunk.content)
        chunking_chunk = next(chunk for chunk in chunks if "Chunk paragraph." in chunk.content)

        self.assertEqual(["Ragent"], overview_chunk.metadata["heading_path"])
        self.assertEqual("Ragent > Ingestion", ingestion_chunk.metadata["heading_path_text"])
        self.assertEqual(["Ragent", "Ingestion", "Chunking"], chunking_chunk.metadata["heading_path"])

    def test_different_sections_get_different_heading_path_text(self):
        text = (
            "# Ragent\n\n"
            "## Retrieval\n\n"
            "Retrieval paragraph.\n\n"
            "## Ingestion\n\n"
            "Ingestion paragraph.\n"
        )

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=40),
        )

        heading_paths = [chunk.metadata["heading_path_text"] for chunk in chunks]
        self.assertIn("Ragent > Retrieval", heading_paths)
        self.assertIn("Ragent > Ingestion", heading_paths)

    def test_structural_enhance_sets_embedding_content_without_changing_content(self):
        text = "# Ragent\n\n## Retrieval\n\nRetrieval paragraph."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            structural_enhance=True,
            document_context="Ragent knowledge retrieval",
        )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertIn("文档上下文：Ragent knowledge retrieval", chunks[0].embedding_content)
        self.assertIn("当前位置：Ragent > Retrieval", chunks[0].embedding_content)
        self.assertIn("当前分块：\n# Ragent", chunks[0].embedding_content)

    def test_structural_enhance_infers_document_context_from_h1(self):
        text = "# Ragent Overview\n\nBody text."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            structural_enhance=True,
        )

        self.assertIn("文档上下文：Ragent Overview", chunks[0].embedding_content)

    def test_structural_enhance_infers_document_context_without_heading(self):
        text = "Plain document opening sentence.\n\nBody text."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            structural_enhance=True,
        )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertIn("文档上下文：Plain document opening sentence.", chunks[0].embedding_content)
        self.assertIn("当前分块：\nPlain document opening sentence.", chunks[0].embedding_content)

    def test_chunk_file_supports_structural_enhance(self):
        text = "# Local Markdown\n\n## Chunking\n\nBody text.\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.md"
            path.write_text(text, encoding="utf-8")

            chunks = self.chunker.chunk_file(
                path,
                TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
                structural_enhance=True,
                document_context="Local docs",
            )

        self.assertEqual(text, "".join(chunk.content for chunk in chunks))
        self.assertIn("文档上下文：Local docs", chunks[0].embedding_content)
        self.assertIn("当前位置：Local Markdown > Chunking", chunks[0].embedding_content)

    def test_vectorization_can_prefer_embedding_content_or_content(self):
        text = "# Ragent\n\nBody text."

        chunks = self.chunker.chunk(
            text,
            TextBoundaryOptions(min_chars=1, target_chars=20, max_chars=100),
            structural_enhance=True,
        )

        texts_for_embedding = [chunk.embedding_content or chunk.content for chunk in chunks]

        self.assertEqual([chunks[0].embedding_content], texts_for_embedding)


if __name__ == "__main__":
    unittest.main()
