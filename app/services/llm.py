from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class LLMCallMeta:
    provider: str
    model_name: str
    status: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    request_preview: str
    response_preview: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class LLMResult:
    text: str
    meta: LLMCallMeta

    @property
    def content(self) -> str:
        return self.text


class LLMClient:
    """DeepSeek chat-completions client with deterministic local fallback."""

    def available(self) -> bool:
        return bool(settings.deepseek_enabled and settings.deepseek_api_key)

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResult:
        fallback = (
            "基于示例知识库与智能体配置生成辅助说明："
            f"{_truncate(user_prompt, 700)}。AI 辅助参考，不替代执业医师诊断、处方或治疗决策。"
        )
        request_preview = _truncate(f"{system_prompt}|{user_prompt}", 1200)

        if not self.available():
            return LLMResult(
                text=fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="fallback_disabled",
                    latency_ms=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    estimated_cost=0.0,
                    request_preview=request_preview,
                    response_preview=_truncate(fallback),
                    error_message="DeepSeek is disabled or API key is missing.",
                ),
            )

        started = time.perf_counter()
        try:
            response_payload = self._post_json(
                "/chat/completions",
                {
                    "model": settings.deepseek_model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            text = response_payload["choices"][0]["message"]["content"].strip()
            usage = response_payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
            return LLMResult(
                text=text or fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="success",
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    estimated_cost=_estimate_cost(prompt_tokens, completion_tokens),
                    request_preview=request_preview,
                    response_preview=_truncate(text or fallback),
                ),
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LLMResult(
                text=fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="fallback_error",
                    latency_ms=latency_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    estimated_cost=0.0,
                    request_preview=request_preview,
                    response_preview=_truncate(fallback),
                    error_message=_truncate(str(exc), 1200),
                ),
            )

    def compose(self, *, agent_name: str, message: str, evidence: list[str], instruction: str) -> LLMResult:
        evidence_text = "；".join(evidence[:3]) or "未检索到充分依据"
        fallback = f"{agent_name}基于示例知识库生成辅助说明：{evidence_text}。{instruction}"
        request_preview = _truncate(f"{agent_name}|{message}|{evidence_text}|{instruction}", 1200)

        if not self.available():
            return LLMResult(
                text=fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="fallback_disabled",
                    latency_ms=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    estimated_cost=0.0,
                    request_preview=request_preview,
                    response_preview=_truncate(fallback),
                    error_message="DeepSeek is disabled or API key is missing.",
                ),
            )

        started = time.perf_counter()
        try:
            payload = self._build_payload(agent_name, message, evidence_text, instruction)
            response_payload = self._post_json("/chat/completions", payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            text = response_payload["choices"][0]["message"]["content"].strip()
            usage = response_payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
            return LLMResult(
                text=text or fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="success",
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    estimated_cost=_estimate_cost(prompt_tokens, completion_tokens),
                    request_preview=request_preview,
                    response_preview=_truncate(text or fallback),
                ),
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LLMResult(
                text=fallback,
                meta=LLMCallMeta(
                    provider="deepseek",
                    model_name=settings.deepseek_model,
                    status="fallback_error",
                    latency_ms=latency_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    estimated_cost=0.0,
                    request_preview=request_preview,
                    response_preview=_truncate(fallback),
                    error_message=_truncate(str(exc), 1200),
                ),
            )

    def _build_payload(self, agent_name: str, message: str, evidence_text: str, instruction: str) -> dict[str, Any]:
        return {
            "model": settings.deepseek_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是口腔医疗智能服务平台的辅助智能体。必须基于给定依据回答，"
                        "不得替代执业医师诊断、处方或治疗决策；涉及急症、处方、影像诊断需提示线下医生复核。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"智能体：{agent_name}\n"
                        f"用户问题：{message}\n"
                        f"检索依据：{evidence_text}\n"
                        f"输出要求：{instruction}\n"
                        "请用中文输出一段简洁、结构化、可溯源的辅助说明。"
                    ),
                },
            ],
        }

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = settings.deepseek_base_url.rstrip("/")
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.deepseek_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {_truncate(body, 800)}") from exc


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        (prompt_tokens / 1_000_000 * settings.llm_input_price_per_1m)
        + (completion_tokens / 1_000_000 * settings.llm_output_price_per_1m),
        8,
    )


def _truncate(text: str, limit: int = 1200) -> str:
    return text if len(text) <= limit else text[:limit] + "..."
