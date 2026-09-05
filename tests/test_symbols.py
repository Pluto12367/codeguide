"""符号与 import 提取测试。"""

from codeguide.symbols import extract_imports, extract_python


def _parse(source: str):
    return extract_python("x.py", source.encode("utf-8"))

def test_extract_symbols():
    source = '''
import os

def top_func(a, b):
    """计算两数之和。"""
    return a + b

class Calculator:
    """一个计算器。"""

    def add(self, x):
        return x + 1

    @staticmethod
    def util():
        pass

@decorator
def decorated():
    pass
'''
    symbols, imports, doc = _parse(source)
    assert doc is None  # 该源码没有模块 docstring
    names = {(s.name, s.kind) for s in symbols}
    assert ("top_func", "function") in names
    assert ("Calculator", "class") in names
    assert ("add", "method") in names
    assert ("util", "method") in names
    assert ("decorated", "function") in names

    top_func = next(s for s in symbols if s.name == "top_func")
    assert top_func.doc == "计算两数之和。"
    assert top_func.line == 4

    assert imports == ["import os"]


def test_extract_imports():
    source = '''
import os
import a.b.c as abc
from x.y import z, w
from . import sibling
from ..pkg import thing
from .relmod import item
'''
    imports = extract_imports_from(source)
    assert "import os" in imports
    assert "import a.b.c" in imports
    assert "from x.y import z,w" in imports
    assert any(i.startswith("from . import") for i in imports)
    assert "from ..pkg import thing" in imports
    assert "from .relmod import item" in imports


def extract_imports_from(source: str):
    import tree_sitter_python
    from tree_sitter import Language, Parser

    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(source.encode("utf-8"))
    return extract_imports(tree.root_node)
