"""HTML 报告生成测试。"""

from pathlib import Path

from codeguide.report import render_report, write_report
from codeguide.scanner import scan_repo


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        '"""核心。"""\nclass Engine:\n    """引擎。"""\n'
        "    def start(self):\n        pass\n",
        encoding="utf-8",
    )
    (root / "pkg" / "app.py").write_text(
        "from pkg.core import Engine\n\nengine = Engine()\n",
        encoding="utf-8",
    )
    return root


def test_render_report_static(tmp_path: Path):
    profile = scan_repo(_make_repo(tmp_path))
    html = render_report(profile)

    assert "<!DOCTYPE html>" in html
    assert "proj" in html
    assert "mermaid.initialize" in html
    assert "flowchart" in html              # 静态模块 mermaid 图
    assert "阅读路线" in html
    assert "循环依赖" in html
    assert "风险热区" in html
    assert "规模地图" in html
    assert "模块地图" in html
    assert "符号速查" in html
    assert "Engine" in html                 # 符号 JSON 已嵌入
    assert "SYMBOLS = [" in html
    assert "纯静态分析" in html              # 无 LLM 标记


def test_report_interactive_data(tmp_path: Path):
    """交互层数据与 UI 骨架齐全。"""
    profile = scan_repo(_make_repo(tmp_path))
    html = render_report(profile)

    # 内嵌交互数据
    assert "REPORT = {" in html
    assert '"previews"' in html and '"graph"' in html
    assert '"deps"' in html and '"dependents"' in html
    assert '"pagerank"' in html and '"phases"' in html

    # 交互组件
    assert 'id="cy"' in html                # cytoscape 容器
    assert "cytoscape.use(cytoscapeDagre)" in html
    assert 'id="drawer"' in html            # 文件抽屉
    assert 'id="palette-overlay"' in html   # Cmd+K 面板
    assert "new Fuse(" in html
    assert 'id="treemap"' in html           # treemap 区块
    assert "d3.treemap()" in html
    assert 'data-theme="dark"' in html      # 暗色模式令牌
    assert "theme-toggle" in html

    # 降级保底文案
    assert "CDN 不可用" in html


def test_render_report_with_llm(tmp_path: Path):
    profile = scan_repo(_make_repo(tmp_path))
    html = render_report(profile, llm={
        "overview": "这是一个测试项目。",
        "summaries": {"pkg/core.py": "核心引擎模块"},
        "module_summaries": {"pkg": "包职责描述"},
    })
    assert "这是一个测试项目。" in html
    assert "核心引擎模块" in html
    assert "包职责描述" in html
    assert "含 LLM 摘要" in html


def test_write_report(tmp_path: Path):
    profile = scan_repo(_make_repo(tmp_path))
    out = tmp_path / "out" / "report.html"
    out.parent.mkdir()
    write_report(profile, out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
