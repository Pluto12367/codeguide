"""语言检测与文件收集测试。"""

from pathlib import Path

from codeguide.languages import detect_language, is_source_file, iter_source_files


def test_detect_language():
    assert detect_language(Path("a/b.py")) == "python"
    assert detect_language(Path("x.PY")) == "python"
    assert detect_language(Path("main.ts")) == "typescript"
    assert detect_language(Path("readme.md")) == "markdown"
    assert detect_language(Path("data.bin")) is None


def test_is_source_file():
    assert is_source_file(Path("a.py"))
    assert not is_source_file(Path("logo.png"))
    assert not is_source_file(Path("poetry.lock"))


def test_iter_source_files_skips(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)}
    assert found == {"src/main.py"}
