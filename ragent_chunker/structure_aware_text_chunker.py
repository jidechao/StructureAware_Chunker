from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
import re
from typing import Callable, TypeAlias
import uuid


ContextEnhanceFunc: TypeAlias = Callable[[str], str | None]
ChunkEnhanceFunc: TypeAlias = Callable[["VectorChunk", list["VectorChunk"], str], str | None]


@dataclass(frozen=True)
class TextBoundaryOptions:
    min_chars: int
    target_chars: int
    max_chars: int
    overlap_chars: int = 0


@dataclass(frozen=True)
class VectorChunk:
    content: str
    index: int
    chunk_id: str
    metadata: dict[str, object] = field(default_factory=dict)
    embedding_content: str | None = None


class _BlockKind(Enum):
    HEADING = "HEADING"
    CODE = "CODE"
    ATOMIC = "ATOMIC"
    PARA = "PARA"


@dataclass(frozen=True)
class _Block:
    kind: _BlockKind
    start: int
    end: int
    heading_level: int | None = None
    heading_text: str | None = None


class StructureAwareTextChunker:
    """Markdown-friendly chunker ported from the Java StructureAwareTextChunker."""

    _HEADING = re.compile(r"^#{1,6}\s+.*$")
    _CODE_FENCE = re.compile(r"^```.*$")
    _ATOMIC_IMAGE = re.compile(r'^!\[[^\]]*]\([^)]+\)(?:\s*"[^"]*")?\s*$')
    _ATOMIC_LINK = re.compile(r"^\[[^\]]+]\([^)]+\)\s*$")

    def chunk(
        self,
        text: str | None,
        config: TextBoundaryOptions,
        context_enhance: bool = False,
        enhance_func: ContextEnhanceFunc | None = None,
        chunk_enhance: bool = False,
        chunk_enhance_func: ChunkEnhanceFunc | None = None,
        structural_enhance: bool = False,
        document_context: str | None = None,
    ) -> list[VectorChunk]:
        text = self._resolve_input_text(text, context_enhance, enhance_func)
        if text is None or not text.strip():
            return []

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        document_context = self._resolve_document_context(text, document_context)

        blocks = self._segment_to_blocks(text)
        if not blocks:
            chunks = [VectorChunk(content=text, index=0, chunk_id=self._new_chunk_id())]
            chunks = self._resolve_structural_chunks(document_context, chunks, structural_enhance)
            return self._resolve_output_chunks(text, chunks, chunk_enhance, chunk_enhance_func)

        ranges = self._pack_blocks_to_chunks(
            blocks,
            min_chars=config.min_chars,
            target_chars=config.target_chars,
            max_chars=config.max_chars,
        )
        chunks = self._materialize(text, blocks, ranges, config.overlap_chars)

        chunks = [
            replace(chunk, index=index, chunk_id=self._new_chunk_id())
            for index, chunk in enumerate(chunks)
        ]
        chunks = self._resolve_structural_chunks(document_context, chunks, structural_enhance)
        return self._resolve_output_chunks(text, chunks, chunk_enhance, chunk_enhance_func)

    def chunk_file(
        self,
        path: str | Path,
        config: TextBoundaryOptions,
        encoding: str = "utf-8",
        context_enhance: bool = False,
        enhance_func: ContextEnhanceFunc | None = None,
        chunk_enhance: bool = False,
        chunk_enhance_func: ChunkEnhanceFunc | None = None,
        structural_enhance: bool = False,
        document_context: str | None = None,
    ) -> list[VectorChunk]:
        text = Path(path).read_text(encoding=encoding)
        return self.chunk(
            text,
            config,
            context_enhance=context_enhance,
            enhance_func=enhance_func,
            chunk_enhance=chunk_enhance,
            chunk_enhance_func=chunk_enhance_func,
            structural_enhance=structural_enhance,
            document_context=document_context,
        )

    @staticmethod
    def _resolve_input_text(
        text: str | None,
        context_enhance: bool,
        enhance_func: ContextEnhanceFunc | None,
    ) -> str | None:
        if not context_enhance:
            return text
        if enhance_func is None:
            raise ValueError("enhance_func is required when context_enhance=True")
        if text is None or not text.strip():
            return text
        enhanced = enhance_func(text)
        return enhanced.strip() if isinstance(enhanced, str) else enhanced

    @staticmethod
    def _resolve_output_chunks(
        text: str,
        chunks: list[VectorChunk],
        chunk_enhance: bool,
        chunk_enhance_func: ChunkEnhanceFunc | None,
    ) -> list[VectorChunk]:
        if not chunk_enhance:
            return chunks
        if chunk_enhance_func is None:
            raise ValueError("chunk_enhance_func is required when chunk_enhance=True")
        if not chunks:
            return chunks

        enhanced_chunks: list[VectorChunk] = []
        for chunk in chunks:
            enhanced = chunk_enhance_func(chunk, chunks, text)
            if isinstance(enhanced, str):
                metadata = dict(chunk.metadata)
                metadata["chunk_enhanced"] = True
                enhanced_chunks.append(replace(chunk, metadata=metadata, embedding_content=enhanced))
            else:
                enhanced_chunks.append(chunk)
        return enhanced_chunks

    def _resolve_structural_chunks(
        self,
        document_context: str,
        chunks: list[VectorChunk],
        structural_enhance: bool,
    ) -> list[VectorChunk]:
        if not structural_enhance:
            return chunks
        return [
            replace(
                chunk,
                embedding_content=self._build_embedding_content(document_context, chunk),
            )
            for chunk in chunks
        ]

    def _segment_to_blocks(self, text: str) -> list[_Block]:
        blocks: list[_Block] = []
        n = len(text)
        pos = 0

        in_fence = False
        fence_start = -1

        in_para = False
        para_start = -1

        while pos < n:
            line_end = self._index_of_newline(text, pos)
            line_end_with_newline = line_end + 1 if line_end < n and text[line_end] == "\n" else line_end
            line = text[pos:line_end]
            trimmed = self._trim_right_keep_left(line)

            if not in_fence and self._CODE_FENCE.match(trimmed):
                if in_para:
                    blocks.append(_Block(_BlockKind.PARA, para_start, pos))
                    in_para = False
                in_fence = True
                fence_start = pos
                pos = line_end_with_newline
                continue

            if in_fence:
                if self._CODE_FENCE.match(trimmed):
                    blocks.append(_Block(_BlockKind.CODE, fence_start, line_end_with_newline))
                    in_fence = False
                pos = line_end_with_newline
                continue

            if trimmed == "":
                if in_para:
                    blocks.append(_Block(_BlockKind.PARA, para_start, pos))
                    in_para = False
                pos = line_end_with_newline
                continue

            if self._HEADING.match(trimmed):
                if in_para:
                    blocks.append(_Block(_BlockKind.PARA, para_start, pos))
                    in_para = False
                level, heading_text = self._parse_heading(trimmed)
                blocks.append(
                    _Block(
                        _BlockKind.HEADING,
                        pos,
                        line_end_with_newline,
                        heading_level=level,
                        heading_text=heading_text,
                    )
                )
                pos = line_end_with_newline
                continue

            if self._ATOMIC_IMAGE.match(trimmed) or self._ATOMIC_LINK.match(trimmed):
                if in_para:
                    blocks.append(_Block(_BlockKind.PARA, para_start, pos))
                    in_para = False
                blocks.append(_Block(_BlockKind.ATOMIC, pos, line_end_with_newline))
                pos = line_end_with_newline
                continue

            if not in_para:
                in_para = True
                para_start = pos
            pos = line_end_with_newline

        if in_fence:
            blocks.append(_Block(_BlockKind.CODE, fence_start, n))
        elif in_para:
            blocks.append(_Block(_BlockKind.PARA, para_start, n))

        return self._coalesce_trailing_blanks(blocks, text)

    def _coalesce_trailing_blanks(self, blocks: list[_Block], text: str) -> list[_Block]:
        if not blocks:
            return blocks

        out: list[_Block] = []
        prev = blocks[0]
        for cur in blocks[1:]:
            if self._is_all_blank(text, prev.end, cur.start):
                prev = _Block(
                    prev.kind,
                    prev.start,
                    cur.start,
                    heading_level=prev.heading_level,
                    heading_text=prev.heading_text,
                )
            out.append(prev)
            prev = cur
        out.append(prev)
        return out

    def _pack_blocks_to_chunks(
        self,
        blocks: list[_Block],
        min_chars: int,
        target_chars: int,
        max_chars: int,
    ) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        i = 0

        while i < len(blocks):
            chunk_start = blocks[i].start
            chunk_end = blocks[i].end
            size = chunk_end - chunk_start

            j = i + 1
            while j < len(blocks):
                block = blocks[j]
                after_add = block.end - chunk_start

                if after_add <= max_chars:
                    chunk_end = block.end
                    size = after_add
                    j += 1
                else:
                    if size < min_chars:
                        chunk_end = block.end
                        size = after_add
                        j += 1
                    break

            ranges.append((chunk_start, chunk_end))
            i = j

        if len(ranges) >= 2:
            last_start, last_end = ranges[-1]
            if last_end - last_start < min(min_chars, target_chars // 2):
                prev_start, _ = ranges[-2]
                if last_end - prev_start <= max_chars * 2:
                    ranges[-2] = (prev_start, last_end)
                    ranges.pop()

        return ranges

    def _materialize(
        self,
        text: str,
        blocks: list[_Block],
        ranges: list[tuple[int, int]],
        overlap_chars: int,
    ) -> list[VectorChunk]:
        out: list[VectorChunk] = []
        prev_tail: str | None = None

        for index, (start, end) in enumerate(ranges):
            body = text[start:end]
            if overlap_chars > 0 and prev_tail:
                body = prev_tail + body

            heading_path = self._heading_path_for_range(blocks, end)
            metadata: dict[str, object] = {
                "heading_path": heading_path,
                "heading_path_text": self._heading_path_text(heading_path),
                "source_start": start,
                "source_end": end,
            }
            out.append(
                VectorChunk(
                    content=body,
                    index=index,
                    chunk_id=self._new_chunk_id(),
                    metadata=metadata,
                )
            )

            if overlap_chars > 0:
                prev_tail = self._tail_by_chars(text[start:end], overlap_chars)

        return out

    @staticmethod
    def _heading_path_for_range(blocks: list[_Block], end: int) -> list[str]:
        headings: list[str | None] = [None] * 6
        for block in blocks:
            if block.start >= end:
                break
            if block.kind != _BlockKind.HEADING or block.heading_level is None:
                continue
            level = block.heading_level
            if not 1 <= level <= 6:
                continue
            headings[level - 1] = block.heading_text or ""
            for index in range(level, 6):
                headings[index] = None
        return [heading for heading in headings if heading]

    @staticmethod
    def _parse_heading(line: str) -> tuple[int, str]:
        marker, _, text = line.partition(" ")
        return len(marker), text.strip()

    @staticmethod
    def _heading_path_text(heading_path: list[str]) -> str:
        return " > ".join(heading_path)

    def _resolve_document_context(self, text: str, document_context: str | None) -> str:
        if document_context is not None and document_context.strip():
            return document_context.strip()

        for line in text.splitlines():
            trimmed = self._trim_right_keep_left(line).strip()
            if not trimmed:
                continue
            if self._HEADING.match(trimmed):
                level, heading_text = self._parse_heading(trimmed)
                if level == 1 and heading_text:
                    return heading_text
            return self._truncate_context(trimmed)
        return ""

    @staticmethod
    def _truncate_context(text: str, limit: int = 120) -> str:
        return text if len(text) <= limit else text[:limit].rstrip() + "..."

    def _build_embedding_content(self, document_context: str, chunk: VectorChunk) -> str:
        parts: list[str] = []
        if document_context:
            parts.append(f"文档上下文：{document_context}")
        heading_path_text = str(chunk.metadata.get("heading_path_text") or "")
        if heading_path_text:
            parts.append(f"当前位置：{heading_path_text}")
        parts.append(f"当前分块：\n{chunk.content}")
        return "\n".join(parts)

    @staticmethod
    def _index_of_newline(text: str, start: int) -> int:
        index = text.find("\n", start)
        return len(text) if index < 0 else index

    @staticmethod
    def _trim_right_keep_left(text: str) -> str:
        end = len(text)
        while end > 0 and text[end - 1].isspace() and text[end - 1] not in ("\n", "\r"):
            end -= 1
        return text[:end]

    @staticmethod
    def _is_all_blank(text: str, start: int, end: int) -> bool:
        return all(ch in (" ", "\t", "\r", "\n") for ch in text[start:end])

    @staticmethod
    def _tail_by_chars(text: str, count: int) -> str:
        if count <= 0:
            return ""
        return text if len(text) <= count else text[-count:]

    @staticmethod
    def _new_chunk_id() -> str:
        return uuid.uuid4().hex
