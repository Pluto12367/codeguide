# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

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
