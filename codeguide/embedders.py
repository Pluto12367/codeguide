"""嵌入后端抽象：API 嵌入与本地 ONNX 嵌入（fastembed）。

统一接口：`embed(texts: list[str]) -> list[list[float]]` 和
`model_name` 属性（用于索引失效判断）。
"""

from __future__ import annotations

import os

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"


class ApiEmbedder:
    """OpenAI 兼容 /embeddings 接口（CODEGUIDE_EMBED_MODEL 配置模型名）。"""

    def __init__(self, llm_client):
        self._client = llm_client
        if not getattr(llm_client, "embed_model", ""):
            raise ValueError(
                "ApiEmbedder 需要设置 CODEGUIDE_EMBED_MODEL 环境变量"
                "（或在 LLMClient 中指定 embed_model）。"
            )

    @property
    def model_name(self) -> str:
        return f"api:{self._client.embed_model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed(texts)


class LocalEmbedder:
    """fastembed 本地嵌入：ONNX 推理，无 torch 依赖，首次运行下载模型后完全离线。"""

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise ImportError(
                "本地嵌入需要安装可选依赖：pip install 'codeguide[local]'"
                "（或 pip install fastembed）"
            ) from e
        self.model_name = f"local:{model_name}"
        self._model = TextEmbedding(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


def get_embedder(spec: str | None, llm_client=None):
    """按字符串 spec 构造嵌入后端。

    - None / "" / "none" -> None（纯 BM25）
    - "api"              -> ApiEmbedder（需要 llm_client 与 CODEGUIDE_EMBED_MODEL）
    - "local"            -> LocalEmbedder 默认模型
    - "local:<model>"    -> LocalEmbedder 指定模型
    """
    spec = (spec or "").strip().lower()
    if spec in ("", "none"):
        return None
    if spec == "api":
        return ApiEmbedder(llm_client)
    if spec == "local":
        return LocalEmbedder()
    if spec.startswith("local:"):
        return LocalEmbedder(spec[len("local:"):])
    raise ValueError(f"未知嵌入后端：{spec}（可选 none / api / local[:模型名]）")


def detect_embedder(llm_client=None, local_embed: bool = False):
    """从环境/标志自动决定嵌入后端（CLI 用）。

    优先级：--local-embed 标志 > CODEGUIDE_EMBED_MODEL 环境变量 > 无。
    """
    if local_embed:
        return LocalEmbedder(
            os.environ.get("CODEGUIDE_EMBED_MODEL", DEFAULT_LOCAL_MODEL)
        )
    if os.environ.get("CODEGUIDE_EMBED_MODEL"):
        return ApiEmbedder(llm_client)
    return None
