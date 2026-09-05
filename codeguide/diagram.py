"""Mermaid 架构图生成：模块级依赖图 + 枢纽文件依赖图。"""

from __future__ import annotations

from .languages import module_group
from .models import RepoProfile


def _label(text: str) -> str:
    """转义为安全的 Mermaid 节点标签。"""
    return text.replace('"', "'").replace("\\", "/").replace("\n", " ")


def _module_edges(profile: RepoProfile) -> dict[tuple[str, str], int]:
    """把文件级依赖边聚合为模块级，返回 {(src, dst): weight}。"""
    agg: dict[tuple[str, str], int] = {}
    for src, dst, w in profile.graph_edges:
        a, b = module_group(src), module_group(dst)
        if a == b:
            continue
        agg[(a, b)] = agg.get((a, b), 0) + w
    return agg


def mermaid_module_graph(profile: RepoProfile, max_edges: int = 40) -> str:
    """模块级依赖图，边越粗（权重越大）模块耦合越强。

    单包仓库（如 src-layout 只有一个包）跨模块边会很少，此时
    降级为文件级核心依赖图，避免输出一张空图。
    """
    weighted = sorted(_module_edges(profile).items(), key=lambda kv: -kv[1])
    if len(weighted) >= 2:
        edges = weighted[:max_edges]
        nodes: list[str] = []
        for (a, b), _ in edges:
            if a not in nodes:
                nodes.append(a)
            if b not in nodes:
                nodes.append(b)

        lines = ["flowchart LR"]
        ids = {m: f"m{i}" for i, m in enumerate(nodes)}
        for m in nodes:
            lines.append(f'  {ids[m]}["{_label(m)}"]')
        for (a, b), w in edges:
            lines.append(f'  {ids[a]} -->|"{w}"| {ids[b]}')
        return "\n".join(lines)
    # 降级：文件级核心图
    return _hub_graph(profile, top=10, max_edges=25, direction="LR")


def mermaid_hub_graph(profile: RepoProfile, top: int = 8, max_edges: int = 30) -> str:
    """核心文件依赖图：展示指向 top 枢纽文件的入边（谁在依赖核心）。"""
    return _hub_graph(profile, top=top, max_edges=max_edges, direction="TD")


def _hub_graph(
    profile: RepoProfile, top: int, max_edges: int, direction: str
) -> str:
    hubs = [h["path"] for h in profile.hub_files[:top]]
    if not hubs:
        return f"flowchart {direction}\n  empty[\"（未检测到内部依赖）\"]"

    hub_set = set(hubs)
    in_deg = {h["path"]: h["in_degree"] for h in profile.hub_files}
    edges = [(s, d, w) for s, d, w in profile.graph_edges if d in hub_set]
    edges.sort(key=lambda e: (-e[2], e[0]))
    edges = edges[:max_edges]

    lines = [f"flowchart {direction}"]
    nodes: list[str] = list(hubs)
    for s, _, _ in edges:
        if s not in nodes:
            nodes.append(s)
    ids = {p: f"n{i}" for i, p in enumerate(nodes)}
    for p in nodes:
        if p in hub_set and in_deg.get(p, 0) >= 5:
            lines.append(f'  {ids[p]}["{_label(p)}"]:::top')
        elif p in hub_set:
            lines.append(f'  {ids[p]}["{_label(p)}"]')
        else:
            lines.append(f'  {ids[p]}["{_label(p)}"]:::caller')
    for s, d, w in edges:
        lines.append(f'  {ids[s]} -->|"{w}"| {ids[d]}')
    lines.append("  classDef top fill:#e8f0fe,stroke:#1a56db,stroke-width:2px;")
    lines.append("  classDef caller fill:#f9fafb,stroke:#9ca3af;")
    return "\n".join(lines)
