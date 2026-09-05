"""Mermaid 架构图与模块分组测试。"""

from codeguide.diagram import mermaid_hub_graph, mermaid_module_graph
from codeguide.languages import module_group
from codeguide.models import FileInfo, RepoProfile


def test_module_group():
    assert module_group("src/requests/models.py") == "requests"
    assert module_group("src/__init__.py") == "src"
    assert module_group("cli.py") == "(root)"
    assert module_group("pkg/sub/a.py") == "pkg"


def _profile_with_edges(edges: list[tuple[str, str, int]]) -> RepoProfile:
    """构造带指定依赖边的最小画像。"""
    nodes = sorted({e[0] for e in edges} | {e[1] for e in edges})
    hub = {}
    for _, d, _ in edges:
        hub[d] = hub.get(d, 0) + 1
    return RepoProfile(
        root="/fake", name="fake",
        total_files=len(nodes), total_lines=100,
        languages={"python": {"files": len(nodes), "lines": 100}},
        files=[], graph_nodes=nodes,
        graph_edges=[list(e) for e in edges],
        hub_files=[{"path": p, "in_degree": n} for p, n in
                   sorted(hub.items(), key=lambda kv: -kv[1])],
    )


def test_module_graph_mermaid():
    profile = _profile_with_edges([
        ("cli.py", "pkg/core.py", 2),      # (root) -> pkg
        ("pkg/core.py", "other/util.py", 1),  # pkg -> other
    ])
    text = mermaid_module_graph(profile)
    assert text.startswith("flowchart LR")
    assert '["pkg"]' in text and '["(root)"]' in text and '["other"]' in text
    assert '-->|"' in text  # 带权边
    assert '"2"' in text


def test_module_graph_empty():
    profile = _profile_with_edges([])
    text = mermaid_module_graph(profile)
    assert "flowchart LR" in text and "未检测到" in text


def test_module_graph_fallback_single_package():
    """单包仓库：跨模块边 < 2 时应降级为文件级图（含真实文件名）。"""
    profile = _profile_with_edges([
        ("pkg/cli.py", "pkg/core.py", 2),
        ("pkg/utils.py", "pkg/core.py", 1),
    ])
    text = mermaid_module_graph(profile)
    assert text.startswith("flowchart LR")
    assert "pkg/core.py" in text  # 展示的是文件而不是空图


def test_hub_graph_mermaid():
    profile = _profile_with_edges([
        ("pkg/cli.py", "pkg/core.py", 1),
        ("pkg/utils.py", "pkg/core.py", 3),
    ])
    text = mermaid_hub_graph(profile, top=8)
    assert text.startswith("flowchart TD")
    assert "pkg/core.py" in text  # 枢纽节点
    assert "pkg/utils.py" in text  # 依赖方也在图中
    assert '-->|' in text
    assert "classDef top" in text


def test_label_sanitized():
    # 文件名中的引号必须被转义，且不能破坏 mermaid 语法
    profile = _profile_with_edges([("a'b.py", "c\"d.py", 1)])
    text = mermaid_hub_graph(profile, top=5)
    assert '\\"' not in text  # 不允许裸双引号出现在标签里
    assert "c'd.py" in text
