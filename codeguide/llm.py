"""OpenAI 兼容的 LLM 客户端。

通过环境变量配置，兼容 DeepSeek / GLM / OpenAI 等任何
OpenAI Chat Completions 接口：

    CODEGUIDE_API_KEY    必填
    CODEGUIDE_BASE_URL   默认 https://api.deepseek.com/v1
    CODEGUIDE_MODEL      默认 deepseek-chat
    CODEGUIDE_EMBED_MODEL 可选；设置后 RAG 索引启用语义嵌入
"""

from __future__ import annotations

import os
import time

import httpx


class LLMError(RuntimeError):
    pass


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
MAX_RETRIES = 3


class LLMClient:
    """最小化的 Chat Completions 客户端，带指数退避重试。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("CODEGUIDE_API_KEY", "")
        self.base_url = (
            base_url or os.environ.get("CODEGUIDE_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.model = model or os.environ.get("CODEGUIDE_MODEL", DEFAULT_MODEL)
        self.embed_model = (
            embed_model or os.environ.get("CODEGUIDE_EMBED_MODEL", "")
        )
        self.timeout = timeout
        if not self.api_key:
            raise LLMError(
                "未配置 API Key。请设置环境变量 CODEGUIDE_API_KEY"
                "（可选 CODEGUIDE_BASE_URL / CODEGUIDE_MODEL）。"
            )

    def chat(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """发送一次对话，返回助手回复文本。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,  # 摘要任务要稳定
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code in (429, 500, 502, 503, 529):
                    last_error = LLMError(
                        f"服务暂时不可用 HTTP {resp.status_code}：{resp.text[:200]}"
                    )
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    try:
                        return data["choices"][0]["message"]["content"].strip()
                    except (KeyError, IndexError, TypeError) as e:
                        raise LLMError(f"响应格式异常：{data}") from e
            except (httpx.HTTPError, LLMError) as e:
                last_error = e
            time.sleep(2**attempt)
        raise LLMError(f"请求失败（已重试 {MAX_RETRIES} 次）：{last_error}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 /embeddings 接口，返回每段文本的向量。"""
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.embed_model, "input": texts},
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as e:
            raise LLMError(f"嵌入响应格式异常：{data}") from e
