"""LLM 分层摘要流水线：文件 → 模块 → 全局。

设计要点：
- 每层只把上一层压缩后的结果交给下一层，控制 token 用量；
- 文件摘要按批合并请求（一次调用摘要 5 个文件），进一步省钱省时；
- 文件级摘要落盘缓存（key = 文件内容哈希），重复扫描不重复调用 API。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .languages import module_group
from .models import FileInfo, RepoProfile

FILE_SOURCE_LIMIT = 120  # 行数不超过此值的文件附带全文，否则只给符号大纲
BATCH_SIZE = 5
CACHE_DIR = ".codeguide"
CACHE_FILE = "file_cache.json"

FILE_SYSTEM_PROMPT = (
    "你是资深软件工程师。阅读以下 Python 源码文件信息，"
    "为每个文件写一句中文摘要（不超过 40 字），说明它的职责。"
    "严格按行输出，格式为：文件路径 :: 摘要，不要输出其他内容。"
)

MODULE_SYSTEM_PROMPT = (
    "你是资深软件工程师。下面是一个代码仓库中某个模块内所有文件的摘要。"
    "请用 2-3 句中文概括这个模块的整体职责，直接输出概括，不要有标题。"
)

REPO_SYSTEM_PROMPT = (
    "你是资深软件工程师，正在为新加入的同事写一份代码库导览。"
    "根据各模块的摘要与仓库统计，写一段 3-5 句的中文项目概览："
    "这个项目是什么、整体如何分层组织、新人应该建立怎样的心智模型。"
    "直接输出概览，不要有标题。"
)


@dataclass
class FileSummary:
    path: str
    summary: str


def _source_hash(source: bytes) -> str:
    return hashlib.sha1(source).hexdigest()


def file_context(f: FileInfo, source: bytes | None) -> str:
    """把一个文件压缩成喂给 LLM 的文本。"""
    parts = [f"文件: {f.path}", f"行数: {f.lines}"]
    if f.imports:
        parts.append("导入: " + "; ".join(f.imports[:12]))
    if f.symbols:
        lines = []
        for s in f.symbols:
            doc = f"  # {s.doc}" if s.doc else ""
            lines.append(f"  {s.kind} {s.name} (L{s.line}){doc}")
        parts.append("符号:\n" + "\n".join(lines))
    if source is not None:
        parts.append("源码:\n```python\n" + source.decode("utf-8", errors="replace") + "\n```")
    return "\n".join(parts)


class Summarizer:
    def __init__(self, client, repo_root: Path, verbose: bool = False):
        self.client = client
        self.repo_root = repo_root
        self.verbose = verbose
        self.cache_path = repo_root / CACHE_DIR / CACHE_FILE
        self._cache: dict[str, dict] = self._load_cache()

    # ---------- 缓存 ----------

    def _load_cache(self) -> dict[str, dict]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---------- 第一层：文件摘要 ----------

    def summarize_files(
        self, profile: RepoProfile, sources: dict[str, bytes], progress=None
    ) -> dict[str, str]:
        """返回 {文件路径: 一句话摘要}，带批处理与缓存。"""
        summaries: dict[str, str] = {}
        todo: list[FileInfo] = []

        for f in profile.files:
            if f.language != "python" or not f.symbols and not f.imports:
                continue
            h = _source_hash(sources[f.path])
            cached = self._cache.get(f.path)
            if cached and cached.get("hash") == h:
                summaries[f.path] = cached["summary"]
            else:
                todo.append(f)

        batches = [
            todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)
        ]
        for bi, batch in enumerate(batches):
            if progress:
                progress(f"文件摘要 {bi + 1}/{len(batches)}")
            contexts = [
                file_context(f, sources[f.path] if f.lines <= FILE_SOURCE_LIMIT else None)
                for f in batch
            ]
            user_msg = "\n\n".join(
                "=" * 20 + f" 第{i + 1}个文件 " + "=" * 20 + "\n" + c
                for i, c in enumerate(contexts)
            )
            expected = [f.path for f in batch]
            parsed = self._parse_summaries(
                self.client.chat(FILE_SYSTEM_PROMPT, user_msg, max_tokens=600),
                expected,
            )
            # 批量结果缺失的文件逐个重试
            missing = [p for p in expected if p not in parsed]
            for p in missing:
                f = next(x for x in batch if x.path == p)
                try:
                    parsed[p] = self.client.chat(
                        "用一句不超过 40 字的中文概括这个文件的职责，直接输出摘要。",
                        file_context(f, sources[f.path] if f.lines <= FILE_SOURCE_LIMIT else None),
                        max_tokens=120,
                    )
                except Exception:
                    parsed[p] = "（摘要生成失败）"

            for f in batch:
                s = parsed.get(f.path, "（摘要生成失败）")
                summaries[f.path] = s
                self._cache[f.path] = {"hash": _source_hash(sources[f.path]), "summary": s}

        self._save_cache()
        return summaries

    @staticmethod
    def _parse_summaries(text: str, expected: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            m = re.match(r"^(.+?)\s*::\s*(.+)$", line.strip())
            if not m:
                continue
            path, summary = m.group(1).strip(), m.group(2).strip()
            for e in expected:
                if path == e or path.endswith("/" + e) or e.endswith("/" + path):
                    result[e] = summary
                    break
        return result

    # ---------- 第二层：模块摘要 ----------

    def group_by_module(self, profile: RepoProfile, summaries: dict[str, str]) -> dict[str, list[str]]:
        """按展示模块分组（src-layout 感知）；根目录文件归入 (root)。"""
        groups: dict[str, list[str]] = {}
        for f in profile.files:
            if f.path not in summaries:
                continue
            groups.setdefault(module_group(f.path), []).append(f.path)
        return groups

    def summarize_modules(
        self, groups: dict[str, list[str]], summaries: dict[str, str], progress=None
    ) -> dict[str, str]:
        module_summaries: dict[str, str] = {}
        items = sorted(groups.items())
        for i, (module, paths) in enumerate(items):
            if progress:
                progress(f"模块摘要 {i + 1}/{len(items)}: {module}")
            listing = "\n".join(f"- {p} :: {summaries[p]}" for p in paths)
            module_summaries[module] = self.client.chat(
                MODULE_SYSTEM_PROMPT, f"模块: {module}\n\n{listing}", max_tokens=300
            )
        return module_summaries

    # ---------- 第三层：全局概览 ----------

    def summarize_repo(
        self,
        profile: RepoProfile,
        module_summaries: dict[str, str],
        summaries: dict[str, str],
    ) -> str:
        stats = (
            f"仓库: {profile.name}，共 {profile.total_files} 个源码文件、"
            f"{profile.total_lines} 行代码。语言构成: "
            + ", ".join(
                f"{lang}({stat['files']}文件)" for lang, stat in profile.languages.items()
            )
        )
        hubs = ""
        if profile.hub_files:
            hubs = "被内部依赖最多的文件:\n" + "\n".join(
                f"- {h['path']}（被 {h['in_degree']} 个文件依赖）:: "
                + summaries.get(h["path"], "")
                for h in profile.hub_files[:8]
            )
        modules = "模块摘要:\n" + "\n".join(
            f"- {m}: {s}" for m, s in module_summaries.items()
        )
        return self.client.chat(
            REPO_SYSTEM_PROMPT, f"{stats}\n\n{modules}\n\n{hubs}", max_tokens=500
        )
