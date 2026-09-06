"""自包含 HTML 交互报告生成。

单文件输出：Cytoscape.js 交互式依赖图（节点点击 → 文件详情抽屉，
与循环/风险/阅读路线全联动）、d3 风险热点 Treemap、Cmd+K 命令面板
（fuse.js 模糊搜索）、暗色模式、可排序符号表。所有外部库走 CDN 并
带降级保底：CDN 不可用时静态内容（Mermaid 模块图、表格）仍完整可读。
LLM 摘要可选注入（--llm）。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import networkx as nx
from jinja2 import Template

from .diagram import mermaid_module_graph
from .languages import module_group
from .models import RepoProfile
from .risks import repo_risks
from .roadmap import _pagerank, reading_route

PREVIEW_FILES = 8  # 为阅读路线前 N 个文件嵌入代码预览
PREVIEW_LINES = 50
GRAPH_MAX_NODES = 150
GRAPH_MAX_EDGES = 400

TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ name }} · CodeGuide 报告</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.4/dist/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js"></script>
<script src="https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-hierarchy@3.1.2/dist/d3-hierarchy.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github.min.css" id="hljs-light">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css" id="hljs-dark" disabled>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<style>
  :root {
    --bg: #f7f8fa; --card: #ffffff; --text: #1f2937; --muted: #6b7280;
    --accent: #1a56db; --accent-soft: #eff6ff; --border: #e5e7eb;
    --code-bg: #f3f4f6; --header-from: #1e3a8a; --header-to: #1a56db;
    --warn-bg: #fef2f2; --warn-border: #fecaca; --warn-text: #991b1b;
    --shadow: 0 10px 30px rgba(0,0,0,.08);
  }
  html[data-theme="dark"] {
    --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --muted: #94a3b8;
    --accent: #60a5fa; --accent-soft: #1e3a5f; --border: #334155;
    --code-bg: #0b1220; --header-from: #0b1220; --header-to: #1e3a5f;
    --warn-bg: #450a0a; --warn-border: #7f1d1d; --warn-text: #fca5a5;
    --shadow: 0 10px 30px rgba(0,0,0,.4);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; scroll-padding-top: 64px; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    line-height: 1.65; transition: background .25s, color .25s;
  }
  .wrap { max-width: 1140px; margin: 0 auto; padding: 0 24px 64px; }
  header.site {
    background: linear-gradient(135deg, var(--header-from), var(--header-to));
    color: #fff; padding: 34px 0 26px; position: sticky; top: 0; z-index: 40;
    box-shadow: var(--shadow);
  }
  header.site .wrap { padding-bottom: 0; display: flex; flex-wrap: wrap; gap: 6px 24px; align-items: flex-start; }
  .head-main { flex: 1 1 480px; }
  h1 { margin: 0; font-size: 24px; }
  .sub { opacity: .85; font-size: 13px; }
  .chips { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { background: rgba(255,255,255,.15); border-radius: 999px; padding: 3px 12px; font-size: 12.5px; }
  .head-actions { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
  .hbtn { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); color: #fff;
          border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer; }
  .hbtn:hover { background: rgba(255,255,255,.24); }
  .hbtn kbd { font-family: inherit; background: rgba(0,0,0,.25); border-radius: 4px; padding: 0 5px; margin-left: 6px; font-size: 11px; }
  nav.toc { flex-basis: 100%; font-size: 13.5px; margin-top: 4px; }
  nav.toc a { color: #fff; opacity: .82; margin-right: 14px; text-decoration: none; white-space: nowrap; }
  nav.toc a:hover { opacity: 1; text-decoration: underline; }
  section { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
            padding: 22px 26px; margin-top: 20px; }
  h2 { margin: 0 0 12px; font-size: 19px; border-left: 4px solid var(--accent); padding-left: 10px; }
  h3 { font-size: 15.5px; margin: 18px 0 8px; }
  code { background: var(--code-bg); border-radius: 4px; padding: 1px 6px; font-size: 13px;
         font-family: Consolas, "JetBrains Mono", monospace; }
  .muted { color: var(--muted); font-size: 13px; }
  .langbar { display: flex; height: 22px; border-radius: 6px; overflow: hidden; margin: 12px 0; }
  .langbar div { height: 100%; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; margin-bottom: 6px; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
  .diagram { overflow-x: auto; padding: 8px 0; }
  #cy { width: 100%; height: 540px; border: 1px solid var(--border); border-radius: 10px; background: var(--code-bg); }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px; align-items: center; }
  .tbtn { background: var(--code-bg); color: var(--text); border: 1px solid var(--border);
          border-radius: 999px; padding: 4px 14px; font-size: 12.5px; cursor: pointer; }
  .tbtn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  ol.route { list-style: none; margin: 0; padding: 0; counter-reset: step; }
  ol.route li { counter-increment: step; display: flex; gap: 14px; padding: 11px 4px;
                border-bottom: 1px solid var(--border); align-items: flex-start; cursor: pointer; }
  ol.route li:hover { background: var(--accent-soft); border-radius: 8px; }
  ol.route li:last-child { border-bottom: none; }
  ol.route li::before { content: counter(step); flex: 0 0 30px; height: 30px; border-radius: 50%;
    background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 14px; margin-top: 2px; }
  .badge { display: inline-block; font-size: 11px; border-radius: 4px; padding: 1px 8px;
           margin-right: 8px; vertical-align: 1px; }
  .badge.起步 { background: #dcfce7; color: #166534; }
  .badge.核心 { background: #dbeafe; color: #1e40af; }
  .badge.支撑, .badge.文件, .badge.章节 { background: #f3f4f6; color: #374151; }
  .badge.循环 { background: var(--warn-bg); color: var(--warn-text); }
  .badge.风险 { background: #fef3c7; color: #92400e; }
  .badge.class { background: #fef3c7; color: #92400e; }
  .badge.function, .badge.method { background: #e0e7ff; color: #3730a3; }
  html[data-theme="dark"] .badge.起步 { background:#064e3b; color:#a7f3d0; }
  html[data-theme="dark"] .badge.核心 { background:#1e3a5f; color:#bfdbfe; }
  html[data-theme="dark"] .badge.风险 { background:#78350f; color:#fde68a; }
  html[data-theme="dark"] .badge.支撑, html[data-theme="dark"] .badge.文件,
  html[data-theme="dark"] .badge.章节 { background:#334155; color:#cbd5e1; }
  .metrics { color: var(--muted); font-size: 12px; }
  .cycle { background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 6px;
           padding: 8px 14px; margin: 6px 0; font-size: 13px; color: var(--warn-text); cursor: pointer; }
  details { border: 1px solid var(--border); border-radius: 8px; margin: 10px 0; }
  details summary { cursor: pointer; padding: 10px 16px; font-weight: 600; background: var(--code-bg);
                    border-radius: 8px; }
  details[open] summary { border-radius: 8px 8px 0 0; }
  details .body { padding: 12px 18px; }
  .msummary { margin: 0 0 10px; padding: 10px 14px; background: var(--accent-soft); border-left: 3px solid var(--accent);
              border-radius: 4px; font-size: 14px; }
  .frow { padding: 3px 6px; border-radius: 6px; cursor: pointer; font-size: 13.5px; }
  .frow:hover { background: var(--accent-soft); }
  input[type="search"] { width: 100%; padding: 10px 14px; border: 1px solid var(--border);
    border-radius: 8px; font-size: 14px; margin: 8px 0 12px; background: var(--card); color: var(--text); }
  input[type="search"]:focus { outline: 2px solid var(--accent); border-color: transparent; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 8px 10px; background: var(--code-bg); position: sticky; top: 0; cursor: pointer; user-select: none; }
  th .arrow { opacity: .5; font-size: 10px; }
  td { padding: 7px 10px; border-top: 1px solid var(--border); }
  .tbl-wrap { max-height: 480px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
  #treemap svg { width: 100%; height: auto; display: block; }
  #treemap rect.cell { stroke: var(--card); cursor: pointer; }
  #treemap rect.cell:hover { opacity: .85; }
  #treemap text { font-size: 11px; pointer-events: none; fill: #fff; }
  /* 文件详情抽屉 */
  #drawer {
    position: fixed; top: 0; right: -500px; width: min(480px, 94vw); height: 100vh; z-index: 60;
    background: var(--card); border-left: 1px solid var(--border); box-shadow: var(--shadow);
    transition: right .25s ease; overflow-y: auto; padding: 20px 22px 40px;
  }
  #drawer.open { right: 0; }
  #drawer h3 { margin: 4px 0 2px; word-break: break-all; }
  #drawer .close { position: absolute; top: 12px; right: 14px; border: none; background: var(--code-bg);
                   color: var(--text); border-radius: 6px; width: 30px; height: 30px; cursor: pointer; font-size: 15px; }
  #drawer h4 { margin: 18px 0 6px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  #drawer pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
                padding: 12px; font-size: 12px; overflow-x: auto; margin: 6px 0; }
  /* Cmd+K 面板 */
  #palette-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 80; display: none; }
  #palette-overlay.open { display: block; }
  #palette {
    width: min(640px, 92vw); margin: 9vh auto 0; background: var(--card); border: 1px solid var(--border);
    border-radius: 14px; box-shadow: var(--shadow); overflow: hidden;
  }
  #palette input { width: 100%; border: none; border-bottom: 1px solid var(--border); border-radius: 0;
                   padding: 15px 18px; font-size: 15px; background: var(--card); color: var(--text); margin: 0; }
  #palette input:focus { outline: none; }
  #palette-results { max-height: 46vh; overflow-y: auto; }
  #palette-results .item { padding: 9px 18px; cursor: pointer; display: flex; gap: 10px; align-items: baseline; }
  #palette-results .item .badge { flex: 0 0 auto; }
  #palette-results .item.active, #palette-results .item:hover { background: var(--accent-soft); }
  #palette-hint { padding: 6px 18px 10px; font-size: 11.5px; }
  footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 28px; }
  @media print { header.site, .toolbar, #symbol-search, #palette-overlay, #drawer { display: none !important; }
                 section { break-inside: avoid; border: none; } }
</style>
</head>
<body>
<header class="site">
  <div class="wrap">
    <div class="head-main">
      <h1>📦 {{ name }}</h1>
      <div class="sub">CodeGuide 新人导游报告 · 生成于 {{ today }}</div>
      <div class="chips">
        <span class="chip">{{ total_files }} 个源码文件</span>
        <span class="chip">{{ '{:,}'.format(total_lines) }} 行代码</span>
        <span class="chip">{{ lang_count }} 种语言</span>
        <span class="chip">{{ edge_count }} 条内部依赖</span>
        {% if cycle_count %}<span class="chip">⚠ {{ cycle_count }} 组循环依赖</span>{% endif %}
        {% if llm_used %}<span class="chip">✓ 含 LLM 摘要</span>{% else %}<span class="chip">纯静态分析</span>{% endif %}
      </div>
    </div>
    <div class="head-actions">
      <button class="hbtn" id="open-palette">搜索 <kbd>Ctrl K</kbd></button>
      <button class="hbtn" id="theme-toggle" title="切换亮/暗主题">🌓</button>
    </div>
    <nav class="toc">
      <a href="#overview">概览</a><a href="#arch">依赖图</a><a href="#route">阅读路线</a>
      <a href="#cycles">循环依赖</a><a href="#risks">风险热区</a><a href="#treemap">规模地图</a>
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
  <h2>2 · 依赖图</h2>
  <h3>交互式文件依赖图</h3>
  <p class="muted">点击节点打开文件详情抽屉；滚轮缩放，拖拽平移。点击节点后只高亮其邻域。</p>
  <div class="toolbar">
    <span class="muted" style="margin-right:2px">着色</span>
    <button class="tbtn color-mode active" data-mode="risk">风险</button>
    <button class="tbtn color-mode" data-mode="module">模块</button>
    <button class="tbtn color-mode" data-mode="importance">核心度</button>
    <span style="flex:1"></span>
    <button class="tbtn" id="cy-fit">复位视图</button>
  </div>
  <div id="cy"></div>
  <p id="cy-note" class="muted" style="display:none"></p>
  <h3>模块视图（静态）</h3>
  <div class="diagram"><pre class="mermaid">{{ module_graph }}</pre></div>
</section>

<section id="route">
  <h2>3 · 阅读路线（PageRank）</h2>
  {% if route %}
  <p class="muted">起步 = 程序入口；核心 = PageRank 最高的枢纽；支撑 = 其他高影响力文件。按序号顺序读，点击行查看文件详情与代码预览。</p>
  <ol class="route">
    {% for item in route %}
    <li class="linkline" data-file="{{ item.path }}">
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
  <p class="muted">以下 {{ cycles | length }} 组文件互相 import，点击在依赖图中定位。</p>
  {% for cycle in cycles %}
  <div class="cycle" data-cycle="{{ cycle | join('|') }}">🔁 {{ cycle | join(' → ') }} → {{ cycle[0] }}</div>
  {% endfor %}
  {% else %}<p class="muted">✓ 未检测到文件级循环依赖。</p>{% endif %}
</section>

<section id="risks">
  <h2>5 · 风险热区（git 变更 × PageRank）</h2>
  {% if risks %}
  <p class="muted">经常改动 × 被广泛依赖的文件最值得警惕，点击查看详情。</p>
  <table>
    <thead><tr><th>文件</th><th>提交次数</th><th>PageRank</th><th>风险分</th></tr></thead>
    <tbody>
    {% for r in risks %}
      <tr class="linkline" data-file="{{ r.path }}"><td><code>{{ r.path }}</code></td><td>{{ r.commits }}</td>
          <td>{{ '%.4f'|format(r.pagerank) }}</td><td>{{ '%.3f'|format(r.risk) }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="muted">非 git 仓库或暂无提交记录，跳过风险分析。</p>{% endif %}
</section>

<section id="treemap">
  <h2>6 · 代码规模地图（Treemap）</h2>
  <p class="muted">方块面积 = 文件行数，颜色 = 风险分（无 git 数据时为核心度），绿 → 红 = 低 → 高。点击方块查看文件详情。</p>
  <div id="treemap"></div>
</section>

<section id="modules">
  <h2>7 · 模块地图</h2>
  {% for group, files in modules | dictsort %}
  <details {% if loop.first %}open{% endif %}>
    <summary>{{ group }} <span class="muted">（{{ files | length }} 个文件）</span></summary>
    <div class="body">
      {% if module_summaries and group in module_summaries %}<div class="msummary">{{ module_summaries[group] }}</div>{% endif %}
      {% for f in files %}
      <div class="frow linkline" data-file="{{ f.path }}">📐 <code>{{ f.path }}</code>{% if f.lines %} <span class="muted">{{ f.lines }} 行</span>{% endif %}{% if f.summary %} — {{ f.summary }}{% endif %}</div>
      {% endfor %}
    </div>
  </details>
  {% endfor %}
</section>

<section id="symbols">
  <h2>8 · 符号速查</h2>
  <p class="muted">共 {{ symbol_count }} 个类/函数。输入过滤，点击表头排序，点击行打开文件抽屉。</p>
  <input id="symbol-search" type="search" placeholder="如：Engine、models.py、encode…">
  <div class="tbl-wrap">
  <table id="symbol-table">
    <thead><tr>
      <th data-sort="kind">类型 <span class="arrow"></span></th>
      <th data-sort="name">名称 <span class="arrow"></span></th>
      <th data-sort="doc">说明 <span class="arrow"></span></th>
      <th data-sort="path">位置 <span class="arrow"></span></th>
    </tr></thead>
    <tbody></tbody>
  </table>
  </div>
  <p id="sym-count" class="muted"></p>
</section>

<footer>
  由 CodeGuide 生成 · 交互功能需联网加载 CDN 库（Mermaid / Cytoscape / fuse.js / d3 / highlight.js），
  离线时静态内容仍完整 · LLM 摘要可能存在偏差，以源码为准
</footer>
</div>

<!-- 文件详情抽屉 -->
<aside id="drawer">
  <button class="close" id="drawer-close" title="关闭 (Esc)">✕</button>
  <div id="drawer-body"></div>
</aside>

<!-- Cmd+K 面板 -->
<div id="palette-overlay">
  <div id="palette">
    <input id="palette-input" type="text" placeholder="搜索文件、符号、章节…" autocomplete="off">
    <div id="palette-results"></div>
    <div id="palette-hint" class="muted">↑↓ 选择 · Enter 打开 · Esc 关闭</div>
  </div>
</div>

<script>
const REPORT = {{ report_json }};
const SYMBOLS = {{ symbols_json }};

/* ---------- 主题 ---------- */
const hljsLight = document.getElementById("hljs-light");
const hljsDark = document.getElementById("hljs-dark");
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  hljsLight.disabled = (t === "dark");
  hljsDark.disabled = (t !== "dark");
  localStorage.setItem("cg-theme", t);
  renderMermaid();
}
document.getElementById("theme-toggle").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

/* ---------- Mermaid（主题感知重渲染） ---------- */
let mermaidReady = !!window.mermaid;
function renderMermaid() {
  if (!mermaidReady) return;
  const dark = document.documentElement.dataset.theme === "dark";
  document.querySelectorAll("pre.mermaid").forEach(el => {
    if (!el.dataset.src) el.dataset.src = el.textContent;
    el.innerHTML = el.dataset.src;
    el.removeAttribute("data-processed");
  });
  mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "neutral", flowchart: { curve: "basis" } });
  try { mermaid.run({ querySelector: ".mermaid" }); } catch (e) {}
}

/* ---------- 工具 ---------- */
const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const basename = p => p.split("/").pop();
const CYCLE_MEMBERS = new Set((REPORT.cycles || []).flat());

/* ---------- 文件详情抽屉 ---------- */
function openDrawer(path) {
  const f = REPORT.files[path];
  if (!f) return;
  const badges = [];
  if (REPORT.phases[path]) badges.push(`<span class="badge ${REPORT.phases[path]}">${REPORT.phases[path]}</span>`);
  if (CYCLE_MEMBERS.has(path)) badges.push(`<span class="badge 循环">循环依赖</span>`);
  if (REPORT.risk[path] !== undefined) badges.push(`<span class="badge 风险">风险 ${REPORT.risk[path].toFixed(3)}</span>`);
  const list = (arr, empty) => arr && arr.length
    ? arr.map(p => `<div class="frow linkline" data-file="${esc(p)}"><code>${esc(basename(p))}</code> <span class="muted">${esc(p)}</span></div>`).join("")
    : `<div class="muted">${empty}</div>`;
  const preview = REPORT.previews[path];
  let previewHtml = "";
  if (preview) {
    let code = esc(preview);
    if (window.hljs) {
      try { code = hljs.highlight(preview, {language: "python"}).value; }
      catch (e) { try { code = hljs.highlightAuto(preview).value; } catch (e2) {} }
    }
    previewHtml = `<h4>代码预览（前 ${REPORT.previewLines} 行）</h4><pre><code class="hljs">${code}</code></pre>`;
  }
  document.getElementById("drawer-body").innerHTML = `
    <h3><code>${esc(path)}</code></h3>
    <div style="margin:6px 0">${badges.join(" ")}</div>
    <div class="metrics">${esc(f.lang)} · ${f.lines} 行 · 模块 ${esc(f.module || "-")}</div>
    ${f.summary ? `<p style="font-size:14px">${esc(f.summary)}</p>` : ""}
    ${f.doc ? `<p class="muted">${esc(f.doc)}</p>` : ""}
    <h4>它依赖（${(f.deps||[]).length}）</h4>${list(f.deps, "无内部依赖")}
    <h4>被依赖（${(f.dependents||[]).length}）</h4>${list(f.dependents, "没有被其他文件依赖")}
    <h4>符号（${(f.symbols||[]).length}）</h4>
    <div>${(f.symbols||[]).map(s => `<span class="badge ${s.kind}">${s.kind}</span><code>${esc(s.name)}</code> <span class="muted">L${s.line}</span><br>`).join("") || '<span class="muted">无</span>'}</div>
    ${previewHtml}`;
  document.getElementById("drawer").classList.add("open");
  highlightInGraph(path);
}
document.getElementById("drawer-close").addEventListener("click", () => document.getElementById("drawer").classList.remove("open"));

/* 全局委托：任何 data-file 元素 → 抽屉 */
document.addEventListener("click", e => {
  const el = e.target.closest("[data-file]");
  if (el) openDrawer(el.dataset.file);
});

/* ---------- 交互式依赖图 ---------- */
let cy = null;
function graphColor(mode, path) {
  const palette = ["#1a56db","#0ea5e9","#10b981","#f59e0b","#ef4444","#8b5cf6","#14b8a6","#f97316","#6366f1","#84cc16"];
  if (mode === "module") {
    const m = REPORT.files[path] ? REPORT.files[path].module : "(root)";
    return palette[(REPORT.modules.indexOf(m) + palette.length) % palette.length];
  }
  if (mode === "importance") {
    const t = Math.min(1, (REPORT.pagerank[path] || 0) / (REPORT.maxPagerank || 1));
    return `rgb(${Math.round(30 + 40*t)},${Math.round(86 + 80*t)},${Math.round(219 + 21*t)})`;
  }
  const r = REPORT.risk[path];
  if (r === undefined) return "#94a3b8";
  const t = Math.min(1, r);
  return `rgb(${Math.round(16 + 220*t)},${Math.round(185 - 140*t)},${Math.round(129 - 60*t)})`;
}
function initGraph() {
  const container = document.getElementById("cy");
  const note = document.getElementById("cy-note");
  if (!window.cytoscape || !window.cytoscapeDagre) {
    container.style.display = "none";
    note.style.display = "block";
    note.textContent = "（CDN 不可用，交互图未加载——下方静态模块图与各表格仍可使用）";
    return;
  }
  cytoscape.use(cytoscapeDagre);
  const els = [
    ...REPORT.graph.nodes.map(p => ({ data: { id: p, label: basename(p) } })),
    ...REPORT.graph.edges.map(e => ({ data: { id: e[0]+"→"+e[1], source: e[0], target: e[1] } })),
  ];
  cy = cytoscape({
    container, elements: els,
    style: [
      { selector: "node", style: {
          "background-color": "data(color)", label: "data(label)", color: "#fff",
          "font-size": 9, "text-valign": "center", "text-halign": "center",
          width: "data(size)", height: "data(size)", shape: "round-rectangle",
          "text-wrap": "ellipsis", "text-max-width": 90 } },
      { selector: "edge", style: { width: 1, "line-color": "#94a3b8", "target-arrow-color": "#94a3b8",
          "target-arrow-shape": "triangle", opacity: .55, "curve-style": "bezier" } },
      { selector: "node.cycle", style: { "border-width": 3, "border-color": "#ef4444" } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": "#f59e0b" } },
    ],
    layout: { name: "dagre", rankDir: "LR", nodeSep: 12, rankSep: 40, animate: false },
    wheelSensitivity: 0.25,
  });
  const applyColors = mode => {
    cy.nodes().forEach(n => {
      const p = n.id();
      n.data("color", graphColor(mode, p));
      n.data("size", Math.max(18, Math.min(42, 14 + 240 * (REPORT.pagerank[p] || 0))));
      if (CYCLE_MEMBERS.has(p)) n.addClass("cycle");
    });
  };
  applyColors(document.querySelector(".color-mode.active").dataset.mode);
  document.querySelectorAll(".color-mode").forEach(btn => btn.addEventListener("click", () => {
    document.querySelectorAll(".color-mode").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    applyColors(btn.dataset.mode);
  }));
    cy.on("tap", "node", evt => openDrawer(evt.target.id()));
    document.getElementById("cy-fit").addEventListener("click", () => cy.fit(undefined, 30));
    window.cy = cy;  // 暴露实例，便于控制台检查与自动化验证
  if (REPORT.graph.capped) {
    note.style.display = "block";
    note.textContent = `（仓库较大，交互图截断为核心度最高的 ${REPORT.graph.nodes.length} 个节点、${REPORT.graph.edges.length} 条边；完整数据见模块地图与符号速查）`;
  }
}
function highlightInGraph(path) {
  if (!cy) return;
  const node = cy.getElementById(path);
  if (node.empty()) return;
  cy.nodes().forEach(n => n.style("opacity", 0.25));
  cy.edges().forEach(e => e.style("opacity", 0.08));
  const hood = node.closedNeighborhood();
  cy.batch(() => {
    hood.nodes().style("opacity", 1);
    hood.edges().style("opacity", 0.9);
  });
  node.select();
}

/* ---------- 循环依赖联动 ---------- */
document.querySelectorAll(".cycle").forEach(el => el.addEventListener("click", () => {
  if (!cy) return;
  const files = el.dataset.cycle.split("|");
  cy.nodes().forEach(n => n.style("opacity", files.includes(n.id()) ? 1 : 0.15));
  cy.edges().forEach(e => e.style("opacity",
    files.includes(e.source().id()) && files.includes(e.target().id()) ? 0.9 : 0.06));
  cy.fit(cy.nodes().filter(n => files.includes(n.id())), 60);
  document.getElementById("arch").scrollIntoView({ behavior: "smooth" });
}));

/* ---------- Cmd+K 面板 ---------- */
let paletteItems = [], fuse = null, activeIdx = 0;
function buildPalette() {
  paletteItems = [
    ...Object.keys(REPORT.files).map(p => ({ type: "文件", label: p, sub: `${REPORT.files[p].lines} 行`, file: p })),
    ...SYMBOLS.map(s => ({ type: s.kind, label: s.name, sub: `${s.path}:${s.line}`, file: s.path })),
    ...[["概览","#overview"],["依赖图","#arch"],["阅读路线","#route"],["循环依赖","#cycles"],
        ["风险热区","#risks"],["规模地图","#treemap"],["模块地图","#modules"],["符号速查","#symbols"]]
      .map(([label, anchor]) => ({ type: "章节", label, sub: "", anchor })),
  ];
  if (window.Fuse) {
    fuse = new Fuse(paletteItems, { keys: ["label"], threshold: 0.35, ignoreLocation: true });
  }
}
function openPalette() {
  document.getElementById("palette-overlay").classList.add("open");
  const input = document.getElementById("palette-input");
  input.value = ""; renderPalette(""); input.focus();
}
function closePalette() { document.getElementById("palette-overlay").classList.remove("open"); }
function renderPalette(q) {
  const box = document.getElementById("palette-results");
  let items = q
    ? (fuse ? fuse.search(q).map(r => r.item)
            : paletteItems.filter(i => i.label.toLowerCase().includes(q.toLowerCase())))
    : paletteItems.slice(0, 40);
  items = items.slice(0, 14);
  activeIdx = 0;
  box.innerHTML = items.map((it, i) =>
    `<div class="item ${i === 0 ? "active" : ""}" data-idx="${i}"><span class="badge ${it.type}">${it.type}</span><span>${esc(it.label)}</span><span class="muted" style="margin-left:auto">${esc(it.sub || "")}</span></div>`
  ).join("") || `<div class="item"><span class="muted">无匹配</span></div>`;
  box._items = items;
  box.querySelectorAll(".item").forEach(el => el.addEventListener("click", () => chooseItem(box._items[+el.dataset.idx])));
}
function chooseItem(it) {
  if (!it) return;
  closePalette();
  if (it.anchor) document.querySelector(it.anchor).scrollIntoView({ behavior: "smooth" });
  else if (it.file) openDrawer(it.file);
}
document.getElementById("open-palette").addEventListener("click", openPalette);
document.getElementById("palette-input").addEventListener("input", e => renderPalette(e.target.value));
document.getElementById("palette-overlay").addEventListener("click", e => { if (e.target.id === "palette-overlay") closePalette(); });
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
  if (e.key === "Escape") { closePalette(); document.getElementById("drawer").classList.remove("open"); }
  const box = document.getElementById("palette-results");
  if (!document.getElementById("palette-overlay").classList.contains("open") || !box._items) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    activeIdx = Math.min(box._items.length - 1, Math.max(0, activeIdx + (e.key === "ArrowDown" ? 1 : -1)));
    box.querySelectorAll(".item").forEach((el, i) => el.classList.toggle("active", i === activeIdx));
  }
  if (e.key === "Enter") chooseItem(box._items[activeIdx]);
});

/* ---------- 符号表：过滤 + 排序 ---------- */
const MAX_ROWS = 300;
let sortKey = null, sortDir = 1;
function renderSymbols(q) {
  q = (q || "").trim().toLowerCase();
  const matched = [];
  for (const s of SYMBOLS) {
    if (!q || s.name.toLowerCase().includes(q) || s.path.toLowerCase().includes(q)
        || (s.doc || "").toLowerCase().includes(q)) {
      matched.push(s);
      if (matched.length >= MAX_ROWS * 3) break;
    }
  }
  if (sortKey) matched.sort((a, b) => (a[sortKey] > b[sortKey] ? sortDir : a[sortKey] < b[sortKey] ? -sortDir : 0));
  const shown = matched.slice(0, MAX_ROWS);
  document.querySelector("#symbol-table tbody").innerHTML = shown.map(s =>
    `<tr class="linkline" data-file="${esc(s.path)}"><td><span class="badge ${s.kind}">${s.kind}</span></td>` +
    `<td><code>${esc(s.name)}</code></td>` +
    `<td class="muted">${esc(s.doc || "")}</td>` +
    `<td class="muted">${esc(s.path)} :${s.line}</td></tr>`
  ).join("") || `<tr><td colspan="4" class="muted">无匹配结果</td></tr>`;
  document.getElementById("sym-count").textContent = q
    ? `显示 ${shown.length}${matched.length > MAX_ROWS ? "（仅前 " + MAX_ROWS + " 条）" : ""} / ${SYMBOLS.length} 个符号`
    : `共 ${SYMBOLS.length} 个符号${SYMBOLS.length > MAX_ROWS ? "（过滤时最多显示 " + MAX_ROWS + " 条）" : ""}`;
}
document.getElementById("symbol-search").addEventListener("input", e => renderSymbols(e.target.value));
document.querySelectorAll("#symbol-table th").forEach(th => th.addEventListener("click", () => {
  const key = th.dataset.sort;
  if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = 1; }
  document.querySelectorAll("#symbol-table th .arrow").forEach(a => a.textContent = "");
  th.querySelector(".arrow").textContent = sortDir > 0 ? "▲" : "▼";
  renderSymbols(document.getElementById("symbol-search").value);
}));

/* ---------- Treemap ---------- */
function initTreemap() {
  const host = document.getElementById("treemap");
  if (!window.d3 || !d3.treemap) {
    host.innerHTML = `<p class="muted">（CDN 不可用，规模地图未加载）</p>`;
    return;
  }
  const groups = {};
  for (const [p, f] of Object.entries(REPORT.files)) {
    const m = f.module || "(root)";
    (groups[m] = groups[m] || []).push({ path: p, lines: f.lines, risk: REPORT.risk[p], pr: REPORT.pagerank[p] || 0 });
  }
  const root = d3.hierarchy({ children: Object.entries(groups).map(([m, fs]) => ({ name: m, children: fs })) })
    .sum(d => d.lines || 1)
    .sort((a, b) => b.value - a.value);
  const W = Math.max(600, host.clientWidth || 1000), H = 460;
  d3.treemap().size([W, H]).paddingInner(2)(root);
  const maxRisk = Math.max(0.001, ...root.leaves().map(l => l.data.risk || 0));
  const color = d => {
    const t = Math.min(1, (d.data.risk !== undefined ? d.data.risk / maxRisk
                                            : (d.data.pr || 0) / (REPORT.maxPagerank || 1)));
    return `rgb(${Math.round(16 + 220*t)},${Math.round(185 - 140*t)},${Math.round(129 - 60*t)})`;
  };
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  for (const leaf of root.leaves()) {
    if (leaf.x1 - leaf.x0 < 1 || leaf.y1 - leaf.y0 < 1) continue;
    const d = leaf.data;
    const tip = `${d.path} · ${d.lines} 行` + (d.risk !== undefined ? ` · 风险 ${d.risk.toFixed(3)}` : "");
    svg += `<rect class="cell" data-file="${esc(d.path)}" x="${leaf.x0}" y="${leaf.y0}"
      width="${leaf.x1 - leaf.x0}" height="${leaf.y1 - leaf.y0}" rx="3" fill="${color(leaf)}"><title>${esc(tip)}</title></rect>`;
    if (leaf.x1 - leaf.x0 > 46 && leaf.y1 - leaf.y0 > 16) {
      svg += `<text x="${leaf.x0 + 5}" y="${leaf.y0 + 14}">${esc(basename(d.path).slice(0, Math.floor((leaf.x1 - leaf.x0) / 7)))}</text>`;
    }
  }
  svg += `</svg>`;
  host.innerHTML = svg;
  host.querySelectorAll("rect.cell").forEach(el => el.addEventListener("click", () => openDrawer(el.dataset.file)));
}

/* ---------- 启动 ---------- */
(function init() {
  const saved = localStorage.getItem("cg-theme");
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (prefersDark ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  hljsLight.disabled = (theme === "dark");
  hljsDark.disabled = (theme !== "dark");
  renderMermaid();
  initGraph();
  buildPalette();
  renderSymbols("");
  initTreemap();
})();
</script>
</body>
</html>
""")


