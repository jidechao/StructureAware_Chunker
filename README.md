# Ragent Python 结构感知分块器使用说明

`ragent_chunker` 提供了一个面向 Markdown 文档的结构感知分块器。它不会按固定字符数硬切文本，而是先识别标题、段落、代码块、图片、链接等结构块，再按 `min_chars / target_chars / max_chars` 打包成适合向量化和检索的 chunk。

适合处理知识库 Markdown、图文混排文档、代码说明文档和普通文本。

## 功能特点

- 保留 Markdown 标题、段落、代码围栏等结构边界。
- 将整行图片 `![...](...)` 和整行链接 `[...] (...)` 作为原子块处理。
- 支持按文件路径读取并分块。
- 支持可选的上下文增强回调。
- 支持可选的分块后增强回调。
- 支持结构路径感知的内置增强文本生成。
- 支持 chunk 间字符重叠。
- 无第三方依赖，使用 Python 标准库即可运行。

## 目录结构

```text
python/
├── demo.py
├── README.md
├── ragent_chunker/
│   ├── __init__.py
│   └── structure_aware_text_chunker.py
└── tests/
    └── test_structure_aware_text_chunker.py
```

## 快速开始

在项目根目录执行：

```powershell
cd StructureAware_Chunker
$env:PYTHONPATH = ".\python"
.\.venv\Scripts\python.exe .\python\demo.py
```

也可以直接进入 `python` 目录运行：

```powershell
cd StructureAware_Chunker\python
..\.venv\Scripts\python.exe .\demo.py
```

如果不使用项目虚拟环境，确保当前 Python 版本支持 `str | None` 类型写法，建议使用 Python 3.10 或更高版本。

## 最小示例

```python
from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions

text = """# Ragent 核心设计

Ragent 采用前后端分离架构。

![](assets/ragent-module-layering-v2.png)

一次用户提问会经过问题改写、意图识别、检索和回答生成。
"""

chunker = StructureAwareTextChunker()

chunks = chunker.chunk(
    text,
    TextBoundaryOptions(
        min_chars=100,
        target_chars=300,
        max_chars=500,
        overlap_chars=0,
    ),
)

for chunk in chunks:
    print(chunk.index)
    print(chunk.chunk_id)
    print(chunk.content)
```

## 从文件分块

```python
from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions

chunker = StructureAwareTextChunker()

chunks = chunker.chunk_file(
    r".\README.md",
    TextBoundaryOptions(
        min_chars=600,
        target_chars=1400,
        max_chars=1800,
        overlap_chars=0,
    ),
    encoding="utf-8",
)

for chunk in chunks:
    print("index:", chunk.index)
    print("chunk_id:", chunk.chunk_id)
    print("content:", chunk.content)
```

## 参数说明

`TextBoundaryOptions` 用来控制分块大小。

| 参数              | 含义                                                  |
| --------------- | --------------------------------------------------- |
| `min_chars`     | 单个 chunk 的期望最小字符数。当前块太小时会尽量继续合并下一个结构块。              |
| `target_chars`  | 单个 chunk 的目标字符数。当前实现主要用于判断尾部小块是否合并。                 |
| `max_chars`     | 单个 chunk 的期望最大字符数。正常情况下不会继续加入会导致超限的结构块。             |
| `overlap_chars` | chunk 间重叠字符数。大于 0 时，会把上一个 chunk 的尾部复制到下一个 chunk 前面。 |

推荐起步配置：

```python
TextBoundaryOptions(
    min_chars=600,
    target_chars=1400,
    max_chars=1800,
    overlap_chars=0,
)
```

如果检索结果需要更强上下文连续性，可以开启少量重叠：

```python
TextBoundaryOptions(
    min_chars=600,
    target_chars=1400,
    max_chars=1800,
    overlap_chars=120,
)
```

## 输出结构

`chunk()` 和 `chunk_file()` 都返回 `list[VectorChunk]`。

| 字段                  | 含义                                                |
| ------------------- | ------------------------------------------------- |
| `content`           | 分块后的原文内容，用于展示、引用和回答拼接。                            |
| `index`             | chunk 顺序，从 0 开始。                                  |
| `chunk_id`          | 自动生成的唯一 ID，使用 32 位 UUID hex 字符串。                  |
| `metadata`          | 结构元数据，例如 `heading_path`、`heading_path_text`、原文范围。 |
| `embedding_content` | 用于向量化检索的增强文本。未开启增强时为 `None`。                      |

示例：

