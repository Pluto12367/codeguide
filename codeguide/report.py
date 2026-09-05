"""自包含 HTML 交互报告生成。

单文件输出：Mermaid 架构图（CDN 渲染）、PageRank 阅读路线、
可折叠模块地图、可搜索符号表。LLM 摘要可选注入（--llm）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Template

from .diagram import mermaid_hub_graph, mermaid_module_graph
from .languages import module_group
from .models import RepoProfile
from .risks import repo_risks
from .roadmap import reading_route

TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ name }} · CodeGuide 报告</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>
  :root {
    --bg: #f7f8fa; --card: #ffffff; --text: #1f2937; --muted: #6b7280;
    --accent: #1a56db; --border: #e5e7eb; --code-bg: #f3f4f6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    line-height: 1.65;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 0 24px 64px; }
  header { background: linear-gradient(135deg, #1e3a8a, #1a56db); color: #fff; padding: 40px 0 32px; }
  header .wrap { padding-bottom: 0; }
  h1 { margin: 0 0 4px; font-size: 28px; }
  .sub { opacity: .85; font-size: 14px; }
  .chips { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { background: rgba(255,255,255,.15); border-radius: 999px; padding: 4px 14px; font-size: 13px; }
    nav {
      margin: 20px 0 0; font-size: 14px;
    }
    nav a { color: #fff; opacity: .85; margin-right: 16px; text-decoration: none; }
    nav a:hover { opacity: 1; text-decoration: underline; }
    .cycle { background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px;
             padding: 8px 14px; margin: 6px 0; font-size: 13px; color: #991b1b; }
  section { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
            padding: 24px 28px; margin-top: 20px; }
  h2 { margin: 0 0 12px; font-size: 20px; border-left: 4px solid var(--accent); padding-left: 10px; }
  h3 { font-size: 16px; margin: 18px 0 8px; }
  code { background: var(--code-bg); border-radius: 4px; padding: 1px 6px; font-size: 13px;
         font-family: Consolas, "JetBrains Mono", monospace; }
  .muted { color: var(--muted); font-size: 13px; }
  .langbar { display: flex; height: 22px; border-radius: 6px; overflow: hidden; margin: 12px 0; }
  .langbar div { height: 100%; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; margin-bottom: 6px; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
  .diagram { overflow-x: auto; padding: 8px 0; }
  ol.route { list-style: none; margin: 0; padding: 0; counter-reset: step; }
  ol.route li { counter-increment: step; display: flex; gap: 14px; padding: 12px 4px;
                border-bottom: 1px solid var(--border); align-items: flex-start; }
  ol.route li:last-child { border-bottom: none; }
  ol.route li::before { content: counter(step); flex: 0 0 30px; height: 30px; border-radius: 50%;
    background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 14px; margin-top: 2px; }
  .badge { display: inline-block; font-size: 11px; border-radius: 4px; padding: 1px 8px;
           margin-right: 8px; vertical-align: 1px; }
  .badge.起步 { background: #dcfce7; color: #166534; }
  .badge.核心 { background: #dbeafe; color: #1e40af; }
  .badge.支撑 { background: #f3f4f6; color: #374151; }
  .badge.class { background: #fef3c7; color: #92400e; }
  .badge.function, .badge.method { background: #e0e7ff; color: #3730a3; }
  .metrics { color: var(--muted); font-size: 12px; }
  details { border: 1px solid var(--border); border-radius: 8px; margin: 10px 0; }
  details summary { cursor: pointer; padding: 10px 16px; font-weight: 600; background: var(--code-bg);
                    border-radius: 8px; }
  details[open] summary { border-radius: 8px 8px 0 0; }
  details .body { padding: 12px 18px; }
  .msummary { margin: 0 0 10px; padding: 10px 14px; background: #eff6ff; border-left: 3px solid var(--accent);
              border-radius: 4px; font-size: 14px; }
  input#symbol-search { width: 100%; padding: 10px 14px; border: 1px solid var(--border);
    border-radius: 8px; font-size: 14px; margin: 8px 0 12px; }
  input#symbol-search:focus { outline: 2px solid var(--accent); border-color: transparent; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 8px 10px; background: var(--code-bg); position: sticky; top: 0; }
  td { padding: 7px 10px; border-top: 1px solid var(--border); }
  .tbl-wrap { max-height: 480px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
  footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 28px; }
  @media print { nav, #symbol-search { display: none; } section { break-inside: avoid; } }
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>📦 {{ name }}</h1>
    <div class="sub">CodeGuide 新人导游报告 · 生成于 {{ today }}</div>
    <div class="chips">
      <span class="chip">{{ total_files }} 个源码文件</span>
      <span class="chip">{{ '{:,}'.format(total_lines) }} 行代码</span>
      <span class="chip">{{ lang_count }} 种语言</span>
      <span class="chip">{{ edge_count }} 条内部依赖</span>
      {% if llm_used %}<span class="chip">✓ 含 LLM 摘要</span>{% else %}<span class="chip">纯静态分析</span>{% endif %}
    </div>
    <nav>
      <a href="#overview">概览</a><a href="#arch">架构图</a><a href="#route">阅读路线</a>
      <a href="#cycles">循环依赖</a><a href="#risks">风险热区</a>
      <a href="#modules">模块地图</a><a href="#symbols">符号速查</a>
    </nav>
  </div>
</header>
<div class="wrap">

<section id="overview">
  <h2>1 · 项目概览</h2>
  {% if overview %}<p>{{ overview }}</p>{% endif %}
  <div class="legend">
    {% for lang, stat in langs %}<span><span class="dot" style="background: {{ loop.cycle('#1a56db','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6') }}"></span>{{ lang }} · {{ stat.lines }} 行 / {{ stat.files }} 文件</span>{% endfor %}
  </div>
  <div class="langbar">
    {% for lang, stat in langs %}<div style="width: {{ (stat.lines / total_lines * 100) | round(2) }}%; background: {{ loop.cycle('#1a56db','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6') }}" title="{{ lang }}"></div>{% endfor %}
  </div>
</section>

<section id="arch">
  <h2>2 · 架构图</h2>
  <h3>模块间依赖</h3>
  <div class="diagram"><pre class="mermaid">{{ module_graph }}</pre></div>
  <h3>核心文件依赖（被依赖最多的 {{ hub_top }} 个文件）</h3>
  <div class="diagram"><pre class="mermaid">{{ hub_graph }}</pre></div>
</section>

<section id="route">
  <h2>3 · 阅读路线（PageRank）</h2>
  {% if route %}
  <p class="muted">起步 = 程序入口；核心 = PageRank 最高的枢纽；支撑 = 其他高影响力文件。按序号顺序读。</p>
  <ol class="route">
    {% for item in route %}
    <li>
      <div>
        <div><span class="badge {{ item.phase }}">{{ item.phase }}</span><code>{{ item.path }}</code></div>
        <div>{{ item.reason }}</div>
        <div class="metrics">出度 {{ item.out_degree }} · 入度 {{ item.in_degree }} · PageRank {{ '%.4f'|format(item.pagerank) }}</div>
      </div>
    </li>
    {% endfor %}
  </ol>
  {% else %}<p class="muted">未检测到内部依赖，无法生成路线。</p>{% endif %}
</section>

<section id="cycles">
  <h2>4 · 循环依赖</h2>
  {% if cycles %}
  <p class="muted">以下 {{ cycles | length }} 组文件互相 import（每组内按路径排序）。循环依赖通常意味着职责划分需要调整，改动其中任何一个都要回归整组。</p>
  {% for cycle in cycles %}
  <div class="cycle">🔁 {{ cycle | join(' → ') }} → {{ cycle[0] }}</div>
  {% endfor %}
  {% else %}<p class="muted">✓ 未检测到文件级循环依赖。</p>{% endif %}
</section>

<section id="risks">
  <h2>5 · 风险热区（git 变更 × PageRank）</h2>
  {% if risks %}
  <p class="muted">经常改动 × 被广泛依赖的文件最值得警惕，建议优先补测试。</p>
  <table>
    <thead><tr><th>文件</th><th>提交次数</th><th>PageRank</th><th>风险分</th></tr></thead>
    <tbody>
    {% for r in risks %}
      <tr><td><code>{{ r.path }}</code></td><td>{{ r.commits }}</td>
          <td>{{ '%.4f'|format(r.pagerank) }}</td><td>{{ '%.3f'|format(r.risk) }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="muted">非 git 仓库或暂无提交记录，跳过风险分析。</p>{% endif %}
</section>

<section id="modules">
  <h2>6 · 模块地图</h2>
  {% for group, files in modules | dictsort %}
  <details {% if loop.first %}open{% endif %}>
    <summary>{{ group }} <span class="muted">（{{ files | length }} 个文件）</span></summary>
    <div class="body">
      {% if module_summaries and group in module_summaries %}<div class="msummary">{{ module_summaries[group] }}</div>{% endif %}
      {% for f in files %}
      <div>📐 <code>{{ f.path }}</code>{% if f.lines %} <span class="muted">{{ f.lines }} 行</span>{% endif %}{% if f.summary %} — {{ f.summary }}{% endif %}</div>
      {% endfor %}
    </div>
  </details>
  {% endfor %}
</section>

<section id="symbols">
  <h2>7 · 符号速查</h2>
  <p class="muted">共 {{ symbol_count }} 个类/函数。输入名称、路径或 docstring 关键词过滤。</p>
  <input id="symbol-search" type="search" placeholder="如：Engine、models.py、encode…" autofocus>
  <div class="tbl-wrap">
  <table id="symbol-table">
    <thead><tr><th>类型</th><th>名称</th><th>说明</th><th>位置</th></tr></thead>
    <tbody></tbody>
  </table>
  </div>
  <p id="sym-count" class="muted"></p>
</section>

<footer>
  由 CodeGuide 生成 · 架构图需联网加载 Mermaid.js · LLM 摘要可能存在偏差，以源码为准
</footer>
</div>

<script>
  mermaid.initialize({ startOnLoad: true, theme: "neutral", flowchart: { curve: "basis" } });

  const SYMBOLS = {{ symbols_json }};
  const tbody = document.querySelector("#symbol-table tbody");
  const counter = document.getElementById("sym-count");
  const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  const MAX_ROWS = 300;

  function render(q) {
    q = q.trim().toLowerCase();
    const matched = [];
    for (const s of SYMBOLS) {
      if (!q || s.name.toLowerCase().includes(q) || s.path.toLowerCase().includes(q)
          || (s.doc || "").toLowerCase().includes(q)) {
        matched.push(s);
        if (matched.length >= MAX_ROWS) break;
      }
    }
    tbody.innerHTML = matched.map(s =>
      `<tr><td><span class="badge ${s.kind}">${s.kind}</span></td>` +
      `<td><code>${esc(s.name)}</code></td>` +
      `<td class="muted">${esc(s.doc || "")}</td>` +
      `<td class="muted">${esc(s.path)} :${s.line}</td></tr>`
    ).join("") || `<tr><td colspan="4" class="muted">无匹配结果</td></tr>`;
    counter.textContent = q
      ? `显示 ${matched.length}${matched.length >= MAX_ROWS ? "+" : ""} / ${SYMBOLS.length} 个符号`
      : `共 ${SYMBOLS.length} 个符号${SYMBOLS.length > MAX_ROWS ? "（搜索时最多显示 " + MAX_ROWS + " 条）" : ""}`;
  }
  document.getElementById("symbol-search").addEventListener("input", e => render(e.target.value));
  render("");
</script>
</body>
</html>
""")


