"""AI에게 JSON 형식의 답을 받는 공통 도구 (내 PC AI / Claude 공용).

글투 분석, 다듬기, 팩트체크처럼 '정해진 항목을 채운 답'이 필요한 작업이 모두 이걸 쓴다.
엔진 이름은 "local:qwen3:8b" 또는 "claude:claude-sonnet-5-5" 형식이다.
"""

from __future__ import annotations

import json
import re

import requests

from . import local_ai
from .writer import WriterError


def split_engine(engine: str) -> tuple[str, str]:
    kind, _, model = (engine or "").partition(":")
    if kind not in ("local", "claude") or not model:
        raise WriterError(f"알 수 없는 AI 엔진입니다: {engine}")
    return kind, model


def generate_json(engine: str, system: str, user: str, schema: dict, max_tokens: int = 12000) -> dict:
    kind, model = split_engine(engine)
    if kind == "local":
        return _local(model, system, user, schema)
    return _claude(model, system, user, schema, max_tokens)


def _parse(content: str) -> dict:
    content = re.sub(r"(?s)<think>.*?</think>", "", content or "").strip()
    match = re.search(r"(?s)\{.*\}", content)
    if not match:
        raise ValueError("JSON이 없습니다")
    return json.loads(match.group(0))


def _local(model: str, system: str, user: str, schema: dict, attempts: int = 3) -> dict:
    http = local_ai._http(None)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0.4, "num_ctx": 12288},
        "keep_alive": "15m",
    }
    last_error = None
    for _ in range(attempts):
        try:
            resp = http.post(f"{local_ai.OLLAMA_URL}/api/chat", json=body, timeout=1800)
        except requests.RequestException as exc:
            raise WriterError("내 PC AI(Ollama)에 연결하지 못했습니다. Ollama가 실행 중인지 확인하세요.") from exc
        if resp.status_code == 404:
            raise WriterError(f"'{model}' 모델이 없습니다. 먼저 모델을 내려받아 주세요.")
        if resp.status_code != 200:
            raise WriterError(f"내 PC AI 오류 (HTTP {resp.status_code}): {resp.text[:200]}")
        try:
            return _parse(resp.json().get("message", {}).get("content", ""))
        except (ValueError, TypeError) as exc:
            last_error = exc  # 작은 모델은 가끔 형식을 틀린다 → 다시 요청
    raise WriterError(f"내 PC AI가 올바른 형식으로 답하지 못했습니다. 다시 시도해 주세요. ({last_error})")


def _claude(model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise WriterError("Claude API 키가 올바르지 않습니다. 설정에서 키를 확인하세요.") from exc
    except anthropic.RateLimitError as exc:
        raise WriterError("Claude API 사용량 한도에 걸렸습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIStatusError as exc:
        raise WriterError(f"Claude API 오류 (HTTP {exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise WriterError("Claude API에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from exc
    if response.stop_reason == "refusal":
        raise WriterError("Claude가 이 요청을 거절했습니다. 내용을 바꿔 다시 시도해 보세요.")
    if response.stop_reason == "max_tokens":
        raise WriterError("답이 너무 길어 중간에 끊겼습니다. 글을 짧게 나눠 다시 시도해 주세요.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)
