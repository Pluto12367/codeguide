# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

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
