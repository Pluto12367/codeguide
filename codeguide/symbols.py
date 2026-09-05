"""基于 tree-sitter 的 Python 符号与 import 提取。

多语言扩展方式：为其他语言实现同样的 SymbolExtractor 接口，
注册到 EXTRACTORS 即可，扫描器本身不感知语言差异。
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python
from tree_sitter import Language, Parser

from .models import Symbol

_PY_LANGUAGE = Language(tree_sitter_python.language())
_parser = Parser(_PY_LANGUAGE)


def _node_text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _first_docstring(body_node) -> str | None:
    """取函数/类 body 的第一个字符串表达式作为 docstring 首行。"""
    if body_node is None:
        return None
    for child in body_node.named_children:
        if child.type == "expression_statement":
            for sub in child.named_children:
                if sub.type == "string":
                    text = _node_text(sub).strip()
                    # 去掉引号，取首行
                    text = text.strip("\"'")
                    first_line = text.splitlines()[0].strip() if text else ""
                    return first_line or None
        break  # 只看第一条语句
    return None


def _extract_def(node, kind: str) -> Symbol | None:
    """从 function_definition / class_definition 节点提取符号。"""
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    doc = _first_docstring(node.child_by_field_name("body"))
    return Symbol(
        name=_node_text(name_node),
        kind=kind,
        line=node.start_point[0] + 1,
        doc=doc,
    )


def _walk_definitions(node, symbols: list[Symbol], in_class: bool = False) -> None:
    for child in node.named_children:
        t = child.type
        if t == "decorated_definition":
            # 装饰器定义：取其内部的 definition
            for sub in child.named_children:
                if sub.type in ("function_definition", "class_definition"):
                    kind = "class" if sub.type == "class_definition" else (
                        "method" if in_class else "function"
                    )
                    sym = _extract_def(sub, kind)
                    if sym:
                        symbols.append(sym)
                    if sub.type == "class_definition":
                        body = sub.child_by_field_name("body")
                        if body:
                            _walk_definitions(body, symbols, in_class=True)
            continue
        if t == "function_definition":
            sym = _extract_def(child, "method" if in_class else "function")
            if sym:
                symbols.append(sym)
        elif t == "class_definition":
            sym = _extract_def(child, "class")
            if sym:
                symbols.append(sym)
            body = child.child_by_field_name("body")
            if body:
                _walk_definitions(body, symbols, in_class=True)
        elif t in ("if_statement", "try_statement", "with_statement"):
            # 模块级条件定义（如 try import fallback）也扫一遍
            _walk_definitions(child, symbols, in_class)


def extract_imports(node) -> list[str]:
    """提取 import 语句的原始记录。

    返回形如 "import a.b" / "from a.b import c,d" / "from .x import y" 的字符串。
    """
    imports: list[str] = []

    def walk(n):
        if n.type == "import_statement":
            names = []
            for child in n.named_children:
                if child.type == "dotted_name":
                    names.append(_node_text(child))
                elif child.type == "aliased_import":
                    dotted = child.child_by_field_name("name")
                    if dotted:
                        names.append(_node_text(dotted))
            if names:
                imports.append("import " + ",".join(names))
        elif n.type == "import_from_statement":
            module_node = n.child_by_field_name("module_name")
            if module_node is not None:
                module = _node_text(module_node)
                names = []
                for child in n.named_children:
                    if child.type == "dotted_name" and child.id != module_node.id:
                        names.append(_node_text(child))
                    elif child.type == "aliased_import":
                        dotted = child.child_by_field_name("name")
                        if dotted:
                            names.append(_node_text(dotted))
                imports.append(f"from {module} import {','.join(names)}")
            elif any(c.type == "relative_import" for c in n.named_children):
                for child in n.named_children:
                    if child.type == "relative_import":
                        imports.append("from " + _node_text(child).replace("\n", " "))
        else:
            for child in n.named_children:
                walk(child)

    walk(node)
    return imports


def extract_python(path: Path, source: bytes) -> tuple[list[Symbol], list[str]]:
    """解析一个 Python 文件，返回 (symbols, imports)。"""
    tree = _parser.parse(source)
    root = tree.root_node

    symbols: list[Symbol] = []
    _walk_definitions(root, symbols)
    imports = extract_imports(root)
    return symbols, imports
