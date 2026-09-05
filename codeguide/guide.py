"""把分层摘要组装成 Markdown 新人指南。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .diagram import mermaid_module_graph
from .models import RepoProfile
from .roadmap import reading_route
from .summarizer import Summarizer

GUIDE_HEADER = """# {name} — 新人指南

> 由 CodeGuide 生成于 {date} · {files} 个源码文件 · {lines} 行代码

"""


def run_summaries(
    profile: RepoProfile, summarizer: Summarizer, progress=None
) -> tuple[dict[str, bytes], dict[str, str], dict[str, list[str]], dict[str, str], str]:
    """跑完整 LLM 流水线，返回 (sources, summaries, groups, module_summaries, overview)。"""
    sources: dict[str, bytes] = {}
    for f in profile.files:
        try:
            sources[f.path] = (Path(profile.root) / f.path).read_bytes()
        except OSError:
            sources[f.path] = b""

    summaries = summarizer.summarize_files(profile, sources, progress)
    groups = summarizer.group_by_module(profile, summaries)
    module_summaries = summarizer.summarize_modules(groups, summaries, progress)
    overview = summarizer.summarize_repo(profile, module_summaries, summaries)
    return sources, summaries, groups, module_summaries, overview


def generate_guide(
    profile: RepoProfile, summarizer: Summarizer, progress=None
) -> str:
    """跑完整流水线并返回 Markdown 指南文本。"""
    _, summaries, groups, module_summaries, overview = run_summaries(
        profile, summarizer, progress
    )
    return _render(profile, overview, groups, summaries, module_summaries)


def _render(
    profile: RepoProfile,
    overview: str,
    groups: dict[str, list[str]],
    summaries: dict[str, str],
    module_summaries: dict[str, str],
) -> str:
    out = [GUIDE_HEADER.format(
        name=profile.name, date=date.today().isoformat(),
        files=profile.total_files, lines=f"{profile.total_lines:,}",
    )]

    out.append("## 1. 项目概览\n")
    out.append(overview + "\n")

    route = reading_route(profile)
    out.append("## 2. 阅读路线\n")
    if route:
        for i, item in enumerate(route, 1):
            out.append(
                f"{i}. **`{item['path']}`** 〔{item['phase']}〕— {item['reason']}"
            )
    else:
        out.append("（未检测到显著的内部依赖关系）")
    out.append("")

    out.append("## 3. 核心文件（被内部依赖最多）\n")
    if profile.hub_files:
        for h in profile.hub_files[:8]:
            summary = summaries.get(h["path"], "")
            out.append(f"- **`{h['path']}`**（被 {h['in_degree']} 个文件依赖）— {summary}")
    else:
        out.append("（未检测到显著的内部依赖关系）")
    out.append("")

    out.append("## 4. 模块地图\n")
    for module in sorted(groups):
        out.append(f"### {module}\n")
        out.append(f"**模块职责**：{module_summaries.get(module, '')}\n")
        for p in sorted(groups[module]):
            out.append(f"- `{p}` — {summaries.get(p, '')}")
        out.append("")

    out.append("## 5. 架构图\n")
    out.append("```mermaid")
    out.append(mermaid_module_graph(profile))
    out.append("```\n")

    if profile.cycles:
        out.append("## ⚠️ 循环依赖\n")
        out.append(f"检测到 {len(profile.cycles)} 组循环依赖（改动需整组回归）：\n")
        for cycle in profile.cycles[:10]:
            out.append(f"- {' → '.join(cycle)} → {cycle[0]}")
        out.append("")

    out.append("## 6. 关键类速查\n")
    doc_classes = [
        (f.path, s)
        for f in profile.files
        for s in f.symbols
        if s.kind == "class" and s.doc
    ]
    hub_order = {h["path"]: i for i, h in enumerate(profile.hub_files)}
    doc_classes.sort(key=lambda item: (hub_order.get(item[0], 999), item[0]))
    for path, s in doc_classes[:15]:
        out.append(f"- `{s.name}`（`{path}` L{s.line}）— {s.doc}")
    if not doc_classes:
        out.append("（未提取到带 docstring 的类）")
    out.append("")

    out.append("---\n*本指南由 CodeGuide 静态分析 + LLM 分层摘要自动生成，"
               "摘要可能存在偏差，以源码为准。*")
    return "\n".join(out)
