# CodeGuide — 代码库新人导游

> 对一个陌生仓库运行一条命令，几分钟内生成"新人入职指南"。

CodeGuide 扫描代码仓库，产出结构化画像：语言构成、模块地图、核心符号（类/函数 + docstring）、
内部 import 依赖图、枢纽文件排名。后续版本将接入 LLM 生成分层架构摘要、Mermaid 架构图、
"第一周阅读路线"，并支持针对仓库的 RAG 问答。

## 当前功能（v0.4，第四周里程碑）

- **语言检测**：识别 20+ 种源码文件，自动跳过 `.git`、`node_modules`、`__pycache__` 等无关目录
- **符号提取**：基于 tree-sitter 解析 Python，提取类、函数、方法、docstring、行号（含装饰器与嵌套定义）
- **依赖图**：解析 import 语句（含相对导入），构建文件级有向依赖图；自动识别 src-layout 并剥离 `src/` 前缀
- **枢纽文件**：按被内部依赖次数排序，找出"新人必须先读懂"的核心文件
- **LLM 分层摘要**（v0.2）：文件 → 模块 → 全局三层压缩；5 个/批合并请求；内容哈希缓存零重复计费
- **Mermaid 架构图**（v0.3）：模块级依赖图（跨模块边过少时自动降级为文件级核心图）+ 枢纽文件入边图
- **PageRank 阅读路线**（v0.3）：起步（入口文件）→ 核心（PageRank 最高枢纽）→ 支撑三阶段，
  自实现幂迭代 PageRank，零 numpy 依赖
- **HTML 交互报告**（v0.3）：自包含单文件，含架构图、可搜索符号表、可折叠模块地图、阅读路线；
  `report` 默认纯静态分析免运行，`--llm` 注入摘要
- **仓库问答 RAG**（v0.4 新增）：`codeguide ask`——本地索引（文件概要 + 符号级代码块），
  BM25 词法检索零依赖可用，配置 `CODEGUIDE_EMBED_MODEL` 升级语义检索；
  无 API Key 时降级为检索定位模式，仍然免费
- **发布基建**（v0.4 新增）：GitHub Actions 测试流水线 + PyPI 可信发布流水线，见 [PUBLISH.md](PUBLISH.md)

## 快速开始

```bash
# 安装（开发模式）
pip install -e .

# 1. 免费功能：扫描仓库输出画像
codeguide scan ./some-repo
codeguide scan ./some-repo --json profile.json

# 2. 免费功能：交互式 HTML 报告（架构图 + 阅读路线 + 符号速查）
codeguide report ./some-repo -o report.html

# 3. 仓库问答（索引本地构建；不配 Key 也能用检索定位模式）
codeguide ask ./some-repo SSL 证书验证在哪里处理

# 4. LLM 功能（先配置 API）
set CODEGUIDE_API_KEY=sk-xxx          # Windows；Linux/macOS 用 export
# 可选：CODEGUIDE_BASE_URL（默认 https://api.deepseek.com/v1）
#       CODEGUIDE_MODEL（默认 deepseek-chat）
#       CODEGUIDE_EMBED_MODEL（设置后 ask 升级为语义检索）
codeguide guide ./some-repo -o GUIDE.md      # Markdown 指南
codeguide report ./some-repo --llm           # HTML 报告 + LLM 摘要
codeguide ask ./some-repo 错误处理在哪里统一做的
```

任何 OpenAI 兼容接口（DeepSeek / GLM / Kimi / OpenAI）都可用，
通过 `CODEGUIDE_BASE_URL` + `CODEGUIDE_MODEL` 切换。

## 实测效果

对 [requests](https://github.com/psf/requests) v2.34.2 源码扫描：

- 40 个源码文件 · 13,729 行，35 个 Python 文件解析出 71 个类、632 个函数/方法
- 81 条内部依赖边，识别出的枢纽文件 `compat.py` / `models.py` / `_types.py`
  正是 requests 真实的核心模块 ✓

## 技术路线

| 组件 | 技术 |
|---|---|
| 符号提取 | tree-sitter（Python 优先，接口预留多语言扩展） |
| 依赖图 | networkx |
| CLI | argparse + rich |
| LLM | OpenAI 兼容 API（httpx 直连），base_url 可配置（DeepSeek / GLM / OpenAI） |
| 成本控制 | 文件摘要批量合并请求 + 内容哈希缓存落盘 |
| RAG 检索 | 本地 JSON 索引 + 自实现 BM25 / 可选 API 语义嵌入 |

## 开发计划

- [x] 第 1 周：仓库扫描器 + CLI + 单元测试
- [x] 第 2 周：LLM 分层摘要流水线（文件 → 模块 → 全局），生成 Markdown 指南
- [x] 第 3 周：Mermaid 架构图、PageRank 阅读路线、HTML 交互报告
- [x] 第 4 周：本地 RAG 问答、发布基建（GitHub Actions + PyPI 可信发布）

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/
```
