"""本地索引、BM25 检索与 ask 问答测试（全部 mock，不联网）。"""

from pathlib import Path

from codeguide.ask import ask
from codeguide.indexer import (
    BM25,
    RepoIndex,
    build_chunks,
    build_index,
    retrieve,
    tokenize,
)
from codeguide.scanner import scan_repo
from codeguide.summarizer import FILE_SYSTEM_PROMPT, MODULE_SYSTEM_PROMPT


class FakeClient:
    """带嵌入的假 LLM：嵌入用可复现的词哈希向量。"""

    embed_model = "fake-embed"

    def embed(self, texts):
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text):
        v = [0.0] * 16
        for tok in tokenize(text):
            v[hash(tok) % 16] += 1.0
        return v


class FakeChatClient(FakeClient):
    def chat(self, system, user, max_tokens=1024):
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


def test_bm25_ranking():
    corpus = [tokenize(t) for t in [
        "engine start boot",
        "http request send",
        "database migrate schema",
    ]]
    bm25 = BM25(corpus)
    hits = bm25.search(tokenize("engine start"), top_k=2)
    assert hits[0][0] == 0
    assert len(hits) == 1 or hits[1][1] < hits[0][1]


def test_build_chunks(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    sources = {f.path: (root / f.path).read_bytes() for f in profile.files}
    chunks = build_chunks(profile, sources)

    engine = [c for c in chunks if c.name == "Engine"]
    assert engine and engine[0].kind == "class" and engine[0].path.endswith("core.py")
    assert "引擎，负责启动" in engine[0].text  # docstring 进入索引
    start = [c for c in chunks if c.name == "start" and c.kind == "method"]
    assert start and "boot" in start[0].text  # 源码片段进入符号所在块
    assert any(c.kind == "file" for c in chunks)


def test_index_persistence_and_rebuild(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)

    index1, rebuilt1 = build_index(profile, root, client=FakeClient())
    assert rebuilt1 and index1.vectors is not None

    # 内容没变：命中缓存，不重建
    index2, rebuilt2 = build_index(profile, root, client=FakeClient())
    assert not rebuilt2 and index2.repo_hash == index1.repo_hash

    # 内容变了：重建
    (root / "pkg" / "core.py").write_text("x = 2\n", encoding="utf-8")
    profile = scan_repo(root)
    _, rebuilt3 = build_index(profile, root, client=FakeClient())
    assert rebuilt3

    # 索引文件落盘
    assert (root / ".codeguide" / "index.json").exists()


def test_retrieve_lexical(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    index, _ = build_index(profile, root)  # 无 client → 纯 BM25
    assert index.vectors is None

    hits = retrieve(index, "engine start boot", top_k=3)
    assert hits
    assert hits[0][0].path.endswith("core.py")


def test_ask_with_llm(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    result = ask(profile, "引擎怎么启动？", client=FakeChatClient())

    assert result["answer"] and "pkg/core.py" in result["answer"]
    assert result["mode"] == "语义"  # FakeClient 配置了嵌入
    assert any(h["path"].endswith("core.py") for h in result["hits"])


def test_ask_without_llm_falls_back_to_locations(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    result = ask(profile, "engine start")

    assert result["answer"] is None
    assert result["mode"] == "词法"
    assert result["hits"] and result["hits"][0]["path"].endswith("core.py")
