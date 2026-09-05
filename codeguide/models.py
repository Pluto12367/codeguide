"""扫描结果的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Symbol:
    """文件中的一个顶层符号（函数 / 类 / 方法）。"""

    name: str
    kind: str  # "function" | "class" | "method"
    line: int  # 1-based
    doc: str | None = None  # docstring 首行

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FileInfo:
    """单个源码文件的画像。"""

    path: str  # 相对仓库根的路径（POSIX 风格）
    language: str
    lines: int
    size_bytes: int
    module_name: str | None = None  # Python 模块名（如 "pkg.sub.mod"）
    doc: str | None = None  # 模块 docstring 首行
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # 原始 import 记录

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class RepoProfile:
    """整个仓库的画像。"""

    root: str
    name: str
    total_files: int
    total_lines: int
    languages: dict[str, dict]  # {"python": {"files": n, "lines": n}}
    files: list[FileInfo] = field(default_factory=list)
    # 依赖图：节点=文件路径，边=import 关系
    graph_nodes: list[str] = field(default_factory=list)
    graph_edges: list[list] = field(default_factory=list)  # [src, dst, weight]
    # 枢纽文件：被内部引用最多的文件，按入度排序
    hub_files: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
