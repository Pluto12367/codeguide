"""JS/TS 符号提取与依赖解析测试。"""

from pathlib import PurePosixPath

from codeguide.deps_graph import (
    build_dependency_graph,
    find_cycles,
    module_name_for,
    resolve_js_import,
)
from codeguide.models import FileInfo
from codeguide.symbols_js import extract_js

JS_SOURCE = b'''
import { fmt } from "./format";
import Renderer from "../ui/renderer";
const legacy = require("./legacy");
import external from "lodash";

export function formatDate(d) { return fmt(d); }

export class Widget {
  render(x) { return x; }
  static make() { return new Widget(); }
}

const helper = (a) => a * 2;
'''

TS_SOURCE = b'''
import { helper } from "./jslib";
export interface Options { flag: boolean; }
export function parse(s: string): number { return helper(s); }
'''


def _fi(path: str, language: str, imports: list[str]) -> FileInfo:
    module_name = module_name_for(PurePosixPath(path)) if language == "python" else None
    return FileInfo(path=path, language=language, lines=10, size_bytes=100,
                    module_name=module_name, imports=imports)


def test_extract_js_symbols():
    symbols, imports = extract_js("javascript", ".js", JS_SOURCE)
    names = {(s.name, s.kind) for s in symbols}
    assert ("formatDate", "function") in names
    assert ("Widget", "class") in names
    assert ("render", "method") in names
    assert ("make", "method") in names
    assert ("helper", "function") in names  # const 箭头函数
    # Widget 类在 formatDate 之后（源码顺序）
    line_fmt = next(s.line for s in symbols if s.name == "formatDate")
    line_widget = next(s.line for s in symbols if s.name == "Widget")
    assert line_fmt < line_widget


def test_extract_js_imports():
    _, imports = extract_js("javascript", ".js", JS_SOURCE)
    jsimports = [i[len("jsimport "):] for i in imports if i.startswith("jsimport ")]
    assert "./format" in jsimports
    assert "../ui/renderer" in jsimports
    assert "./legacy" in jsimports  # require
    assert "lodash" in jsimports  # npm 包也记录，但解析时视为外部


def test_extract_ts():
    symbols, imports = extract_js("typescript", ".ts", TS_SOURCE)
    names = {(s.name, s.kind) for s in symbols}
    assert ("parse", "function") in names
    assert any(i.startswith("jsimport ./jslib") for i in imports)


def test_resolve_js_import():
    path_set = {
        "src/ui/app.js", "src/ui/format.js", "src/ui/lib/legacy.js",
        "src/ui/pkg/index.js",
    }
    assert resolve_js_import("src/ui/app.js", "./format", path_set) == "src/ui/format.js"
    assert resolve_js_import("src/ui/app.js", "./format.js", path_set) == "src/ui/format.js"
    assert resolve_js_import("src/ui/app.js", "./lib/legacy", path_set) == "src/ui/lib/legacy.js"
    assert resolve_js_import("src/ui/app.js", "./pkg", path_set) == "src/ui/pkg/index.js"
    assert resolve_js_import("src/ui/app.js", "lodash", path_set) is None  # 外部包
    assert resolve_js_import("src/ui/app.js", "./missing", path_set) is None


def test_js_dependency_graph():
    files = [
        _fi("src/app.js", "javascript", [
            "jsimport ./core",
            "jsimport lodash",  # 外部包不进图
        ]),
        _fi("src/core.js", "javascript", ["jsimport ./util"]),
        _fi("src/util.js", "javascript", []),
    ]
    nodes, edges = build_dependency_graph(files)
    assert "src/app.js" in nodes and "src/core.js" in nodes
    edges_set = {(u, v) for u, v, _ in edges}
    assert ("src/app.js", "src/core.js") in edges_set
    assert ("src/core.js", "src/util.js") in edges_set


def test_mixed_python_js_graph():
    files = [
        _fi("src/app.js", "javascript", ["jsimport ./api"]),
        _fi("src/api.js", "javascript", []),
        _fi("server/main.py", "python", ["import server.helpers"]),
        _fi("server/helpers.py", "python", []),
    ]
    nodes, edges = build_dependency_graph(files)
    edges_set = {(u, v) for u, v, _ in edges}
    assert ("src/app.js", "src/api.js") in edges_set
    assert any(e[1] == "server/helpers.py" for e in edges)


def test_find_cycles():
    files = [
        _fi("a.py", "python", ["import b"]),
        _fi("b.py", "python", ["import c"]),
        _fi("c.py", "python", ["import a"]),
        _fi("d.py", "python", ["import a"]),
    ]
    # a.py/b.py/c.py 的模块名：单文件顶层模块
    from codeguide.deps_graph import module_name_for
    from pathlib import PurePosixPath

    for f in files:
        f.module_name = module_name_for(PurePosixPath(f.path))
    nodes, edges = build_dependency_graph(files)
    cycles = find_cycles(nodes, edges)
    assert cycles
    cycle_members = {p for c in cycles for p in c}
    assert {"a.py", "b.py", "c.py"} == cycle_members


def test_find_cycles_empty_for_dag():
    files = [
        _fi("a.py", "python", ["import b"]),
        _fi("b.py", "python", []),
    ]
    from codeguide.deps_graph import module_name_for
    from pathlib import PurePosixPath

    for f in files:
        f.module_name = module_name_for(PurePosixPath(f.path))
    nodes, edges = build_dependency_graph(files)
    assert find_cycles(nodes, edges) == []
