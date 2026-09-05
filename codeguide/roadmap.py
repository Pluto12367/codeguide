"""基于 PageRank 的阅读路线生成。

思路：入口文件（无人导入、但导入了别人）是"起步"，PageRank 最高的
枢纽文件是"核心"，其余高影响力文件是"支撑"。比单纯入度排序更能
反映全局重要性。
"""

from __future__ import annotations

import networkx as nx

from .models import RepoProfile

PHASE_ENTRY = "起步"
PHASE_CORE = "核心"
PHASE_SUPPORT = "支撑"


def _pagerank(
    graph: nx.DiGraph, damping: float = 0.85, max_iter: int = 100, tol: float = 1e-9
) -> dict[str, float]:
    """幂迭代 PageRank（按边权）。不依赖 numpy，保持工具轻量。"""
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    pr = {u: 1.0 / n for u in nodes}
    out_weight = {
        u: sum(d.get("weight", 1) for *_, d in graph.out_edges(u, data=True))
        for u in nodes
    }
    edges = [(u, v, d.get("weight", 1)) for u, v, d in graph.edges(data=True)]
    for _ in range(max_iter):
        # 悬空节点（无出边）的质量均摊给所有节点
        dangling = sum(pr[u] for u in nodes if out_weight[u] == 0)
        base = (1 - damping) / n + damping * dangling / n
        new = {u: base for u in nodes}
        for u, v, w in edges:
            new[v] += damping * pr[u] * w / out_weight[u]
        err = sum(abs(new[u] - pr[u]) for u in nodes)
        pr = new
        if err < tol:
            break
    return pr


def reading_route(profile: RepoProfile, max_items: int = 15) -> list[dict]:
    """返回按阅读顺序排列的文件路线。

    每项：{path, phase, reason, pagerank, in_degree, out_degree}
    """
    if not profile.graph_nodes or not profile.graph_edges:
        return []

    graph = nx.DiGraph()
    graph.add_nodes_from(profile.graph_nodes)
    for src, dst, w in profile.graph_edges:
        graph.add_edge(src, dst, weight=w)

    pagerank = _pagerank(graph)
    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())

    # 入口：没人导入它，但它导入别人 —— 执行从这里开始
    entries = sorted(
        (n for n in graph.nodes if in_deg[n] == 0 and out_deg[n] > 0),
        key=lambda n: (-out_deg[n], n),
    )
    # 核心：PageRank 降序（排除已入选的入口）
    chosen = set(entries[:4])
    core = sorted(
        (n for n in graph.nodes if n not in chosen),
        key=lambda n: (-pagerank[n], n),
    )
    core = [n for n in core if in_deg[n] > 0][:8]
    chosen.update(core)
    # 支撑：剩余文件按 PageRank 补齐
    support = sorted(
        (n for n in graph.nodes if n not in chosen),
        key=lambda n: (-pagerank[n], n),
    )[: max(0, max_items - len(entries[:4]) - len(core))]

    route: list[dict] = []
    for n in entries[:4]:
        route.append({
            "path": n,
            "phase": PHASE_ENTRY,
            "reason": f"没有其他文件导入它，却有 {out_deg[n]} 个内部依赖——"
                      f"程序的入口或独立脚本，从这里开始读",
            "pagerank": pagerank[n],
            "in_degree": in_deg[n],
            "out_degree": out_deg[n],
        })
    for n in core:
        route.append({
            "path": n,
            "phase": PHASE_CORE,
            "reason": f"被 {in_deg[n]} 个文件依赖，PageRank {pagerank[n]:.4f}，全局核心",
            "pagerank": pagerank[n],
            "in_degree": in_deg[n],
            "out_degree": out_deg[n],
        })
    for n in support:
        route.append({
            "path": n,
            "phase": PHASE_SUPPORT,
            "reason": f"较高影响力（PageRank {pagerank[n]:.4f}，被 {in_deg[n]} 个文件依赖）",
            "pagerank": pagerank[n],
            "in_degree": in_deg[n],
            "out_degree": out_deg[n],
        })
    return route
