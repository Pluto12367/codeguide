"""分层摘要与指南生成测试（mock LLM，不联网）。"""

import json
import re
from pathlib import Path

from codeguide.guide import generate_guide
from codeguide.scanner import scan_repo
from codeguide.summarizer import (
    FILE_SYSTEM_PROMPT,
    MODULE_SYSTEM_PROMPT,
    Summarizer,
)


class FakeClient:
    """按 system prompt 类型返回罐头回复，并记录每次调用。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append((system, user))
        if system == FILE_SYSTEM_PROMPT:
            paths = re.findall(r"^文件: (.+)$", user, re.M)
            return "\n".join(f"{p} :: 摘要{i + 1}" for i, p in enumerate(paths))
        if system == MODULE_SYSTEM_PROMPT:
            module = re.search(r"^模块: (.+)$", user, re.M).group(1)
            return f"{module} 模块负责整体逻辑"
        return "这是一个用于测试的示例项目概览。"


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        '"""核心。"""\nclass Engine:\n    """引擎。"""\n    def start(self):\n        pass\n',
        encoding="utf-8",
    )
    (root / "pkg" / "app.py").write_text(
        "from pkg.core import Engine\n\nengine = Engine()\n",
        encoding="utf-8",
    )
    return root


def test_pipeline_and_guide(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    client = FakeClient()
    summarizer = Summarizer(client, repo_root=root)
    guide = generate_guide(profile, summarizer)

    assert "# proj — 新人指南" in guide
    assert "## 1. 项目概览" in guide
    assert "示例项目概览" in guide
    assert "## 2. 阅读路线" in guide
    assert "`pkg/app.py`" in guide  # 入口文件进入阅读路线
    assert "## 3. 核心文件" in guide
    assert "`pkg/core.py`" in guide  # hub 文件出现在核心文件区
    assert "## 4. 模块地图" in guide
    assert "pkg 模块负责整体逻辑" in guide
    assert "## 5. 架构图" in guide and "```mermaid" in guide
    assert "## 6. 关键类速查" in guide
    assert "`Engine`" in guide and "引擎" in guide  # 关键类速查


def test_file_cache_avoids_repeat_calls(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)

    client1 = FakeClient()
    s1 = Summarizer(client1, repo_root=root)
    s1.summarize_files(profile, {f.path: b"x = 1\n" for f in profile.files})
    first_calls = len(client1.calls)
    assert first_calls > 0

    # 内容没变，第二次应全部命中缓存，不再发起文件摘要调用
    client2 = FakeClient()
    s2 = Summarizer(client2, repo_root=root)
    s2.summarize_files(profile, {f.path: b"x = 1\n" for f in profile.files})
    assert len(client2.calls) == 0

    # 内容变了才重新摘要
    sources = {f.path: b"x = 1\n" for f in profile.files}
    sources["pkg/core.py"] = b"x = 2\n"
    client3 = FakeClient()
    s3 = Summarizer(client3, repo_root=root)
    s3.summarize_files(profile, sources)
    assert len(client3.calls) > 0


def test_cache_persisted_to_disk(tmp_path: Path):
    root = _make_repo(tmp_path)
    profile = scan_repo(root)
    s = Summarizer(FakeClient(), repo_root=root)
    s.summarize_files(profile, {f.path: b"x = 1\n" for f in profile.files})

    cache_file = root / ".codeguide" / "file_cache.json"
    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "pkg/core.py" in data
    assert "hash" in data["pkg/core.py"] and "summary" in data["pkg/core.py"]