def _adjacency(profile: RepoProfile):
    deps: dict[str, list[str]] = {}
    dependents: dict[str, list[str]] = {}
    for src, dst, _w in profile.graph_edges:
        deps.setdefault(src, []).append(dst)
        dependents.setdefault(dst, []).append(src)
    return deps, dependents


def render_report(profile: RepoProfile, llm: dict | None = None) -> str:
    """渲染 HTML 报告。llm 可选，键：overview / summaries / module_summaries。"""
    llm = llm or {}
    summaries: dict[str, str] = llm.get("summaries") or {}
    module_summaries: dict[str, str] | None = llm.get("module_summaries")

    risk_result = repo_risks(profile)
    risk_scores = {r["path"]: r["risk"] for r in (risk_result or {}).get("rows", [])}

    route = reading_route(profile)
    phases = {item["path"]: item["phase"] for item in route}

    graph = nx.DiGraph()
    graph.add_nodes_from(profile.graph_nodes)
    for src, dst, w in profile.graph_edges:
        graph.add_edge(src, dst, weight=w)
    pagerank = _pagerank(graph) if profile.graph_nodes else {}
    max_pr = max(pagerank.values(), default=1.0) or 1.0

    deps, dependents = _adjacency(profile)
    module_names = sorted({module_group(f.path) for f in profile.files})

    # 交互图数据（超限截断，UI 提示）
    cycle_members = {p for c in profile.cycles for p in c}
    nodes_sorted = sorted(
        profile.graph_nodes,
        key=lambda n: (n not in cycle_members, -pagerank.get(n, 0.0)),
    )
    graph_nodes = nodes_sorted[:GRAPH_MAX_NODES]
    node_set = set(graph_nodes)
    edges_sorted = sorted(profile.graph_edges, key=lambda e: -e[2])
    graph_edges = [e for e in edges_sorted if e[0] in node_set and e[1] in node_set][
        :GRAPH_MAX_EDGES
    ]

    # 阅读路线文件的代码预览
    previews: dict[str, str] = {}
    for item in route[:PREVIEW_FILES]:
        try:
            text = (Path(profile.root) / item["path"]).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        previews[item["path"]] = "\n".join(text.splitlines()[:PREVIEW_LINES])

    files_meta: dict[str, dict] = {}
    for f in profile.files:
        files_meta[f.path] = {
            "lines": f.lines,
            "lang": f.language,
            "module": module_group(f.path),
            "doc": f.doc,
            "summary": summaries.get(f.path, ""),
            "deps": sorted(set(deps.get(f.path, []))),
            "dependents": sorted(set(dependents.get(f.path, []))),
            "symbols": [{"name": s.name, "kind": s.kind, "line": s.line} for s in f.symbols],
        }

    report_data = {
        "files": files_meta,
        "modules": module_names,
        "pagerank": pagerank,
        "maxPagerank": max_pr,
        "risk": risk_scores,
        "phases": phases,
        "cycles": profile.cycles,
        "previews": previews,
        "previewLines": PREVIEW_LINES,
        "graph": {
            "nodes": graph_nodes,
            "edges": graph_edges,
            "capped": len(graph_nodes) < len(profile.graph_nodes)
            or len(graph_edges) < len(profile.graph_edges),
        },
    }

    # 按模块分组文件（模块地图区块用）
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
        cycle_count=len(profile.cycles),
        llm_used=bool(llm.get("overview")),
        overview=llm.get("overview"),
        langs=langs,
        module_graph=mermaid_module_graph(profile),
        route=route,
        cycles=profile.cycles,
        risks=(risk_result or {}).get("rows", [])[:15],
        modules=modules,
        module_summaries=module_summaries,
        report_json=json.dumps(report_data, ensure_ascii=False),
        symbols_json=json.dumps(symbols, ensure_ascii=False),
        symbol_count=len(symbols),
    )


def write_report(profile: RepoProfile, out: Path, llm: dict | None = None) -> Path:
    out.write_text(render_report(profile, llm), encoding="utf-8")
    return out
