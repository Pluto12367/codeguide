"""PageRank 阅读路线测试。"""

from pathlib import PurePosixPath

from codeguide.deps_graph import build_dependency_graph, module_name_for
from codeguide.models import FileInfo, RepoProfile
from codeguide.roadmap import PHASE_CORE, PHASE_ENTRY, reading_route


def _fi(path: str, imports: list[str]) -> FileInfo:
    return FileInfo(
        path=path, language="python", lines=10, size_bytes=100,
        module_name=module_name_for(PurePosixPath(path)), imports=imports,
    )


def _profile(files: list[FileInfo]) -> RepoProfile:
    nodes, edges = build_dependency_graph(files)
    from codeguide.deps_graph import hub_files

    return RepoProfile(
        root="/fake", name="fake", total_files=len(files), total_lines=100,
        languages={"python": {"files": len(files), "lines": 100}},
        files=files, graph_nodes=nodes, graph_edges=edges,
        hub_files=hub_files(nodes, edges),
    )


def test_route_phases():
    files = [
        _fi("pkg/__init__.py", []),
        # core 是枢纽：被 utils/cli/api 依赖
        _fi("pkg/core.py", ["import pkg.utils"]),
        _fi("pkg/utils.py", []),
        _fi("pkg/cli.py", ["import pkg.core", "import pkg.utils"]),
        _fi("pkg/api.py", ["import pkg.core"]),
    ]
    route = reading_route(_profile(files))

    assert route, "有依赖时必须产出路线"
    phases = [item["phase"] for item in route]

    # cli.py 没人导入（有出度）→ 应在起步阶段
    entries = [i for i in route if i["phase"] == PHASE_ENTRY]
    assert any(i["path"] == "pkg/cli.py" for i in entries)

    # core.py / utils.py 是 PageRank 最高的枢纽 → 在核心阶段，且按分数降序
    core = [i for i in route if i["phase"] == PHASE_CORE]
    assert core
    paths = {i["path"] for i in core}
    assert {"pkg/core.py", "pkg/utils.py"} <= paths
    scores = [i["pagerank"] for i in core]
    assert scores == sorted(scores, reverse=True)
    assert core[0]["path"] == "pkg/utils.py"  # 它还被核心文件 core.py 依赖

    # 起步在前，核心在后
    assert phases.index(PHASE_ENTRY) < phases.index(PHASE_CORE) or \
        PHASE_CORE not in phases

    # 字段完整
    item = route[0]
    assert {"path", "phase", "reason", "pagerank", "in_degree", "out_degree"} <= set(item)


def test_route_empty_graph():
    files = [_fi("solo.py", ["import os"])]
    profile = _profile(files)
    # 没有内部边
    profile.graph_edges = []
    assert reading_route(profile) == []
