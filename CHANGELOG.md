# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [0.7.0] — 2026-09-06

### 新增（前端交互升级，零构建单文件不变）

- **交互式依赖图**：Cytoscape.js + dagre 分层布局，缩放/平移，
  风险 / 模块 / 核心度三种着色，节点大小 = PageRank，循环成员红框；
  大仓库自动截断为核心节点（上限 150 节点 / 400 边）并提示
- **文件详情抽屉**：点击任意文件元素（图节点、阅读路线、风险表、模块地图、
  符号表）打开——依赖/被依赖列表、符号、阶段与风险徽章、代码预览
  （highlight.js 高亮，阅读路线前 8 个文件各嵌 50 行）；打开时依赖图高亮其邻域
- **Cmd+K 命令面板**：fuse.js 模糊搜索文件/符号/章节，↑↓ 选择、Enter 跳转
- **风险热点 Treemap**：d3-hierarchy squarified treemap，面积 = 行数、
  颜色 = 风险分（无 git 数据退化为核心度），点击方块打开抽屉
- **暗色模式**：跟随系统 + 手动切换 + localStorage 记忆；
  Mermaid 与代码高亮主题随动
- **符号表排序**：表头点击按类型/名称/说明/位置排序，与过滤叠加
- **循环依赖联动**：点击循环条目 → 依赖图聚焦该环并高亮内部边
- CDN 全部降级保底：库加载失败时静态 Mermaid 图与表格仍完整可读

### 修复
- cytoscape-dagre CDN 版本指向不存在的 2.6.0 导致交互图无法初始化（改 2.5.0）

## [0.6.0] — 2026-09-06

### 新增
- **JS/TS 符号提取**：tree-sitter-javascript/typescript 解析
  function/class 声明（含 export 包裹）、类方法、`const fn = () => {}`；
  import/require/export-from 相对路径解析为仓库内依赖边，npm 包视为外部。
  前后端混合仓库可出完整画像与架构图
- **循环依赖检测**：文件级 `simple_cycles`（上限 20 组），呈现于
  `scan` 摘要、HTML 报告、Markdown 指南。实测检出 requests 2.34.2 的
  20 组真实文件级循环（`TYPE_CHECKING` 守卫下的互相引用）
- **风险热区**：新 `codeguide risks <repo>` 命令与报告区块——
  git 变更频次 × PageRank 交叉排序，"常改动 × 被广泛依赖"的文件优先暴露；
  非 git 仓库优雅降级
- **增量索引**：索引格式 v2，按文件内容哈希复用分块与向量——
  改一个文件只重新分块/嵌入一个文件；嵌入模型的更改仍触发整体重建

### 变更
- 依赖新增 tree-sitter-javascript、tree-sitter-typescript
- 索引 JSON 结构改为按文件分组（旧格式自动识别并整体重建）

## [0.5.0] — 2026-09-05

### 新增
- **检索质量评测基建**：`codeguide eval <repo> <golden.json>` 命令，
  指标 Recall@1/3/5 与 MRR，`--json` 明细输出，`--show-rows` 逐题明细；
  黄金问答集 `evals/golden_requests.json`（16 条针对 requests 2.34.2 的
  人工核实问答，评测不依赖 LLM 生成，无 API Key 可跑）
- **混合检索（RRF）**：Reciprocal Rank Fusion 融合 BM25 与向量两路排序，
  `ask`/`eval` 新增 `--retrieval bm25|semantic|hybrid`（默认 auto：有向量即混合）。
  在 requests 黄金集上 Recall@5 从 31.2%（纯 BM25）提升至 **68.8%**，MRR 0.34 → 0.47
- **本地语义嵌入**：可选依赖 `codeguide[local]`（fastembed/ONNX，无 torch），
  `--embedder local` 使用 bge-small-zh-v1.5，首次下载模型后完全离线；
  `embedders.py` 统一 ApiEmbedder / LocalEmbedder 后端抽象
- **分块质量**：方法块名带类名前缀（`Engine.start`），文件头块纳入模块
  docstring（新增 FileInfo.doc，扫描时同步提取）

### 变更
- 索引格式加入嵌入模型标识：更换嵌入模型自动触发重建，避免向量混用
- `build_index` 的 `client` 参数改为 `embedder`（嵌入与对话解耦）

### 已评测并否决
- cross-encoder 重排序：fastembed 0.8 中文可用模型为 bge-reranker-base
  （1.04GB），下载与推理成本在当前语料规模下不成比例，暂缓
- LLM 查询改写：需真实 API Key 评测有效性，验证前不加入

## [0.4.0] — 2026-09-05

### 新增
- `codeguide ask <repo> <问题>`：仓库问答。本地索引（文件概要 + 符号级代码块）
  + BM25 词法检索，配置 `CODEGUIDE_EMBED_MODEL` 时自动升级为语义检索；
  未配置 API Key 时降级为"检索定位"模式，仍可免费使用
- 索引落盘 `.codeguide/index.json`，以全仓库内容哈希判断是否需要重建
- 发布基建：LICENSE、CHANGELOG、GitHub Actions 测试与 PyPI 发布流水线

### 修复
- 中文查询检索不命中：CJK 无分词器时按单字切分
- `HTTPResponse` 等缩写词未被拆分，补充大写缩写边界规则

## [0.3.0] — 2026-09-05

### 新增
- Mermaid 架构图：模块级依赖图（跨模块边过少时自动降级为文件级核心图）
  + 枢纽文件入边图
- PageRank 阅读路线：起步（入口）→ 核心（枢纽）→ 支撑三阶段；
  自实现幂迭代 PageRank，零 numpy 依赖
- `codeguide report`：自包含 HTML 交互报告（架构图、可搜索符号表、
  可折叠模块地图、阅读路线），默认纯静态分析免 API Key
- Markdown 指南接入阅读路线与架构图
- src-layout 仓库自动识别并剥离 `src/` 前缀，修复此类仓库 import 解析

## [0.2.0] — 2026-09-05

### 新增
- LLM 分层摘要流水线：文件 → 模块 → 全局，逐层压缩控制 token
- 文件摘要按 5 个/批合并请求；摘要缓存至 `.codeguide/file_cache.json`
  （内容哈希为 key），重复运行零重复计费
- `codeguide guide`：生成 Markdown 新人指南（概览、核心文件、模块地图、关键类）

## [0.1.0] — 2026-09-05

### 新增
- 仓库扫描器：语言检测、tree-sitter 符号提取（类/函数/方法/docstring/行号）、
  import 依赖图（含相对导入）、枢纽文件排名
- `codeguide scan`：rich 终端摘要 + JSON 画像导出
