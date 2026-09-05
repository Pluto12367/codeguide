"""风险热区：git 变更频次（churn）× PageRank。

改动最频繁 × 依赖最核心的文件最值得新人警惕、也最值得优先补测试。
churn 来自 `git log --name-only` 计数；非 git 仓库返回 None 并优雅降级。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .models import RepoProfile
from .roadmap import _pagerank


def git_churn(root: Path, since: str = "1 year ago") -> dict[str, int] | None:
    """统计 since 以来每个文件的被改次数；非 git 仓库或 git 不可用返回 None。"""
    cmd = [
        "git", "-C", str(root), "log", f"--since={since}",
        "--name-only", "--pretty=format:",
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None

    churn: dict[str, int] = {}
    for line in out.stdout.splitlines():
        path = line.strip()
        if path:
            churn[path] = churn.get(path, 0) + 1
    return churn


def risk_map(profile: RepoProfile, churn: dict[str, int]) -> list[dict]:
    """融合变更频次与 PageRank，返回按风险降序的文件列表。

    risk = churn 归一化 × pagerank 归一化（乘法惩罚只在两维同时高时给高分）。
    """
    if not churn or not profile.graph_nodes:
        return []

    graph = _build_graph(profile)
    pagerank = _pagerank(graph)

    known = [p for p in churn if p in pagerank]
    if not known:
        return []
    max_churn = max(churn[p] for p in known)
    max_pr = max(pagerank[p] for p in known) or 1.0

    rows = [
        {
            "path": p,
            "commits": churn[p],
            "pagerank": pagerank[p],
            "risk": (churn[p] / max_churn) * (pagerank[p] / max_pr),
        }
        for p in known
    ]
    rows.sort(key=lambda r: (-r["risk"], r["path"]))
    return rows


def _build_graph(profile: RepoProfile):
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_nodes_from(profile.graph_nodes)
    for src, dst, w in profile.graph_edges:
        graph.add_edge(src, dst, weight=w)
    return graph


def repo_risks(profile: RepoProfile, since: str = "1 year ago") -> dict | None:
    """一站式：churn + risk_map。非 git 仓库返回 None。"""
    churn = git_churn(Path(profile.root), since=since)
    if churn is None:
        return None
    return {"churn": churn, "rows": risk_map(profile, churn)}
