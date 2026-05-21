import sys

from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

chunker = StructureAwareTextChunker()

chunks = chunker.chunk_file(
    r".\samples\README.md",
    TextBoundaryOptions(
        min_chars=600,
        target_chars=1400,
        max_chars=1800,
        overlap_chars=0,
    ),
    structural_enhance=True,
    document_context="Ragent 项目说明与知识库检索能力介绍",
)

for chunk in chunks:
    print("index:", chunk.index, "chunk_id:", chunk.chunk_id)
    print("heading_path:", chunk.metadata.get("heading_path"))
    print("heading_path_text:", chunk.metadata.get("heading_path_text"))
    print("content:", chunk.content)
    print("embedding_content:", chunk.embedding_content)
    print("text_for_embedding:", chunk.embedding_content or chunk.content)
    print("-" * 100)
