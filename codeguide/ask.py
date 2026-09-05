"""仓库问答：本地索引检索 + LLM 生成；无 API Key 时降级为定位模式。"""

from __future__ import annotations

from pathlib import Path

from .indexer import build_index, retrieve, retrieve_semantic
from .models import RepoProfile

ANSWER_SYSTEM_PROMPT = (
    "你是代码库导览助手。只根据下面提供的代码上下文回答用户问题，"
    "回答中用 `文件路径:行号` 标注依据；上下文不足以回答时明确说明"
    "“仓库中没有找到相关代码”，不要编造。用中文回答，简洁分点。"
)


def _context_block(hit, summary: str | None) -> str:
    chunk, score = hit
    head = f"[{chunk.path}:{chunk.line}] {chunk.kind} {chunk.name}（相关度 {score:.3f}）"
    if summary:
        head += f"\n文件摘要：{summary}"
    return f"--- {head} ---\n{chunk.text[:1500]}"


def ask(
    profile: RepoProfile,
    question: str,
    client=None,  # LLMClient | None；None 时只做检索定位
    top_k: int = 6,
    progress=None,
) -> dict:
    """回答关于仓库的问题。

    返回 {"answer": str|None, "hits": [...], "index_rebuilt": bool}。
    answer 为 None 表示未配置 LLM，仅返回检索到的位置。
    """
    index, rebuilt = build_index(
        profile, Path(profile.root), client=client, progress=progress
    )

    embed_model = getattr(client, "embed_model", "") if client else ""
    if embed_model and index.vectors:
        hits = retrieve_semantic(index, question, client, top_k)
        mode = "语义"
    else:
        hits = retrieve(index, question, top_k)
        mode = "词法"

    sources = [
        {
            "path": c.path,
            "name": c.name,
            "kind": c.kind,
            "line": c.line,
            "score": round(s, 4),
        }
        for c, s in hits
    ]

    answer = None
    if client is not None:
        summaries = {}
        if progress:
            progress(f"{mode}检索到 {len(hits)} 个片段，生成回答…")
        context = "\n\n".join(
            _context_block(h, summaries.get(h[0].path)) for h in hits
        )
        if not context:
            answer = "仓库中没有找到相关代码。"
        else:
            answer = client.chat(
                ANSWER_SYSTEM_PROMPT,
                f"代码上下文：\n{context}\n\n问题：{question}",
                max_tokens=800,
            )

    return {
        "answer": answer,
        "hits": sources,
        "mode": mode,
        "index_rebuilt": rebuilt,
    }
