"""检索评测（evaluate.py）测试：mock 嵌入，不联网。"""

import json
from pathlib import Path

from codeguide.evaluate import (
    evaluate_retrieval,
    first_relevant_rank,
    load_golden,
)
from codeguide.scanner import scan_repo
from tests.test_ask import FakeEmbedder, _make_repo


def test_first_relevant_rank():
    hits = [
        {"path": "a.py"},
        {"path": "b.py"},
        {"path": "c.py"},
    ]
    assert first_relevant_rank(hits, {"c.py"}) == 3
    assert first_relevant_rank(hits, {"a.py"}) == 1
    assert first_relevant_rank(hits, {"missing.py"}) is None


def test_load_golden_wrapped(tmp_path: Path):
    p = tmp_path / "g.json"
    p.write_text(
        json.dumps({"cases": [{"question": "q", "expected_files": ["a.py"]}]}),
        encoding="utf-8",
    )
    cases = load_golden(p)
    assert len(cases) == 1 and cases[0]["question"] == "q"


def test_load_golden_rejects_missing_fields(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"question": "q"}]), encoding="utf-8")
    try:
        load_golden(p)
        raise AssertionError("应当抛出 ValueError")
    except ValueError:
        pass


def test_evaluate_metrics(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    cases = [
        {"question": "engine start boot", "expected_files": ["pkg/core.py"]},
        {"question": "引擎 启动", "expected_files": ["pkg/core.py"]},
        {"question": "完全无关的问题 xyzzy", "expected_files": ["pkg/app.py"]},
    ]
    result = evaluate_retrieval(profile, cases, embedder=FakeEmbedder(), mode="hybrid")

    m = result["metrics"]
    assert m["questions"] == 3
    assert 0.0 <= m["recall@1"] <= 1.0 and 0.0 <= m["mrr"] <= 1.0
    # 前两题一定命中 core.py（内容直接相关）
    assert result["rows"][0]["hit"] and result["rows"][1]["hit"]
    assert result["rows"][0]["rank"] is not None

    # JSON 可序列化（供 --json 输出）
    json.dumps(result, ensure_ascii=False)


def test_evaluate_lexical_mode(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    cases = [{"question": "engine start boot", "expected_files": ["pkg/core.py"]}]
    result = evaluate_retrieval(profile, cases, embedder=None, mode="bm25")
    assert result["rows"][0]["hit"]
    assert result["rows"][0]["mode"] == "词法"
