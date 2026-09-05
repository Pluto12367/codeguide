"""CodeGuide 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__
from .scanner import scan_repo

# legacy_windows=False 绕过 rich 在旧式 Windows 控制台/管道下
# 的渲染崩溃（OSError Errno 22）
console = Console(legacy_windows=False)


def _print_summary(profile) -> None:
    console.print(f"\n[bold cyan]📦 {profile.name}[/] 仓库画像")
    console.print(
        f"   {profile.total_files} 个源码文件 · {profile.total_lines:,} 行代码"
    )

    # 语言构成表
    table = Table(title="语言构成", show_lines=False)
    table.add_column("语言", style="cyan")
    table.add_column("文件数", justify="right")
    table.add_column("行数", justify="right")
    for lang, stat in sorted(
        profile.languages.items(), key=lambda kv: -kv[1]["lines"]
    ):
        table.add_row(lang, str(stat["files"]), f"{stat['lines']:,}")
    console.print(table)

    # 枢纽文件
    if profile.hub_files:
        table = Table(title=f"枢纽文件（被内部引用最多，前 {len(profile.hub_files)}）")
        table.add_column("文件", style="green")
        table.add_column("被依赖次数", justify="right", style="yellow")
        for item in profile.hub_files:
            table.add_row(item["path"], str(item["in_degree"]))
        console.print(table)

    # 符号统计
    py_files = [f for f in profile.files if f.symbols]
    if py_files:
        n_classes = sum(
            1 for f in py_files for s in f.symbols if s.kind == "class"
        )
        n_funcs = sum(
            1 for f in py_files for s in f.symbols if s.kind in ("function", "method")
        )
        console.print(
            f"   符号：{n_classes} 个类 · {n_funcs} 个函数/方法"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codeguide",
        description="CodeGuide — 代码库新人导游：扫描仓库，生成新人入职画像",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描仓库并输出画像")
    scan.add_argument("path", help="仓库根目录路径")
    scan.add_argument(
        "--json",
        dest="json_out",
        help="把完整画像写入指定 JSON 文件（不指定则只打印摘要）",
    )

    guide = sub.add_parser("guide", help="生成 Markdown 新人指南（需 LLM API）")
    guide.add_argument("path", help="仓库根目录路径")
    guide.add_argument("-o", "--out", default="GUIDE.md", help="输出文件路径（默认 GUIDE.md）")
    guide.add_argument("--api-key", default=None, help="覆盖 CODEGUIDE_API_KEY")
    guide.add_argument("--base-url", default=None, help="覆盖 CODEGUIDE_BASE_URL")
    guide.add_argument("--model", default=None, help="覆盖 CODEGUIDE_MODEL")

    report = sub.add_parser("report", help="生成交互式 HTML 报告（默认纯静态分析，--llm 加摘要）")
    report.add_argument("path", help="仓库根目录路径")
    report.add_argument("-o", "--out", default="codeguide-report.html", help="输出文件路径")
    report.add_argument("--llm", action="store_true", help="包含 LLM 摘要（需 API Key）")
    report.add_argument("--api-key", default=None, help="覆盖 CODEGUIDE_API_KEY")
    report.add_argument("--base-url", default=None, help="覆盖 CODEGUIDE_BASE_URL")
    report.add_argument("--model", default=None, help="覆盖 CODEGUIDE_MODEL")

    ask = sub.add_parser("ask", help="针对仓库提问（本地索引检索 + LLM 回答）")
    ask.add_argument("path", help="仓库根目录路径")
    ask.add_argument("question", nargs="+", help="问题，如：错误处理在哪里统一做的？")
    ask.add_argument("-k", "--top-k", type=int, default=6, help="检索片段数（默认 6）")
    ask.add_argument(
        "--retrieval",
        choices=["auto", "bm25", "semantic", "hybrid"],
        default="auto",
        help="检索模式（默认 auto：有嵌入向量则混合，否则词法）",
    )
    ask.add_argument(
        "--embedder",
        default=None,
        help="嵌入后端：local / local:模型名 / api（默认读 CODEGUIDE_EMBED_MODEL）",
    )
    ask.add_argument("--api-key", default=None, help="覆盖 CODEGUIDE_API_KEY")
    ask.add_argument("--base-url", default=None, help="覆盖 CODEGUIDE_BASE_URL")
    ask.add_argument("--model", default=None, help="覆盖 CODEGUIDE_MODEL")

    ev = sub.add_parser("eval", help="在黄金问答集上评测检索质量（Recall@k / MRR）")
    ev.add_argument("path", help="仓库根目录路径")
    ev.add_argument("golden", help="黄金问答集 JSON 路径")
    ev.add_argument(
        "--retrieval",
        choices=["auto", "bm25", "semantic", "hybrid"],
        default="auto",
        help="检索模式（默认 auto）",
    )
    ev.add_argument("--embedder", default=None, help="嵌入后端：local / local:模型名 / api")
    ev.add_argument("--json", dest="json_out", help="把详细结果写入 JSON 文件")
    ev.add_argument(
        "--show-rows", action="store_true", help="逐题打印命中明细"
    )

    args = parser.parse_args(argv)

    if args.command == "scan":
        root = Path(args.path)
        if not root.is_dir():
            console.print(f"[red]错误：{root} 不是目录[/]")
            return 2
        with console.status("正在扫描仓库…"):
            profile = scan_repo(root)

        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            console.print(f"[green]画像已写入 {args.json_out}[/]")

        _print_summary(profile)
        return 0

    if args.command == "guide":
        return _run_guide(args)

    if args.command == "report":
        return _run_report(args)

    if args.command == "ask":
        return _run_ask(args)

    if args.command == "eval":
        return _run_eval(args)

    return 0


def _resolve_embedder(args):
    """按 CLI 参数构造嵌入后端；失败时打印警告并降级为词法。"""
    from .embedders import get_embedder

    if not args.embedder:
        return None
    try:
        client = _make_llm(args) if args.embedder == "api" else None
        return get_embedder(args.embedder, llm_client=client)
    except (ValueError, ImportError) as e:
        console.print(f"[yellow]警告：嵌入后端不可用（{e}），使用词法检索。[/]")
        return None


def _run_ask(args) -> int:
    from .ask import ask
    from .llm import LLMError
    from .scanner import scan_repo

    root = Path(args.path)
    if not root.is_dir():
        console.print(f"[red]错误：{root} 不是目录[/]")
        return 2

    question = " ".join(args.question)
    client = None
    try:
        client = _make_llm(args)
    except LLMError as e:
        console.print(f"[yellow]未配置 LLM（{e}），降级为检索定位模式。[/]")

    embedder = _resolve_embedder(args)
    profile = scan_repo(root)
    try:
        result = ask(
            profile,
            question,
            client=client,
            embedder=embedder,
            mode=args.retrieval,
            top_k=args.top_k,
            progress=lambda m: console.print(f"  [dim]… {m}[/]"),
        )
    except LLMError as e:
        console.print(f"[red]问答失败：{e}[/]")
        return 1

    if result["index_rebuilt"]:
        console.print("[dim]已构建/更新本地索引（.codeguide/index.json）[/]")

    console.print(f"\n[bold cyan]❓ {question}[/]")
    if result["answer"]:
        console.print(f"\n{result['answer']}\n")
    else:
        console.print("\n[dim]（未配置 LLM，以下为最相关的代码位置）[/]\n")

    table = Table(title=f"依据（{result['mode']}检索）")
    table.add_column("位置", style="green")
    table.add_column("符号", style="cyan")
    table.add_column("类型")
    table.add_column("相关度", justify="right", style="yellow")
    for h in result["hits"]:
        table.add_row(f"{h['path']}:{h['line']}", h["name"], h["kind"], f"{h['score']:.3f}")
    console.print(table)
    return 0


def _run_eval(args) -> int:
    import json as _json

    from .evaluate import evaluate_retrieval, load_golden
    from .scanner import scan_repo

    root = Path(args.path)
    if not root.is_dir():
        console.print(f"[red]错误：{root} 不是目录[/]")
        return 2
    golden_path = Path(args.golden)
    if not golden_path.is_file():
        console.print(f"[red]错误：{golden_path} 不是文件[/]")
        return 2

    embedder = _resolve_embedder(args)
    try:
        cases = load_golden(golden_path)
    except ValueError as e:
        console.print(f"[red]黄金集格式错误：{e}[/]")
        return 2

    profile = scan_repo(root)
    console.print(
        f"[dim]评测：{len(cases)} 题 · 模式 {args.retrieval} · "
        f"嵌入 {embedder.model_name if embedder else '无（词法）'}[/]"
    )
    result = evaluate_retrieval(
        profile,
        cases,
        embedder=embedder,
        mode=args.retrieval,
        progress=lambda m: console.print(f"  [dim]… {m}[/]"),
    )

    m = result["metrics"]
    if args.json_out:
        Path(args.json_out).write_text(
            _json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[green]明细已写入 {args.json_out}[/]")

    table = Table(title="检索评测结果")
    table.add_column("指标", style="cyan")
    table.add_column("数值", justify="right", style="yellow")
    table.add_row("题目数", str(m.get("questions", 0)))
    for k in (1, 3, 5):
        if f"recall@{k}" in m:
            table.add_row(f"Recall@{k}", f"{m[f'recall@{k}']:.1%}")
    if "mrr" in m:
        table.add_row("MRR", f"{m['mrr']:.4f}")
    console.print(table)

    if args.show_rows:
        table = Table(title="逐题明细")
        table.add_column("#", justify="right")
        table.add_column("问题", max_width=36)
        table.add_column("排名", justify="right")
        table.add_column("命中", justify="center")
        table.add_column("预期文件", max_width=36)
        for i, r in enumerate(result["rows"], 1):
            table.add_row(
                str(i),
                r["question"][:34],
                str(r["rank"]) if r["rank"] else "-",
                "✓" if r["hit"] else "✗",
                r["expected"][0] if r["expected"] else "",
            )
        console.print(table)
    return 0


def _make_llm(args):
    from .llm import LLMClient, LLMError

    return LLMClient(api_key=args.api_key, base_url=args.base_url, model=args.model)


def _run_guide(args) -> int:
    from .guide import generate_guide
    from .llm import LLMError
    from .scanner import scan_repo
    from .summarizer import Summarizer

    root = Path(args.path)
    if not root.is_dir():
        console.print(f"[red]错误：{root} 不是目录[/]")
        return 2

    try:
        client = _make_llm(args)
    except LLMError as e:
        console.print(f"[red]{e}[/]")
        return 2

    console.print(f"[dim]LLM: {client.model} @ {client.base_url}[/]")
    profile = scan_repo(root)
    summarizer = Summarizer(client, repo_root=root, verbose=True)

    def progress(msg: str) -> None:
        console.print(f"  [dim]… {msg}[/]")

    try:
        text = generate_guide(profile, summarizer, progress)
    except LLMError as e:
        console.print(f"[red]生成失败：{e}[/]")
        console.print("[dim]提示：文件级摘要已缓存，修复配置后重跑不会重复计费。[/]")
        return 1

    Path(args.out).write_text(text, encoding="utf-8")
    console.print(f"[green]✓ 指南已生成：{args.out}[/]")
    return 0


def _run_report(args) -> int:
    from .guide import run_summaries
    from .llm import LLMError
    from .report import write_report
    from .scanner import scan_repo
    from .summarizer import Summarizer

    root = Path(args.path)
    if not root.is_dir():
        console.print(f"[red]错误：{root} 不是目录[/]")
        return 2

    profile = scan_repo(root)

    llm: dict | None = None
    if args.llm:
        try:
            client = _make_llm(args)
        except LLMError as e:
            console.print(f"[yellow]警告：{e} 已跳过 LLM 摘要，仅输出静态分析。[/]")
            client = None
        if client is not None:
            console.print(f"[dim]LLM: {client.model} @ {client.base_url}[/]")
            summarizer = Summarizer(client, repo_root=root)
            try:
                _, summaries, groups, module_summaries, overview = run_summaries(
                    profile, summarizer,
                    progress=lambda m: console.print(f"  [dim]… {m}[/]"),
                )
                llm = {
                    "summaries": summaries,
                    "module_summaries": module_summaries,
                    "overview": overview,
                }
            except LLMError as e:
                console.print(f"[yellow]警告：LLM 摘要失败（{e}），已降级为纯静态分析。[/]")
                llm = None

    out = write_report(profile, Path(args.out), llm)
    console.print(f"[green]✓ 报告已生成：{out.resolve().as_uri()}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
