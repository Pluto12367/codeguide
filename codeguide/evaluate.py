"""检索质量评测：黄金问答集 → Recall@1/3/5 与 MRR。

纯检索评测，不调用 LLM 生成，因此无 API Key 也能跑（语义模式除外）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .indexer import build_index, retrieve_auto
from .models import RepoProfile

METRIC_KS = (1, 3, 5)


def load_golden(path: Path) -> list[dict]:
    """读取黄金问答集 JSON（兼容 {cases: []} 包装与裸列表）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    required = {"question", "expected_files"}
    for i, c in enumerate(cases):
        if not required <= set(c):
            raise ValueError(f"第 {i} 条缺少必需字段 {required - set(c)}")
    return cases


def first_relevant_rank(hits: list[dict], expected_files: set[str]) -> int | None:
    """首个命中预期文件的检索结果排名（1-based），未命中返回 None。"""
    for rank, h in enumerate(hits, 1):
        if h["path"] in expected_files:
            return rank
    return None


def evaluate_retrieval(
    profile: RepoProfile,
    cases: list[dict],
    embedder=None,
    mode: str = "auto",
    top_k: int = 8,
    progress=None,
) -> dict:
    """对黄金集逐题检索并计算指标。

    返回 {"metrics": {...}, "rows": [{question, rank, hit, top1, expected}]}。
    """
    index, rebuilt = build_index(
        profile, Path(profile.root), embedder=embedder, progress=progress
    )

    rows: list[dict] = []
    for i, case in enumerate(cases, 1):
        if progress:
            progress(f"评测 {i}/{len(cases)}: {case['question'][:30]}")
        hits, used_mode = retrieve_auto(
            index, case["question"], embedder, mode, top_k
        )
        hit_dicts = [
            {
                "path": c.path,
                "name": c.name,
                "kind": c.kind,
                "line": c.line,
                "score": round(s, 4),
            }
            for c, s in hits
        ]
        expected = set(case["expected_files"])
        rank = first_relevant_rank(hit_dicts, expected)
        rows.append({
            "question": case["question"],
            "rank": rank,
            "hit": rank is not None,
            "top1": hit_dicts[0]["path"] if hit_dicts else None,
            "expected": sorted(expected),
            "mode": used_mode,
        })

    n = len(rows)
    if n == 0:
        return {"metrics": {}, "rows": []}

    def recall_at(k: int) -> float:
        return sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k) / n

    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    return {
        "metrics": {
            "questions": n,
            **{f"recall@{k}": round(recall_at(k), 4) for k in METRIC_KS},
            "mrr": round(mrr, 4),
        },
        "rows": rows,
    }
