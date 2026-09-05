"""本地索引、检索与 ask 问答测试（全部 mock，不联网）。"""

import hashlib
from pathlib import Path

from codeguide.ask import ask
from codeguide.indexer import (
    Chunk,
    build_chunks,
    build_index,
    rrf_fuse,
    retrieve,
    retrieve_auto,
    tokenize,
)
from codeguide.scanner import scan_repo


def _vec(text: str, dim: int = 16) -> list[float]:
    v = [0.0] * dim
    for tok in tokenize(text):
        v[int(hashlib.sha1(tok.encode()).hexdigest(), 16) % dim] += 1.0
    return v


class FakeEmbedder:
    """可复现的词哈希嵌入，接口与真实 embedder 一致。"""

    model_name = "fake:test-embed"

    def embed(self, texts):
        return [_vec(t) for t in texts]


class FakeChatClient:
    def chat(self, system: str, user: str, max_tokens: int = 1024) -> str:
        return "根据上下文，答案在 `pkg/core.py`。"


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        '"""核心引擎模块。"""\n'
        "class Engine:\n"
        '    """引擎，负责启动。"""\n'
        "    def start(self):\n"
        "        print('boot')\n",
        encoding="utf-8",
    )
    (root / "pkg" / "app.py").write_text(
        "from pkg.core import Engine\n\nengine = Engine()\nengine.start()\n",
        encoding="utf-8",
    )
    return root


def test_tokenize_splits_identifiers():
    toks = tokenize("parseHTTPResponse user_name 中文问题")
    assert "http" in toks and "response" in toks  # 缩写 + camelCase 拆分
    assert "user" in toks and "name" in toks  # snake_case 拆分
    assert "中" in toks and "问" in toks  # CJK 按字切分


def test_rrf_fuse():
    # 两路排名：第一名得 1/61，两路都排前面的索引融合分最高
    fused = rrf_fuse([[0, 1, 2], [1, 3, 0]])
    scores = dict(fused)
    assert fused[0][0] == 1  # 两路都靠前的 1 应排第一
    assert scores[1] > scores[0] > 0
    assert scores[3] == 1 / (60 + 2)  # 只在第二路出现，rank=2


def test_build_chunks_qualified_names(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    sources = {f.path: (root / f.path).read_bytes() for f in profile.files}
    chunks = build_chunks(profile, sources)

    engine = [c for c in chunks if c.name == "Engine"]
    assert engine and engine[0].kind == "class" and engine[0].path.endswith("core.py")
    assert "引擎，负责启动" in engine[0].text  # docstring 进入索引

    start = [c for c in chunks if c.name == "Engine.start"]  # 类名前缀
    assert start and start[0].kind == "method"
    assert "Engine.start" in start[0].text
    assert "boot" in start[0].text

    header = [c for c in chunks if c.kind == "file" and c.path.endswith("core.py")]
    assert header and "核心引擎模块" in header[0].text  # 模块 docstring 进入文件头


def test_index_persistence_and_rebuild(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)

    index1, rebuilt1 = build_index(profile, root, embedder=FakeEmbedder())
    assert rebuilt1 and index1.vectors is not None
    assert index1.embedder_id == "fake:test-embed"

    # 内容与嵌入模型都没变：命中缓存，不重建
    index2, rebuilt2 = build_index(profile, root, embedder=FakeEmbedder())
    assert not rebuilt2 and index2.repo_hash == index1.repo_hash

    # 换嵌入模型：必须重建（向量不可混用）
    class OtherEmbedder(FakeEmbedder):
        model_name = "fake:other"

    _, rebuilt3 = build_index(profile, root, embedder=OtherEmbedder())
    assert rebuilt3

    # 内容变了：重建
    (root / "pkg" / "core.py").write_text("x = 2\n", encoding="utf-8")
    profile = scan_repo(root)
    _, rebuilt4 = build_index(profile, root, embedder=FakeEmbedder())
    assert rebuilt4

    assert (root / ".codeguide" / "index.json").exists()


def test_retrieve_lexical(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    index, _ = build_index(profile, root)  # 无 embedder → 纯 BM25
    assert index.vectors is None

    hits = retrieve(index, "engine start boot", top_k=3)
    assert hits
    assert hits[0][0].path.endswith("core.py")


def test_retrieve_auto_modes(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    embedder = FakeEmbedder()
    index, _ = build_index(profile, root, embedder=embedder)

    # auto + 有向量 → 混合
    hits, used = retrieve_auto(index, "引擎怎么启动", embedder, "auto")
    assert used == "混合" and hits

    # 指定 bm25 → 词法
    hits, used = retrieve_auto(index, "engine start boot", embedder, "bm25")
    assert used == "词法"

    # semantic 请求但无 embedder → 优雅降级为词法
    hits, used = retrieve_auto(index, "engine start boot", None, "semantic")
    assert used == "词法" and hits

    # 纯词法索引上请求 hybrid → 降级
    lex_index, _ = build_index(profile, root)
    hits, used = retrieve_auto(lex_index, "engine start boot", FakeEmbedder(), "hybrid")
    assert used == "词法"


def test_retrieve_semantic_chinese(tmp_path: Path):
    """中文查询经嵌入应命中中文 docstring 所在文件。"""
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    index, _ = build_index(profile, root, embedder=FakeEmbedder())
    from codeguide.indexer import retrieve_semantic

    hits = retrieve_semantic(index, "引擎 启动 boot", FakeEmbedder(), top_k=3)
    assert hits and hits[0][0].path.endswith("core.py")


def test_ask_with_llm(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    result = ask(
        profile, "引擎怎么启动？", client=FakeChatClient(), embedder=FakeEmbedder()
    )

    assert result["answer"] and "pkg/core.py" in result["answer"]
    assert result["mode"] == "混合"
    assert any(h["path"].endswith("core.py") for h in result["hits"])


def test_ask_without_llm_falls_back_to_locations(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    result = ask(profile, "engine start")

    assert result["answer"] is None
    assert result["mode"] == "词法"
    assert result["hits"] and result["hits"][0]["path"].endswith("core.py")


def test_chunk_dataclass_roundtrip():
    c = Chunk("a.py", "a", "file", 1, "text")
    assert Chunk(**c.to_dict()) == c
