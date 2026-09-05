"""依赖图构建测试。"""

from pathlib import PurePosixPath

from codeguide.deps_graph import build_dependency_graph, hub_files, module_name_for
from codeguide.models import FileInfo


def _fi(path: str, imports: list[str]) -> FileInfo:
    return FileInfo(
        path=path,
        language="python",
        lines=10,
        size_bytes=100,
        module_name=module_name_for(PurePosixPath(path)),
        imports=imports,
    )


def test_module_name_for():
    assert module_name_for(PurePosixPath("pkg/mod.py")) == "pkg.mod"
    assert module_name_for(PurePosixPath("pkg/__init__.py")) == "pkg"
    assert module_name_for(PurePosixPath("single.py")) == "single"


def test_module_name_for_src_layout():
    assert module_name_for(
        PurePosixPath("src/requests/models.py"), strip_prefix="src"
    ) == "requests.models"
    assert module_name_for(
        PurePosixPath("src/requests/__init__.py"), strip_prefix="src"
    ) == "requests"
    # 前缀不匹配时原样保留
    assert module_name_for(
        PurePosixPath("other/x.py"), strip_prefix="src"
    ) == "other.x"


def test_dependency_graph():
    files = [
        _fi("pkg/__init__.py", []),
        _fi("pkg/core.py", ["import os", "from pkg import utils"]),
        _fi("pkg/utils.py", ["from pkg.core import Engine"]),
        _fi("pkg/cli.py", ["import pkg.core", "import pkg.core"]),
        _fi("setup.py", []),
    ]
    nodes, edges = build_dependency_graph(files)
    assert "pkg/core.py" in nodes
    assert "setup.py" in nodes  # 所有 Python 文件都入图（后续 PageRank 需要）

    edges_set = {(u, v) for u, v, _ in edges}
    assert ("pkg/utils.py", "pkg/core.py") in edges_set
    assert ("pkg/cli.py", "pkg/core.py") in edges_set
    # self import 应被忽略
    assert ("pkg/core.py", "pkg/core.py") not in edges_set

    # pkg/core.py 被 utils 和 cli 依赖，入度最高
    hubs = hub_files(nodes, edges)
    assert hubs[0]["path"] == "pkg/core.py"
    assert hubs[0]["in_degree"] == 2


def test_relative_import():
    files = [
        _fi("pkg/sub/__init__.py", []),
        _fi("pkg/sub/a.py", ["from . import b"]),  # -> pkg.sub.b
        _fi("pkg/sub/b.py", []),
        _fi("pkg/other.py", ["from .sub.b import x"]),  # -> pkg.sub.b
    ]
    nodes, edges = build_dependency_graph(files)
    edges_set = {(u, v) for u, v, _ in edges}
    assert ("pkg/sub/a.py", "pkg/sub/b.py") in edges_set
    assert ("pkg/other.py", "pkg/sub/b.py") in edges_set
