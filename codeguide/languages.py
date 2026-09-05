"""语言检测与文件收集。"""

from __future__ import annotations

import os
from pathlib import Path

# 扩展名 -> 语言名
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".md": "markdown",
    ".rst": "markdown",
}

# 这些目录直接跳过，不进入扫描
SKIP_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".codeguide",
    "site-packages",
    ".eggs",
    "*.egg-info",
}

# 明确跳过的文件类型（二进制 / 产物）
BINARY_EXTS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pyc", ".pyo", ".class", ".o", ".a", ".lib",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".pickle", ".pkl",
    ".lock", ".csv", ".tsv",
}

MAX_FILE_BYTES = 1_000_000  # 超过 1MB 的单个文件不解析


def detect_language(path: Path) -> str | None:
    return EXTENSION_MAP.get(path.suffix.lower())


def is_source_file(path: Path) -> bool:
    """是有语言的源码文件，且不是锁文件等产物。"""
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTS:
        return False
    if path.name in ("package-lock.json", "poetry.lock", "Pipfile.lock", "uv.lock"):
        return False
    return suffix in EXTENSION_MAP


def module_group(path: str) -> str:
    """文件路径 -> 展示用的模块分组名（src-layout 感知）。

    src/requests/models.py -> requests；cli.py -> (root)；pkg/a.py -> pkg
    """
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    if parts[0] == "src" and len(parts) > 2:
        return parts[1]
    return parts[0]


def iter_source_files(root: Path) -> list[Path]:
    """递归收集仓库内所有源码文件，跳过 SKIP_DIRS 与二进制文件。"""
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地过滤，避免 os.walk 深入无关目录
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for fname in filenames:
            p = Path(dirpath) / fname
            if not is_source_file(p):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            results.append(p)
    results.sort()
    return results
