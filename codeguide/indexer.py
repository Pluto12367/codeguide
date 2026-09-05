"""本地索引与检索：代码分块 + BM25 / 语义 / RRF 混合检索。

索引落盘在目标仓库的 .codeguide/index.json，以「全仓库内容哈希 + 嵌入模型
标识」判断是否需要重建。未提供 embedder 时自动使用 BM25 词法检索。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import RepoProfile

INDEX_DIR = ".codeguide"
INDEX_FILE = "index.json"
INDEX_VERSION = 2
MAX_CHUNKS = 3000
SYMBOL_SNIPPET_LINES = 40
EMBED_BATCH = 64
RRF_K = 60

_WORD = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """代码友好分词：拆 snake_case / camelCase / 缩写词，CJK 按单字切。"""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", text)
    tokens: list[str] = []
    for word in _WORD.findall(text.lower()):
        if re.match(r"[\u4e00-\u9fff]", word):
            tokens.extend(word)  # 无分词器时按字切分，保证中文查询能命中
        else:
            tokens.extend(part for part in word.split("_") if part)
    return tokens


@dataclass
class Chunk:
    path: str
    name: str
    kind: str  # "file" | "class" | "function" | "method"
    line: int
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(source: bytes, start_line: int, max_lines: int) -> str:
    lines = source.decode("utf-8", errors="replace").splitlines()
    start = max(0, start_line - 1)
    return "\n".join(lines[start : start + max_lines])


def _qualified_symbols(symbols: list):
    """给方法补上所属类名（Engine.start），并保持行序。"""
    ordered = sorted(symbols, key=lambda s: s.line)
    current_class: str | None = None
    for s in ordered:
        if s.kind == "class":
            current_class = s.name
        elif s.kind == "function":
            current_class = None  # 模块级函数意味着类作用域已结束
        display = (
            f"{current_class}.{s.name}"
            if (s.kind == "method" and current_class)
            else s.name
        )
        yield s, display


def build_chunks(
    profile: RepoProfile,
    sources: dict[str, bytes],
    summaries: dict[str, str] | None = None,
    max_chunks: int = MAX_CHUNKS,
) -> list[Chunk]:
    """把仓库画像切成检索单元：每个文件一条概要块 + 每个符号一条代码块。"""
    chunks: list[Chunk] = []
    for f in profile.files:
        if len(chunks) >= max_chunks:
            break
        chunks.extend(_chunks_for_file(f, sources.get(f.path, b""), summaries, max_chunks - len(chunks)))
    return chunks


def _chunks_for_file(
    f, src: bytes, summaries: dict[str, str] | None, budget: int = MAX_CHUNKS
) -> list[Chunk]:
    """单个文件的分块：文件概要块 + 每个符号一条代码块。"""
    summaries = summaries or {}
    chunks: list[Chunk] = []
    header_parts = [f.path]
    if f.module_name:
        header_parts.append(f.module_name)
    if f.doc:
        header_parts.append(f.doc)
    if f.path in summaries:
        header_parts.append(summaries[f.path])
    chunks.append(Chunk(f.path, Path(f.path).name, "file", 1, " ".join(header_parts)))

    for s, display in _qualified_symbols(f.symbols):
        if len(chunks) >= budget:
            break
        text = (
            f"{f.path} {s.kind} {display} {s.doc or ''}\n"
            + _snippet(src, s.line, SYMBOL_SNIPPET_LINES)
        )
        chunks.append(Chunk(f.path, display, s.kind, s.line, text))
    return chunks


def file_hash(source: bytes) -> str:
    return hashlib.sha1(source).hexdigest()


class BM25:
    """Okapi BM25，纯 Python 实现。"""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(corpus)
        self.doc_len = [len(d) for d in corpus]
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0
        self.tf = [Counter(d) for d in corpus]
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        self.idf = {
            t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()
        }

    def score(self, query: list[str], index: int) -> float:
        score = 0.0
        tf = self.tf[index]
        dl = self.doc_len[index] or 1
        for term in query:
            if term not in tf:
                continue
            idf = self.idf.get(term, 0.0)
            freq = tf[term]
            score += idf * freq * (self.k1 + 1) / (
                freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            )
        return score

    def search(self, query: list[str], top_k: int = 6) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.N)]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top_k]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：融合多路排序，score = Σ 1/(k + rank)。

    输入每路的候选索引列表（按该路分数降序），输出融合后的
    [(索引, rrf分数)] 降序列表。对异构分数量纲天然免疫。
    """
    scores: dict[int, float] = {}
    for indices in rankings:
        for rank, idx in enumerate(indices, 1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


@dataclass
class RepoIndex:
    """文件级增量的仓库索引（格式 v2）。

    file_hashes 记录每个文件的内容哈希；内容未变的文件直接复用
    分块与向量，只有变化的文件重新分块/嵌入。
    """

    chunks: list[Chunk]
    vectors: list[list[float]] | None = None  # 与 chunks 对齐；None = 未启用嵌入
    embedder_id: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)

    def save(self, root: Path) -> Path:
        out = root / INDEX_DIR / INDEX_FILE
        out.parent.mkdir(parents=True, exist_ok=True)
        # 按文件重组（chunks 依文件顺序排列，便于切片）
        files: dict[str, dict] = {}
        for i, chunk in enumerate(self.chunks):
            entry = files.setdefault(chunk.path, {"hash": self.file_hashes.get(chunk.path, ""), "chunks": [], "vectors": []})
            entry["chunks"].append(chunk.to_dict())
            if self.vectors is not None:
                entry["vectors"].append(self.vectors[i])
        for entry in files.values():
            if self.vectors is None:
                entry["vectors"] = None
        out.write_text(
            json.dumps(
                {"version": INDEX_VERSION, "embedder": self.embedder_id, "files": files},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return out

    @classmethod
    def load(cls, root: Path) -> "RepoIndex | None":
        path = root / INDEX_DIR / INDEX_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("version") != INDEX_VERSION:
            return None  # 旧格式：整体重建
        chunks: list[Chunk] = []
        vectors: list[list[float]] = []
        hashes: dict[str, str] = {}
        for fpath, entry in data.get("files", {}).items():
            hashes[fpath] = entry.get("hash", "")
            for c in entry.get("chunks", []):
                chunks.append(Chunk(**c))
            if entry.get("vectors") is not None:
                vectors.extend(entry["vectors"])
        return cls(
            chunks=chunks,
            vectors=vectors if vectors else None,
            embedder_id=data.get("embedder", ""),
            file_hashes=hashes,
        )


def _embed_texts(embedder, texts: list[str], progress=None) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        if progress:
            progress(f"嵌入 {i + 1}-{i + len(batch)}/{len(texts)}")
        vectors.extend(embedder.embed(batch))
    return vectors


def build_index(
    profile: RepoProfile,
    root: Path,
    embedder=None,  # 提供（ApiEmbedder/LocalEmbedder）时启用语义向量
    summaries: dict[str, str] | None = None,
    progress=None,
) -> tuple[RepoIndex, bool]:
    """加载或增量构建索引，返回 (index, 是否有任何重建)。

    内容未变的文件复用缓存的分块与向量；只有变化的文件重新处理。
    """
    sources: dict[str, bytes] = {}
    for f in profile.files:
        try:
            sources[f.path] = (Path(profile.root) / f.path).read_bytes()
        except OSError:
            sources[f.path] = b""

    embedder_id = getattr(embedder, "model_name", "") if embedder else ""
    cached = RepoIndex.load(root)
    cache_ok = cached is not None and cached.embedder_id == embedder_id

    # 逐文件决定复用或重建
    reused: dict[str, tuple[list[Chunk], list[list[float]] | None]] = {}
    todo: list = []  # (FileInfo, source)
    for f in profile.files:
        h = file_hash(sources[f.path])
        if cache_ok and cached.file_hashes.get(f.path) == h:
            file_chunks = [c for c in cached.chunks if c.path == f.path]
            file_vectors = None
            if cached.vectors is not None:
                # 向量与 cached.chunks 对齐，按块归属切片
                offsets = [i for i, c in enumerate(cached.chunks) if c.path == f.path]
                file_vectors = [cached.vectors[i] for i in offsets]
            reused[f.path] = (file_chunks, file_vectors)
        else:
            todo.append((f, h))

    rebuilt = bool(todo) or not cache_ok
    if todo:
        if progress:
            progress(f"增量索引：复用 {len(reused)} 个文件，重建 {len(todo)} 个")
        new_chunks: dict[str, list[Chunk]] = {}
        for f, _h in todo:
            new_chunks[f.path] = _chunks_for_file(
                f, sources[f.path], summaries, MAX_CHUNKS
            )
        new_vectors: dict[str, list[list[float]] | None] = {
            f.path: None for f, _ in todo
        }
        if embedder:
            flat_texts = [
                c.text[:2000] for f, _ in todo for c in new_chunks[f.path]
            ]
            flat_vecs = _embed_texts(embedder, flat_texts, progress)
            pos = 0
            for f, _ in todo:
                n = len(new_chunks[f.path])
                new_vectors[f.path] = flat_vecs[pos : pos + n]
                pos += n

        for f, h in todo:
            reused[f.path] = (new_chunks[f.path], new_vectors[f.path])

    # 组装扁平索引（保持文件顺序）
    chunks: list[Chunk] = []
    vectors: list[list[float]] | None = None if embedder is None else []
    hashes: dict[str, str] = {}
    for f in profile.files:
        file_chunks, file_vectors = reused[f.path]
        hashes[f.path] = file_hash(sources[f.path])
        chunks.extend(file_chunks)
        if vectors is not None:
            vectors.extend(file_vectors or [])

    index = RepoIndex(
        chunks=chunks,
        vectors=vectors if vectors else None,
        embedder_id=embedder_id,
        file_hashes=hashes,
    )
    index.save(root)
    return index, rebuilt


# ---------- 检索 ----------


def _bm25_ranking(index: RepoIndex, question: str, top_k: int) -> list[tuple[int, float]]:
    bm25 = BM25([tokenize(c.text) for c in index.chunks])
    return bm25.search(tokenize(question), top_k)


def _semantic_ranking(
    index: RepoIndex, question: str, embedder, top_k: int
) -> list[tuple[int, float]]:
    qvec = embedder.embed([question])[0]
    scored = [
        (i, cosine(qvec, vec))
        for i, vec in enumerate(index.vectors or [])
    ]
    scored = [(i, s) for i, s in scored if s > 0]
    scored.sort(key=lambda kv: -kv[1])
    return scored[:top_k]


def _to_chunks(index: RepoIndex, ranking: list[tuple[int, float]]) -> list[tuple["Chunk", float]]:
    return [(index.chunks[i], s) for i, s in ranking]


def retrieve(index: RepoIndex, question: str, top_k: int = 6) -> list[tuple[Chunk, float]]:
    """BM25 词法检索（兼容旧接口）。"""
    return _to_chunks(index, _bm25_ranking(index, question, top_k))


def retrieve_semantic(
    index: RepoIndex, question: str, embedder, top_k: int = 6
) -> list[tuple[Chunk, float]]:
    """纯语义检索，需要索引含向量。"""
    return _to_chunks(index, _semantic_ranking(index, question, embedder, top_k))


def retrieve_hybrid(
    index: RepoIndex,
    question: str,
    embedder,
    top_k: int = 6,
    candidates: int = 20,
) -> list[tuple[Chunk, float]]:
    """RRF 混合检索：BM25 与向量两路各取候选，按倒数排名融合。"""
    bm = [i for i, _ in _bm25_ranking(index, question, candidates)]
    sem = [i for i, _ in _semantic_ranking(index, question, embedder, candidates)]
    fused = rrf_fuse([bm, sem])[:top_k]
    return [(index.chunks[i], s) for i, s in fused]


def retrieve_auto(
    index: RepoIndex,
    question: str,
    embedder=None,
    mode: str = "auto",
    top_k: int = 6,
) -> tuple[list[tuple[Chunk, float]], str]:
    """按 mode 调度检索，返回 (hits, 实际使用的模式)。

    mode: "bm25" | "semantic" | "hybrid" | "auto"。
    auto = 有向量则 hybrid，否则 bm25；请求 semantic/hybrid 但向量
    不可用时优雅降级并如实报告。
    """
    has_vectors = bool(index.vectors) and len(index.vectors) == len(index.chunks)
    can_semantic = has_vectors and embedder is not None

    if mode == "bm25" or (mode == "auto" and not can_semantic):
        return retrieve(index, question, top_k), "词法"
    if mode == "semantic":
        if not can_semantic:
            return retrieve(index, question, top_k), "词法"
        return retrieve_semantic(index, question, embedder, top_k), "语义"
    if mode == "hybrid":
        if not can_semantic:
            return retrieve(index, question, top_k), "词法"
        return retrieve_hybrid(index, question, embedder, top_k), "混合"
    # auto + can_semantic
    return retrieve_hybrid(index, question, embedder, top_k), "混合"