def render_report(profile: RepoProfile, llm: dict | None = None) -> str:
    """渲染 HTML 报告。llm 可选，键：overview / summaries / module_summaries。"""
    llm = llm or {}
    summaries: dict[str, str] = llm.get("summaries") or {}
    module_summaries: dict[str, str] | None = llm.get("module_summaries")

    risk_result = repo_risks(profile)

    # 按模块分组文件
    modules: dict[str, list[dict]] = {}
    for f in sorted(profile.files, key=lambda x: x.path):
        modules.setdefault(module_group(f.path), []).append({
            "path": f.path,
            "lines": f.lines if f.language == "python" else 0,
            "summary": summaries.get(f.path, ""),
        })

    symbols = [
        {"path": f.path, "name": s.name, "kind": s.kind, "line": s.line, "doc": s.doc}
        for f in profile.files
        for s in f.symbols
    ]

    langs = sorted(profile.languages.items(), key=lambda kv: -kv[1]["lines"])

    return TEMPLATE.render(
        name=profile.name,
        today=date.today().isoformat(),
        total_files=profile.total_files,
        total_lines=profile.total_lines,
        lang_count=len(profile.languages),
        edge_count=len(profile.graph_edges),
        llm_used=bool(llm.get("overview")),
        overview=llm.get("overview"),
        langs=langs,
        module_graph=mermaid_module_graph(profile),
        hub_graph=mermaid_hub_graph(profile),
        hub_top=min(8, len(profile.hub_files)) or 8,
        route=reading_route(profile),
        cycles=profile.cycles,
        risks=(risk_result or {}).get("rows", [])[:15],
        modules=modules,
        module_summaries=module_summaries,
        symbols_json=__import__("json").dumps(symbols, ensure_ascii=False),
        symbol_count=len(symbols),
    )


def write_report(profile: RepoProfile, out: Path, llm: dict | None = None) -> Path:
    out.write_text(render_report(profile, llm), encoding="utf-8")
    return out
