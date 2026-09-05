# CodeGuide — 代码库新人导游

> 对一个陌生仓库运行一条命令，几分钟内生成"新人入职指南"。

CodeGuide 扫描代码仓库，产出结构化画像：语言构成、模块地图、核心符号（类/函数 + docstring）、
内部 import 依赖图、枢纽文件排名。后续版本将接入 LLM 生成分层架构摘要、Mermaid 架构图、
"第一周阅读路线"，并支持针对仓库的 RAG 问答。

## 当前功能（v0.6，多语言与深度分析轮）

- **多语言符号提取**（v0.6 新增）：Python 之外新增 JavaScript/TypeScript/TSX——
  function/class 声明、类方法、`const fn = () => {}` 箭头函数；import/require/export-from
  的相对路径解析为仓库内依赖边（npm 包视为外部依赖）。前后端混合仓库可出完整画像
- **循环依赖检测**（v0.6 新增）：文件级 `simple_cycles`，CLI scan 摘要、HTML 报告、
  Markdown 指南三处呈现（requests 上检出 20 组真实循环——`TYPE_CHECKING` 守卫下的互相引用）
- **风险热区**（v0.6 新增）：`codeguide risks` 与报告区块——git 变更频次 × PageRank，
  "经常改动 × 被广泛依赖"的文件排最前，给出补测试优先级；非 git 仓库优雅降级
- **增量索引**（v0.6 新增）：索引格式 v2 按文件内容哈希复用分块与向量，
  改一个文件只重嵌一个文件（嵌入是本地索引的主要耗时）；换嵌入模型自动整体重建
- **语言检测**：识别 20+ 种源码文件，自动跳过 `.git`、`node_modules`、`__pycache__` 等无关目录
- **符号提取**：tree-sitter 解析，类/函数/方法/docstring/行号（含装饰器与嵌套定义）
- **依赖图**：解析 import（Python 含相对导入），构建文件级有向依赖图；自动识别 src-layout
- **枢纽文件**：按被内部依赖次数排序，找出"新人必须先读懂"的核心文件
- **LLM 分层摘要**（v0.2）：文件 → 模块 → 全局三层压缩；批量合并请求；内容哈希缓存零重复计费
- **Mermaid 架构图**（v0.3）：模块级依赖图（单包仓库自动降级为文件级核心图）+ 枢纽文件入边图
- **PageRank 阅读路线**（v0.3）：起步（入口）→ 核心（枢纽）→ 支撑三阶段，自实现幂迭代，零 numpy
- **HTML 交互报告**（v0.3）：自包含单文件：架构图、阅读路线、循环依赖、风险热区、
  可搜索符号表、模块地图；默认纯静态分析免费
- **仓库问答 RAG**（v0.4）：`codeguide ask`，无 API Key 时降级为检索定位模式
- **混合检索 + 本地语义嵌入**（v0.5）：RRF 融合 BM25 与向量；`[local]` 可选依赖
  （fastembed/ONNX，无 torch，离线）
- **检索质量评测**（v0.5）：`codeguide eval` 量化 Recall@1/3/5 与 MRR（见下文评测矩阵）

## 快速开始

```bash
# 安装（开发模式）
pip install -e .

# 1. 免费功能：扫描仓库输出画像
codeguide scan ./some-repo
codeguide scan ./some-repo --json profile.json

# 2. 免费功能：交互式 HTML 报告（架构图 + 阅读路线 + 循环依赖 + 风险热区 + 符号速查）
codeguide report ./some-repo -o report.html

# 2b. 风险热区：git 变更频次 × PageRank（需要目标仓库是 git 仓库）
codeguide risks ./some-repo --since "1 year ago"

# 3. 仓库问答（索引本地构建；不配 Key 也能用检索定位模式）
codeguide ask ./some-repo SSL 证书验证在哪里处理

# 3b. 混合检索（推荐）：安装本地嵌入后完全离线、免费
pip install 'codeguide[local]'
codeguide ask ./some-repo 错误处理在哪里统一做的 --embedder local

# 4. 检索质量评测（黄金问答集 → Recall@k / MRR）
codeguide eval ./some-repo evals/golden_requests.json --retrieval hybrid --embedder local

# 5. LLM 功能（先配置 API）
set CODEGUIDE_API_KEY=sk-xxx          # Windows；Linux/macOS 用 export
# 可选：CODEGUIDE_BASE_URL（默认 https://api.deepseek.com/v1）
#       CODEGUIDE_MODEL（默认 deepseek-chat）
#       CODEGUIDE_EMBED_MODEL（设置后 --embedder api 走 API 嵌入）
codeguide guide ./some-repo -o GUIDE.md      # Markdown 指南
codeguide report ./some-repo --llm           # HTML 报告 + LLM 摘要
```

## 检索质量评测

黄金集：[evals/golden_requests.json](evals/golden_requests.json)，
16 条针对 requests 2.34.2 的人工核实问答（纯检索评测，不涉及 LLM 生成）。
复现：`codeguide eval _demo/requests-2.34.2 evals/golden_requests.json --retrieval <模式> --embedder local`

| 检索模式 | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|
| BM25 词法 | **31.2%** | 31.2% | 31.2% | 0.3408 |
| 语义（bge-small-zh） | 25.0% | 50.0% | 56.2% | 0.3745 |
| **RRF 混合（默认）** | **31.2%** | **56.2%** | **68.8%** | **0.4656** |

结论：两路检索互补性明显——BM25 的 top-1 精度强、深层召回弱，
语义检索反之；RRF 融合后 Recall@5 提升 **2.2 倍**（31.2% → 68.8%），MRR +36.6%。
样本量小（16 题），数字用于方向性验证而非精确声明。

已评测并砍掉的增强项（数据/成本不支持）：cross-encoder 重排序
（fastembed 中文可用模型 1GB，下载/推理成本在当前语料规模下不成比例）、
LLM 查询改写（需真实 API Key 评测，待验证后再考虑加入）。

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
| RAG 检索 | 本地 JSON 索引 + BM25 / 本地 ONNX 语义嵌入（fastembed）/ RRF 混合 |
| 质量评测 | 黄金问答集 + `codeguide eval`（Recall@k / MRR） |

## 开发计划

- [x] 第 1 周：仓库扫描器 + CLI + 单元测试
- [x] 第 2 周：LLM 分层摘要流水线（文件 → 模块 → 全局），生成 Markdown 指南
- [x] 第 3 周：Mermaid 架构图、PageRank 阅读路线、HTML 交互报告
- [x] 第 4 周：本地 RAG 问答、发布基建（GitHub Actions + PyPI 可信发布）
- [x] 优化轮：混合检索（RRF）、本地语义嵌入、检索评测基建（v0.5.0）
- [x] 扩展轮：JS/TS 符号提取、循环依赖检测、git 风险热区、增量索引（v0.6.0）

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/
```