```python
for chunk in chunks:
    payload = {
        "id": chunk.chunk_id,
        "index": chunk.index,
        "content": chunk.content,
        "metadata": chunk.metadata,
        "embedding_content": chunk.embedding_content,
    }
    print(payload)
```

## 分块前增强

如果分块前需要先对文档做增强，可以设置 `context_enhance=True` 并传入 `enhance_func`。

```python
from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions

def enhance(text: str) -> str:
    return "# 文档摘要\n\n这是增强后的上下文。\n\n" + text

chunker = StructureAwareTextChunker()

chunks = chunker.chunk(
    "# 原始文档\n\n正文内容。",
    TextBoundaryOptions(
        min_chars=100,
        target_chars=300,
        max_chars=500,
    ),
    context_enhance=True,
    enhance_func=enhance,
)
```

注意：

- `context_enhance=False` 时不会调用 `enhance_func`。
- `context_enhance=True` 时必须传入 `enhance_func`。
- `enhance_func` 返回空字符串或 `None` 时，最终返回空列表。
- 增强结果会先执行 `strip()`，再进入分块流程。

## 分块后增强

如果需要给每个 chunk 注入额外检索上下文，可以设置 `chunk_enhance=True` 并传入 `chunk_enhance_func`。

这个能力适合在生成 embedding 前使用。增强结果会写入 `chunk.embedding_content`，原始 `chunk.content` 不会被污染。

```python
from ragent_chunker import StructureAwareTextChunker, TextBoundaryOptions

def enhance_chunk(chunk, chunks, source_text):
    global_context = (
        "文档上下文：本文介绍 Ragent 的 RAG 架构、检索链路和知识库处理流程。"
    )
    return f"{global_context}\n\n当前分块：\n{chunk.content}"

chunker = StructureAwareTextChunker()

chunks = chunker.chunk(
    "# Ragent 核心设计\n\nRagent 采用多路检索。\n\n知识库文档会先解析再分块。",
    TextBoundaryOptions(
        min_chars=20,
        target_chars=80,
        max_chars=120,
    ),
    chunk_enhance=True,
    chunk_enhance_func=enhance_chunk,
)
```

`chunk_enhance_func` 会收到三个参数：

| 参数            | 含义                            |
| ------------- | ----------------------------- |
| `chunk`       | 当前正在增强的 `VectorChunk`。        |
| `chunks`      | 本次分块产生的完整 chunk 列表。           |
| `source_text` | 分块前的完整文本。若开启了分块前增强，这里是增强后的文本。 |

注意：

- `chunk_enhance=False` 时不会调用 `chunk_enhance_func`。
- `chunk_enhance=True` 时必须传入 `chunk_enhance_func`。
- `chunk_enhance_func` 返回字符串时，会写入当前 chunk 的 `embedding_content`。
- `chunk_enhance_func` 返回 `None` 时，会保留当前 chunk 的原始 `content`。
- `index` 和 `chunk_id` 不会因为分块后增强而改变。

也可以只追加一个全局摘要：

```python
summary = "全局摘要：本文说明 Ragent 的结构感知分块和向量检索流程。"

chunks = chunker.chunk_file(
    r".\README.md",
    TextBoundaryOptions(
        min_chars=600,
        target_chars=1400,
        max_chars=1800,
    ),
    chunk_enhance=True,
    chunk_enhance_func=lambda chunk, chunks, source_text: (
        f"{summary}\n\n{chunk.content}"
    ),
)
```

## 结构路径感知增强

如果希望每个 chunk 自动带上不同的结构路径信息，可以开启 `structural_enhance=True`。

它会把下面这些信息拼进 `embedding_content`：

```text
文档上下文：{document_context}
当前位置：{heading_path_text}
当前分块：
{content}
```

示例：

```python
chunks = chunker.chunk(
    "# Ragent\n\n## Retrieval\n\n向量检索负责召回候选文档。",
    TextBoundaryOptions(
        min_chars=20,
        target_chars=80,
        max_chars=120,
    ),
    structural_enhance=True,
    document_context="Ragent 知识库检索设计",
)

for chunk in chunks:
    print(chunk.metadata["heading_path"])
    print(chunk.metadata["heading_path_text"])
    print(chunk.embedding_content)
```

说明：

- `metadata["heading_path"]` 是标题路径数组。
- `metadata["heading_path_text"]` 是标题路径的可读文本形式。
- `document_context` 不传时，会优先使用一级标题；没有标题时，使用文档开头文本。

## 向量化接入建议

生成 embedding 时，优先使用：

```python
text_for_embedding = chunk.embedding_content or chunk.content
```

这样既能利用增强文本提高检索准确率，也能保留原始内容用于展示和引用。

## 如何选择增强方式

