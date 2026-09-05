"""本地索引与检索：代码分块 + BM25（零依赖）+ 可选 API 语义嵌入。

索引落盘在目标仓库的 .codeguide/index.json，以全仓库内容哈希判断
是否需要重建。未配置嵌入模型时自动使用 BM25 词法检索。
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
MAX_CHUNKS = 3000
SYMBOL_SNIPPET_LINES = 40
EMBED_BATCH = 64

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
        if f.path in summaries:
            header_parts.append(summaries[f.path])
        chunks.append(Chunk(f.path, Path(f.path).name, "file", 1, " ".join(header_parts)))

        ordered = sorted(f.symbols, key=lambda s: s.line)
        for i, s in enumerate(ordered):
            if len(chunks) >= max_chunks:
                break
            end = ordered[i + 1].line - 1 if i + 1 < len(ordered) else None
            span = (
                min(end - s.line + 1, SYMBOL_SNIPPET_LINES)
                if end
                else SYMBOL_SNIPPET_LINES
            )
            text = (
                f"{f.path} {s.kind} {s.name} {s.doc or ''}\n"
                + _snippet(src, s.line, max(span, 1))
            )
            chunks.append(Chunk(f.path, s.name, s.kind, s.line, text))
    return chunks


def repo_hash(profile: RepoProfile, sources: dict[str, bytes]) -> str:
    h = hashlib.sha1()
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


@dataclass
class RepoIndex:
    chunks: list[Chunk]
    vectors: list[list[float]] | None = None  # 与 chunks 对齐；None = 未启用嵌入
    repo_hash: str = ""

    def save(self, root: Path) -> Path:
        out = root / INDEX_DIR / INDEX_FILE
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "hash": self.repo_hash,
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
        )


def _embed_texts(client, texts: list[str], progress=None) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        if progress:
            progress(f"嵌入 {i + 1}-{i + len(batch)}/{len(texts)}")
        vectors.extend(client.embed(batch))
    return vectors


def build_index(
    profile: RepoProfile,
    root: Path,
    client=None,  # LLMClient；提供且配置了嵌入模型时启用语义索引
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

    current_hash = repo_hash(profile, sources)
    cached = RepoIndex.load(root)
    if cached and cached.repo_hash == current_hash:
        return cached, False

    chunks = build_chunks(profile, sources, summaries)
    vectors = None
    embed_model = getattr(client, "embed_model", "") if client else ""
    if embed_model and chunks:
        vectors = _embed_texts(
            client, [c.text[:2000] for c in chunks], progress
        )
    index = RepoIndex(chunks=chunks, vectors=vectors, repo_hash=current_hash)
    index.save(root)
    return index, True


def retrieve(
    index: RepoIndex, question: str, top_k: int = 6
) -> list[tuple[Chunk, float]]:
    """按索引类型自动选择语义（嵌入）或词法（BM25）检索。"""
    if index.vectors and len(index.vectors) == len(index.chunks):
        raise NotImplementedError("需要查询向量，请走 retrieve_semantic")
    bm25 = BM25([tokenize(c.text) for c in index.chunks])
    hits = bm25.search(tokenize(question), top_k)
    return [(index.chunks[i], s) for i, s in hits]


def retrieve_semantic(
    index: RepoIndex, question: str, client, top_k: int = 6
) -> list[tuple[Chunk, float]]:
    qvec = client.embed([question])[0]
    scored = [
        (chunk, cosine(qvec, vec))
        for chunk, vec in zip(index.chunks, index.vectors or [])
    ]
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda kv: -kv[1])
    return scored[:top_k]
