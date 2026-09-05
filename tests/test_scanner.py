"""端到端扫描测试。"""

import json
from pathlib import Path

from codeguide.scanner import scan_repo


def _make_sample_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sample_proj"
    (root / "sample_proj").mkdir(parents=True)
    (root / "sample_proj" / "__init__.py").write_text("", encoding="utf-8")
    (root / "sample_proj" / "core.py").write_text(
        '"""核心逻辑。"""\n\nclass Engine:\n    def start(self):\n        pass\n',
        encoding="utf-8",
    )
    (root / "sample_proj" / "app.py").write_text(
        "from sample_proj.core import Engine\n\nengine = Engine()\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# sample\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
    return root


def test_scan_repo(tmp_path: Path):
    root = _make_sample_repo(tmp_path)
    profile = scan_repo(root)

    assert profile.name == "sample_proj"
    langs = {lang: stat["lines"] for lang, stat in profile.languages.items()}
    assert "python" in langs
    assert "markdown" in langs

    app = next(f for f in profile.files if f.path.endswith("app.py"))
    assert app.module_name == "sample_proj.app"
    assert app.imports == ["from sample_proj.core import Engine"]

    assert any(
        e[0].endswith("app.py") and e[1].endswith("core.py")
        for e in profile.graph_edges
    )
    assert profile.hub_files[0]["path"].endswith("core.py")

    # to_dict 可 JSON 序列化
    data = json.dumps(profile.to_dict(), ensure_ascii=False)
    assert "sample_proj.core" in data


def test_scan_src_layout(tmp_path: Path):
    root = tmp_path / "srcrepo"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "core.py").write_text(
        "class Engine:\n    pass\n", encoding="utf-8"
    )
    (root / "src" / "pkg" / "app.py").write_text(
        "from pkg.core import Engine\n", encoding="utf-8"
    )
    profile = scan_repo(root)

    app = next(f for f in profile.files if f.path.endswith("app.py"))
    assert app.module_name == "pkg.app"  # 无 src. 前缀
    assert any(
        e[0].endswith("app.py") and e[1].endswith("core.py")
        for e in profile.graph_edges
    )
    assert profile.hub_files[0]["path"].endswith("core.py")
