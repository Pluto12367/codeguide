"""仓库扫描器：把各模块拼成完整的仓库画像。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .deps_graph import build_dependency_graph, hub_files, module_name_for
from .languages import detect_language, iter_source_files
from .models import FileInfo, RepoProfile
from .symbols import extract_python


def detect_src_layout(rel_paths: list[str]) -> str | None:
    """所有 Python 文件都在 src/ 下时返回 "src"（src-layout 约定）。"""
    py_rels = [r for r in rel_paths if r.endswith(".py")]
    if py_rels and all(r.startswith("src/") for r in py_rels):
        return "src"
    return None


def scan_repo(root: Path) -> RepoProfile:
    """扫描仓库根目录，返回 RepoProfile。"""
    root = root.resolve()
    source_files = iter_source_files(root)
    rel_paths = [p.relative_to(root).as_posix() for p in source_files]
    strip_prefix = detect_src_layout(rel_paths)

    files: list[FileInfo] = []
    for path in source_files:
        rel = path.relative_to(root).as_posix()
        language = detect_language(path) or "unknown"

        try:
            source = path.read_bytes()
        except OSError:
            continue
        text_lines = source.count(b"\n") + (1 if source and not source.endswith(b"\n") else 0)

        symbols: list = []
        imports: list[str] = []
        module_name = None
        module_doc = None
        if language == "python":
            module_name = module_name_for(PurePosixPath(rel), strip_prefix=strip_prefix)
            try:
                symbols, imports, module_doc = extract_python(path, source)
            except Exception:
                # 语法错误等解析失败不应中断整个扫描
                symbols, imports, module_doc = [], [], None

        files.append(
            FileInfo(
                path=rel,
                language=language,
                lines=text_lines,
                size_bytes=len(source),
                module_name=module_name,
                doc=module_doc,
                symbols=symbols,
                imports=imports,
            )
        )

    # 语言统计（行数口径，纯文本文件也计入）
    languages: dict[str, dict] = {}
    for f in files:
        stat = languages.setdefault(f.language, {"files": 0, "lines": 0})
        stat["files"] += 1
        stat["lines"] += f.lines

    nodes, edges = build_dependency_graph(files)

    return RepoProfile(
        root=str(root),
        name=root.name,
        total_files=len(files),
        total_lines=sum(f.lines for f in files),
        languages=languages,
        files=files,
        graph_nodes=nodes,
        graph_edges=edges,
        hub_files=hub_files(nodes, edges),
    )
