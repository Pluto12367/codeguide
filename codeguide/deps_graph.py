"""Python import 依赖图构建 + JS/TS 相对路径依赖 + 循环依赖检测。"""

from __future__ import annotations

import posixpath
from itertools import islice
from pathlib import Path, PurePosixPath

import networkx as nx

from .models import FileInfo

JS_EXTENSIONS = ("", ".js", ".ts", ".jsx", ".tsx")
MAX_CYCLES = 20


def module_name_for(path: PurePosixPath, strip_prefix: str | None = None) -> str | None:
    """文件路径 -> Python 模块名。__init__.py 映射为包名本身。

    strip_prefix 用于 src-layout 仓库：传入 "src" 时剥掉首段，
    使 src/requests/models.py 映射为 requests.models。
    """
    parts = list(path.with_suffix("").parts)
    if not parts:
        return None
    if strip_prefix and parts[0] == strip_prefix:
        parts = parts[1:]
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None  # 根目录的 __init__.py
    if any(not p.isidentifier() for p in parts):
        # 目录名带点或非法字符（如 "pkg-1.0"），无法映射为模块名
        return None
    return ".".join(parts)


def _resolve_absolute(module: str, module_map: dict[str, str]) -> str | None:
    """绝对导入 -> 内部文件路径。import a.b.c 时优先匹配最长前缀。"""
    parts = module.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in module_map:
            return module_map[candidate]
        parts.pop()
    return None


def _resolve_relative(module: str, package: str) -> str | None:
    """相对导入（module 以 . 开头）-> 绝对模块名。

    package 是发起导入的文件所属的包（__init__.py 本身就是包；
    普通模块取其父级）。
    """
    if not module.startswith("."):
        return module
    if not package:
        return None
    dots = len(module) - len(module.lstrip("."))
    rest = module.lstrip(".").strip()
    # 1 个点 = 当前包；每多 1 个点向上一层
    parts = package.split(".")
    if dots - 1 > len(parts):
        return None
    base = parts[: len(parts) - (dots - 1)] if dots > 1 else parts
    if not rest:
        return ".".join(base)
    return ".".join(base) + "." + rest


def package_of(file: FileInfo) -> str | None:
    """文件所属包名：__init__.py 是包本身，普通模块取父级。"""
    if not file.module_name:
        return None
    if file.path.endswith("__init__.py"):
        return file.module_name
    if "." not in file.module_name:
        return None  # 顶层模块不在任何包内，无法解析相对导入
    return file.module_name.rsplit(".", 1)[0]


def resolve_js_import(importing_file: str, source: str, path_set: set[str]) -> str | None:
    """JS 相对导入 -> 仓库内文件路径；非相对导入（npm 包）返回 None。"""
    if not source.startswith("."):
        return None
    base = posixpath.normpath(
        posixpath.join(posixpath.dirname(importing_file), source)
    )
    candidates = [base + ext for ext in JS_EXTENSIONS]
    candidates += [posixpath.join(base, "index" + ext) for ext in JS_EXTENSIONS[1:]]
    for cand in candidates:
        if cand in path_set and cand != importing_file:
            return cand
    return None


def build_dependency_graph(files: list[FileInfo]) -> tuple[list[str], list[list]]:
    """构建文件级依赖图。

    返回 (nodes, edges)，edge = [src_path, dst_path, weight]。
    Python 文件按模块名解析 import；JS/TS 文件解析相对路径 import
    （npm 包为外部依赖，不进图）。
    """
    module_map: dict[str, str] = {}
    for f in files:
        if f.module_name:
            module_map[f.module_name] = f.path

    graph = nx.DiGraph()
    py_files = [f for f in files if f.language == "python" and f.module_name]
    js_files = [
        f for f in files if f.language in ("javascript", "typescript")
    ]
    for f in py_files + js_files:
        graph.add_node(f.path)
    path_set = {f.path for f in files}

    for f in py_files:
        package = package_of(f)
        for record in f.imports:
            if record.startswith("from "):
                rest = record[len("from "):]
                module_part, _, names_part = rest.partition(" import ")
                for name in [n for n in names_part.split(",") if n]:
                    if module_part.startswith("."):
                        absolute = _resolve_relative(module_part, package)
                    else:
                        absolute = module_part
                    if not absolute:
                        continue
                    target = (
                        _resolve_absolute(f"{absolute}.{name.strip()}", module_map)
                        # name 可能是模块也可能是符号；先试模块
                        or _resolve_absolute(absolute, module_map)
                    )
                    if target and target != f.path:
                        _add_edge(graph, f.path, target)
            elif record.startswith("import "):
                for module in record[len("import "):].split(","):
                    module = module.strip()
                    absolute = (
                        _resolve_relative(module, package)
                        if module.startswith(".")
                        else module
                    )
                    target = _resolve_absolute(absolute, module_map) if absolute else None
                    if target and target != f.path:
                        _add_edge(graph, f.path, target)

    for f in js_files:
        for record in f.imports:
            if record.startswith("jsimport "):
                source = record[len("jsimport "):]
                target = resolve_js_import(f.path, source, path_set)
                if target:
                    _add_edge(graph, f.path, target)

    edges = [[u, v, d.get("weight", 1)] for u, v, d in graph.edges(data=True)]
    nodes = sorted(graph.nodes())
    return nodes, edges


def _add_edge(graph: nx.DiGraph, src: str, dst: str) -> None:
    if graph.has_edge(src, dst):
        graph[src][dst]["weight"] += 1
    else:
        graph.add_edge(src, dst, weight=1)


def find_cycles(nodes: list[str], edges: list[list], max_cycles: int = MAX_CYCLES) -> list[list[str]]:
    """检测文件级循环依赖，返回至多 max_cycles 个环（每个环内路径排序）。"""
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    for src, dst, _w in edges:
        graph.add_edge(src, dst)
    if graph.number_of_nodes() == 0 or nx.is_directed_acyclic_graph(graph):
        return []
    cycles = [
        sorted(cycle) for cycle in islice(nx.simple_cycles(graph), max_cycles)
    ]
    cycles.sort()
    return cycles


def hub_files(nodes: list[str], edges: list[list], top: int = 10) -> list[dict]:
    """按入度（被多少文件依赖）返回枢纽文件。"""
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    for src, dst, w in edges:
        graph.add_edge(src, dst, weight=w)
    scored = sorted(graph.in_degree(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"path": path, "in_degree": degree}
        for path, degree in scored[:top]
        if degree > 0
    ]
