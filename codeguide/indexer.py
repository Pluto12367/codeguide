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
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import RepoProfile

INDEX_DIR = ".codeguide"
INDEX_FILE = "index.json"
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
    summaries = summaries or {}
    chunks: list[Chunk] = []
    for f in profile.files:
        if len(chunks) >= max_chunks:
            break
        src = sources.get(f.path, b"")
        header_parts = [f.path]
        if f.module_name:
            header_parts.append(f.module_name)
        if f.doc:
            header_parts.append(f.doc)
        if f.path in summaries:
            header_parts.append(summaries[f.path])
        chunks.append(Chunk(f.path, Path(f.path).name, "file", 1, " ".join(header_parts)))

        for s, display in _qualified_symbols(f.symbols):
            if len(chunks) >= max_chunks:
                break
            end = s.line + SYMBOL_SNIPPET_LINES  # 兜底：无后续符号时也截断
            text = (
                f"{f.path} {s.kind} {display} {s.doc or ''}\n"
                + _snippet(src, s.line, SYMBOL_SNIPPET_LINES)
            )
            chunks.append(Chunk(f.path, display, s.kind, s.line, text))
    return chunks


def repo_hash(profile: RepoProfile, sources: dict[str, bytes], embedder_id: str = "") -> str:
    h = hashlib.sha1()
    h.update(embedder_id.encode("utf-8"))
    for path in sorted(sources):
        h.update(path.encode("utf-8"))
        h.update(hashlib.sha1(sources[path]).digest())
    return h.hexdigest()


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
    chunks: list[Chunk]
    vectors: list[list[float]] | None = None  # 与 chunks 对齐；None = 未启用嵌入
    repo_hash: str = ""
    embedder_id: str = ""

    def save(self, root: Path) -> Path:
        out = root / INDEX_DIR / INDEX_FILE
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "hash": self.repo_hash,
                    "embedder": self.embedder_id,
                    "chunks": [c.to_dict() for c in self.chunks],
                    "vectors": self.vectors,
                },
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
        return cls(
            chunks=[Chunk(**c) for c in data.get("chunks", [])],
            vectors=data.get("vectors"),
            repo_hash=data.get("hash", ""),
            embedder_id=data.get("embedder", ""),
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
    """加载或构建索引，返回 (index, rebuilt)。"""
    sources: dict[str, bytes] = {}
    for f in profile.files:
        try:
            sources[f.path] = (Path(profile.root) / f.path).read_bytes()
        except OSError:
            sources[f.path] = b""

    embedder_id = getattr(embedder, "model_name", "") if embedder else ""
    current_hash = repo_hash(profile, sources, embedder_id)
    cached = RepoIndex.load(root)
    if cached and cached.repo_hash == current_hash:
        return cached, False

    chunks = build_chunks(profile, sources, summaries)
    vectors = None
    if embedder and chunks:
        vectors = _embed_texts(
            embedder, [c.text for c in chunks], progress
        )
    index = RepoIndex(
        chunks=chunks, vectors=vectors, repo_hash=current_hash, embedder_id=embedder_id
    )
    index.save(root)
    return index, True


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
