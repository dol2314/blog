"""내 글투 학습(글투 설명서 만들기)과 글 다듬기."""

from __future__ import annotations

import json
import re

from . import llm, web
from .local_ai import parse_post
from .models import Post
from .writer import POST_SCHEMA, WriterError

STYLE_SCHEMA = {
    "type": "object",
    "properties": {
        "guide": {"type": "string", "description": "글투 설명서 (항목별 목록)"},
        "examples": {"type": "array", "items": {"type": "string"}, "description": "글투가 잘 드러나는 문장 3~5개"},
    },
    "required": ["guide", "examples"],
    "additionalProperties": False,
}

ANALYZE_SYSTEM = """당신은 한국어 글쓰기 문체 분석가입니다.
주어진 블로그 글들의 '내용'이 아니라 '글투'를 분석해서,
다른 작가가 이 설명서만 보고도 같은 글투로 새 글을 쓸 수 있게 구체적인 글투 설명서를 만듭니다.

설명서에 들어갈 항목 (각 항목을 '- 항목: 설명' 형식으로, 실제 예를 들어 구체적으로):
- 말투와 문장 끝맺음 (예: "~해요"체, "~습니다"체, 반말, 섞어 쓰는지)
- 문장 길이와 리듬
- 자주 쓰는 표현·접속어·감탄사
- 글을 시작하는 방식
- 소제목을 다는 방식
- 강조 방식 (굵게, 이모지, 기호 등)과 그 빈도
- 독자에게 말을 거는 방식
- 글을 마무리하는 방식
- 피해야 할 것 (이 글투에서 쓰지 않는 표현)

examples에는 원문에서 글투가 잘 드러나는 문장을 그대로 3~5개 고릅니다. 개인정보가 담긴 문장은 고르지 않습니다.
"""

REFINE_SYSTEM = """당신은 한국어 블로그 편집자입니다. 주어진 글을 더 자연스럽게 다듬습니다.

할 일:
- 어색하거나 번역투인 문장, 같은 표현의 반복, 군더더기를 고칩니다.
- 글투 설명서가 있으면 말투와 문장 끝맺음을 그것에 맞춥니다.
- 소제목 구성과 순서, HTML 태그 형식(h2, h3, p, ul, ol, li, strong, em, blockquote)은 유지합니다.

하지 말 것:
- 새로운 사실, 수치, 날짜, 법 조항을 추가하지 않습니다. 있는 정보만 다듬습니다.
- 글을 크게 줄이거나 늘리지 않습니다.
답은 title, html, tags 세 항목을 가진 JSON으로 합니다.
"""


def collect_samples(text: str, fetch=web.fetch_text, max_chars: int = 9000) -> list[str]:
    """붙여넣은 글과 주소(URL)에서 글투 분석용 글을 모은다. 글은 '---' 줄로 나눈다."""
    urls, rest = web.split_urls(text)
    samples = [s.strip() for s in re.split(r"(?m)^\s*-{3,}\s*$", rest) if len(s.strip()) >= 50]
    for url in urls:
        try:
            _, body = fetch(url)
        except web.WebError as exc:
            raise WriterError(str(exc)) from exc
        samples.append(body[:4000])
    total, picked = 0, []
    for sample in samples:
        if total >= max_chars:
            break
        picked.append(sample[: max_chars - total])
        total += len(picked[-1])
    return picked


def analyze(engine: str, text: str, fetch=web.fetch_text) -> dict:
    samples = collect_samples(text, fetch)
    if not samples:
        raise WriterError("분석할 글이 없습니다. 내가 쓴 글을 붙여넣거나 글 주소를 넣어 주세요.")
    joined = "\n\n".join(f"[글 {i + 1}]\n{s}" for i, s in enumerate(samples))
    data = llm.generate_json(engine, ANALYZE_SYSTEM, f"다음 글들의 글투를 분석하세요.\n\n{joined}", STYLE_SCHEMA)
    guide = str(data.get("guide", "")).strip()
    if not guide:
        raise WriterError("글투 분석 결과가 비었습니다. 글을 더 넣어 다시 시도해 주세요.")
    examples = [str(e).strip() for e in data.get("examples", []) if str(e).strip()][:5]
    return {"guide": guide, "examples": examples, "samples": len(samples)}


def refine(engine: str, post: Post, style: dict | None = None) -> Post:
    parts = []
    if style and style.get("guide"):
        parts += ["[글투 설명서]", style["guide"], ""]
    parts += [f"제목: {post.title}", f"태그: {', '.join(post.tags)}", "본문 HTML:", post.html]
    data = llm.generate_json(engine, REFINE_SYSTEM, "\n".join(parts), POST_SCHEMA)
    refined = parse_post(json.dumps(data, ensure_ascii=False))  # 마크다운 → HTML 등 형식 정리
    return Post(title=refined.title or post.title, html=refined.html or post.html, tags=refined.tags or post.tags)