很多人第一次接触这两个能力时，会问：

- 结构路径感知增强和分块后增强有什么区别？
- 日常使用时，是不是只开 `structural_enhance=True` 就够了？

这里给一个直接可用的判断方式。

### 结构路径感知增强 vs 分块后增强

`structural_enhance=True` 是库内置好的、规则化的分块后增强。

它会自动基于 Markdown 结构生成：

- 文档上下文
- 标题路径
- 当前分块正文

并把这些内容写入 `chunk.embedding_content`。

`chunk_enhance=True` + `chunk_enhance_func=...` 则是更通用的扩展点。

你可以自己决定增强逻辑，例如：

- 追加全局摘要
- 追加相邻 chunk 的语义提示
- 让 LLM 生成小节摘要
- 追加业务标签、来源说明、FAQ 提示词

简化理解：

- `structural_enhance` 解决的是“这个 chunk 在文档结构里属于哪”
- `chunk_enhance_func` 解决的是“除了结构位置，我还想补什么语义信息”

对比：

| 维度       | 结构路径感知增强                  | 分块后增强                |
| -------- | ------------------------- | -------------------- |
| 触发方式     | `structural_enhance=True` | `chunk_enhance=True` |
| 增强来源     | 标题层级、文档结构                 | 任意自定义逻辑              |
| 是否依赖 LLM | 不需要                       | 可选                   |
| 灵活性      | 中等                        | 很高                   |
| 适用场景     | 标题清晰的 Markdown 文档         | 需要额外语义补全的场景          |

### 日常使用建议

大多数日常场景，只开启 `structural_enhance=True` 就够了。

它已经能把下面三类信息带进 `embedding_content`：

- 文档级上下文
- 当前 chunk 的标题路径
- 当前 chunk 的原始正文

这对知识库文档、技术文档、产品说明、图文混排 Markdown 往往已经足够有效。

推荐的日常用法：

```python
chunks = chunker.chunk_file(
    path,
    TextBoundaryOptions(
        min_chars=600,
        target_chars=1400,
        max_chars=1800,
    ),
    structural_enhance=True,
)

for chunk in chunks:
    text_for_embedding = chunk.embedding_content or chunk.content
```

什么时候再考虑 `chunk_enhance_func`：

- 标题层级不明显
- 同一章节内部语义跨度很大
- 想给每个 chunk 增加小节摘要
- 想追加业务标签、来源说明、问答提示
- 想引入 LLM 做更强的 chunk 级语义补全

一个稳妥的策略是：

1. 先默认启用 `structural_enhance=True`
2. 观察检索效果
3. 只有在结构信息不够时，再叠加 `chunk_enhance_func`

## 分块规则

分块器会先把输入文本扫描成结构块。

| 结构  | 规则                                            |
| --- | --------------------------------------------- |
| 标题  | `#` 到 `######` 开头的 Markdown 标题行。              |
| 代码块 | 使用三反引号包裹的代码围栏。未闭合代码块会保留到文档末尾。                 |
| 图片  | 整行 Markdown 图片，如 `![架构图](assets/a.png)`。      |
| 链接  | 整行 Markdown 链接，如 `[文档](https://example.com)`。 |
| 段落  | 非空普通文本段落，空行作为段落边界。                            |

打包时只在结构块边界切分，尽量避免把图片、代码块或段落切碎。

## 运行测试

在项目根目录执行：

```powershell
cd StructureAware_Chunker
$env:PYTHONPATH = ".\python"
.\.venv\Scripts\python.exe -m unittest discover -s .\python\tests
```

或在 `python` 目录执行：

```powershell
cd StructureAware_Chunker\python
..\.venv\Scripts\python.exe -m unittest discover -s .\tests
```

## 常见问题

### 为什么 chunk 长度可能超过 max_chars？

当当前 chunk 小于 `min_chars` 时，分块器会允许合并下一个结构块，即使结果超过 `max_chars`。这样可以避免生成过短、语义不完整的小块。

### overlap 会破坏结构块吗？

`overlap_chars` 会把上一个 chunk 的尾部字符复制到下一个 chunk 前面。它不会改变原始切分边界，但复制出来的重叠片段可能从结构块中间开始。

### 为什么图片没有被拆开？

整行 Markdown 图片会被识别为原子块。只要图片单独占一行，就会尽量作为整体进入同一个 chunk。

### 这个目录可以直接 pip install 吗？

当前 `python/` 目录没有 `pyproject.toml` 或 `setup.py`。它更适合作为仓库内模块使用，通过 `PYTHONPATH=.\python` 或从 `python/` 目录运行。
