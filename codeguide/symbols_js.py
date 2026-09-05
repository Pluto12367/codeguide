"""基于 tree-sitter 的 JavaScript/TypeScript 符号与 import 提取。

识别：function/class 声明（含 export 包裹）、类方法、
const fn = () => {} 形式的箭头函数；import / require /
export...from 的模块路径。import 记录以 "jsimport <路径>" 前缀
存储，相对路径由 deps_graph 解析为仓库内文件边。
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

from .models import Symbol

_parsers: dict[str, Parser] = {}


def _parser_for(kind: str) -> Parser:
    if kind not in _parsers:
        if kind == "js":
            lang = Language(tree_sitter_javascript.language())
        elif kind == "ts":
            lang = Language(tree_sitter_typescript.language_typescript())
        elif kind == "tsx":
            lang = Language(tree_sitter_typescript.language_tsx())
        else:
            raise ValueError(kind)
        _parsers[kind] = Parser(lang)
    return _parsers[kind]


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _unquote(node) -> str:
    t = _text(node).strip()
    return t.strip("'\"")


def _func_symbol(node, kind: str = "function") -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return Symbol(name=_text(name_node), kind=kind, line=node.start_point[0] + 1)


def _walk_class(node, symbols: list[Symbol]) -> None:
    sym = _func_symbol(node, "class")
    if sym:
        symbols.append(sym)
    body = node.child_by_field_name("body")
    if body is None:
        return
    for child in body.named_children:
        if child.type == "method_definition":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                symbols.append(
                    Symbol(
                        name=_text(name_node),
                        kind="method",
                        line=child.start_point[0] + 1,
                    )
                )
        elif child.type in ("lexical_declaration", "variable_declaration"):
            _walk_const_fns(child, symbols)


def _walk_const_fns(node, symbols: list[Symbol]) -> None:
    """const foo = () => {} / const foo = function(){} 视为函数。"""
    for declarator in node.named_children:
        if declarator.type != "variable_declarator":
            continue
        value = declarator.child_by_field_name("value")
        if value is not None and value.type in ("arrow_function", "function_expression"):
            name_node = declarator.child_by_field_name("name")
            if name_node is not None:
                symbols.append(
                    Symbol(
                        name=_text(name_node),
                        kind="function",
                        line=declarator.start_point[0] + 1,
                    )
                )


def _collect_declarations(node, symbols: list[Symbol], depth: int = 0) -> None:
    for child in node.named_children:
        t = child.type
        if t == "export_statement":
            # export 内部可能是声明，也可能是 export ... from（无本地符号）
            _collect_declarations(child, symbols, depth + 1)
        elif t == "function_declaration":
            sym = _func_symbol(child)
            if sym:
                symbols.append(sym)
        elif t == "class_declaration":
            _walk_class(child, symbols)
        elif t in ("lexical_declaration", "variable_declaration"):
            _walk_const_fns(child, symbols)


def _collect_import_strings(node, out: list[str]) -> None:
    """递归收集 import/require/export-from 的模块路径。"""
    if node.type == "import_statement":
        source = node.child_by_field_name("source")
        if source is not None:
            out.append("jsimport " + _unquote(source))
        return
    if (
        node.type == "call_expression"
        and node.child_by_field_name("function") is not None
        and _text(node.child_by_field_name("function")) == "require"
    ):
        args = node.child_by_field_name("arguments")
        if args is not None:
            for arg in args.named_children:
                if arg.type == "string":
                    out.append("jsimport " + _unquote(arg))
                    break
        return
    if node.type == "export_statement":
        source = node.child_by_field_name("source")
        if source is not None:
            out.append("jsimport " + _unquote(source))
    for child in node.named_children:
        _collect_import_strings(child, out)


def extract_js(
    language: str, suffix: str, source: bytes
) -> tuple[list[Symbol], list[str]]:
    """解析 JS/TS 文件，返回 (symbols, imports)。"""
    if suffix == ".tsx":
        kind = "tsx"
    elif language == "typescript":
        kind = "ts"
    else:
        kind = "js"
    tree = _parser_for(kind).parse(source)
    root = tree.root_node

    symbols: list[Symbol] = []
    _collect_declarations(root, symbols)
    imports: list[str] = []
    _collect_import_strings(root, imports)
    return symbols, imports
