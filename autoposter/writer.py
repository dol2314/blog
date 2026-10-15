"""Claude로 블로그 글(제목, 본문 HTML, 태그)을 쓴다."""

from __future__ import annotations

import json
import os

import anthropic

from .models import Post

DEFAULT_MODEL = os.environ.get("AUTOPOSTER_MODEL", "claude-opus-5-5")

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "검색에 잘 걸리는 글 제목 (60자 이내)"},
        "html": {"type": "string", "description": "본문 HTML"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "태그 5~10개, # 없이"},
    },
    "required": ["title", "html", "tags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 한국어 블로그 글을 쓰는 작가입니다.
독자가 끝까지 읽고 실제로 도움을 얻는 글을 씁니다.

본문 HTML 규칙:
- 사용할 태그: h2, h3, p, ul, ol, li, strong, em, blockquote, br. 그 외 태그, h1, 스타일 속성, 이미지, 스크립트는 쓰지 않습니다.
- 제목은 본문에 다시 쓰지 않습니다.
- 도입 문단, 소제목(h2) 3~5개로 나눈 본문, 짧은 마무리 순서로 씁니다.
- 확실하지 않은 수치, 가격, 날짜는 단정하지 말고 독자가 확인하도록 안내합니다.

사실 규칙:
- 법 조항, 벌점·과태료·세금 금액, 시행일, 통계 수치처럼 틀리면 안 되는 정보는
  '참고 자료'에 있을 때만 구체적으로 씁니다.
- 참고 자료에 없는 정보는 지어내지 말고, "정확한 기준은 관련 기관 누리집에서 확인하세요"처럼 안내합니다.
"""


class WriterError(RuntimeError):
    pass


def build_prompt(
    category: str,
    topic: str | None,
    tone: str,
    length: int,
    extra: str | None,
    style: dict | None = None,
    references: str | None = None,
) -> str:
    lines = [f"블로그 카테고리: {category}"]
    if topic:
        lines.append(f"글 주제/키워드: {topic}")
    else:
        lines.append("글 주제: 이 카테고리 독자가 관심 가질 만한 구체적인 주제를 하나 정해서 쓰세요.")
    if style and style.get("guide"):
        lines.append("말투: 아래 '글투 설명서'를 따릅니다.")
    else:
        lines.append(f"말투: {tone}")
    lines.append(f"분량: 본문 약 {length}자")
    if extra:
        lines.append(f"추가 요청: {extra}")
    if style and style.get("guide"):
        lines += ["", "[글투 설명서] 이 블로그 주인의 글투입니다. 말투와 구성 방식만 따르고, 예시의 내용은 베끼지 마세요.",
                  style["guide"].strip()]
        examples = [e for e in style.get("examples", []) if e.strip()][:4]
        if examples:
            lines += ["글투 예시 문장:"] + [f"- {e.strip()}" for e in examples]
    if references and references.strip():
        lines += ["", "[참고 자료] 구체적인 사실·수치·날짜는 이 자료에 있는 것만 씁니다. 자료와 다르게 쓰지 마세요.",
                  references.strip()[:8000]]
    return "\n".join(lines)


def write_post(
    category: str,
    topic: str | None = None,
    tone: str = "친근한 존댓말",
    length: int = 2000,
    extra: str | None = None,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
    style: dict | None = None,
    references: str | None = None,
) -> Post:
    client = client or anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(category, topic, tone, length, extra, style, references)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": POST_SCHEMA}},
            # 안전 필터가 거절하면 서버가 다른 모델로 자동 재시도한다.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise WriterError("Claude API 키가 올바르지 않습니다. ANTHROPIC_API_KEY를 확인하세요.") from exc
    except anthropic.RateLimitError as exc:
        raise WriterError("Claude API 사용량 한도에 걸렸습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIStatusError as exc:
        raise WriterError(f"Claude API 오류 (HTTP {exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise WriterError("Claude API에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from exc

    if response.stop_reason == "refusal":
        raise WriterError("Claude가 이 주제의 글쓰기를 거절했습니다. 주제를 바꿔 보세요.")
    if response.stop_reason == "max_tokens":
        raise WriterError("글이 너무 길어 중간에 끊겼습니다. 분량을 줄여 다시 시도하세요.")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise WriterError("Claude 응답에 글 내용이 없습니다.")
    data = json.loads(text)
    tags = [t.strip().lstrip("#") for t in data["tags"] if t.strip()]
    return Post(title=data["title"].strip(), html=data["html"].strip(), tags=list(dict.fromkeys(tags)))
