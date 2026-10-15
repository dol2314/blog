"""팩트체크: 글의 사실 주장을 정부·공공기관 공개 자료와 비교하고, 틀린 부분을 고친다.

1) AI가 글에서 확인이 필요한 사실 주장(수치, 날짜, 금액, 법·제도 내용)을 뽑는다.
2) 주장마다 정부·공공기관 사이트를 검색해 관련 부분을 읽는다 (사용자가 넣은 참고 자료도 함께).
3) AI가 그 자료만 근거로 맞음 / 틀림 / 확인 불가를 판정한다.
4) 사용자가 원하면 틀린 부분을 고치고, 확인 불가인 단정적 표현은 누그러뜨린 뒤 출처를 붙인다.

AI는 '자료에 근거가 있을 때만' 판정하도록 지시하지만, 자동 판정은 틀릴 수 있다.
그래서 결과마다 근거 출처를 남겨 사용자가 직접 확인할 수 있게 한다.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time

from . import llm, web
from .local_ai import parse_post
from .models import Post
from .writer import POST_SCHEMA, WriterError

MAX_CLAIMS = 6

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "글에 쓰인 사실 주장 (원문에 가깝게)"},
                    "query": {"type": "string", "description": "정부 사이트에서 찾을 검색어 (핵심 낱말 2~6개)"},
                },
                "required": ["claim", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["맞음", "틀림", "확인 불가"]},
        "correct": {"type": "string", "description": "틀림일 때 자료에 근거한 올바른 내용, 아니면 빈 문자열"},
        "reason": {"type": "string", "description": "판정 이유 한두 문장 (자료의 어느 부분 근거인지)"},
        "source_url": {"type": "string", "description": "근거가 된 자료 주소, 없으면 빈 문자열"},
    },
    "required": ["verdict", "correct", "reason", "source_url"],
    "additionalProperties": False,
}

CLAIMS_SYSTEM = """당신은 꼼꼼한 팩트체커입니다.
블로그 글에서 공식 자료로 사실 여부를 확인할 수 있는 '구체적인 사실 주장'만 골라냅니다.
대상: 수치, 날짜·시행일, 금액(벌금·과태료·요금·지원금), 법·제도·규정 내용, 통계, 기관 발표.
제외: 의견, 감상, 일반 상식, 조언, 확인이 필요 없는 문장.
가장 중요한 것부터 최대 6개를 고르고, 각 주장마다 정부 누리집에서 찾을 짧은 검색어를 만듭니다.
확인할 주장이 없으면 빈 목록을 줍니다.
"""

JUDGE_SYSTEM = """당신은 꼼꼼한 팩트체커입니다. 아래 '공식 자료'만 근거로 주장을 판정합니다.
- 맞음: 자료가 주장을 분명히 뒷받침할 때
- 틀림: 자료가 주장과 다른 내용(다른 수치·날짜·조건 등)을 분명히 말할 때. correct에 자료에 근거한 올바른 내용을 씁니다.
- 확인 불가: 자료에 관련 내용이 없거나, 자료만으로는 판단할 수 없을 때
자료에 없는 내용을 당신의 지식으로 추측해서 판정하지 않습니다. 확실하지 않으면 '확인 불가'로 합니다.
자료가 오래된 것으로 보이면 reason에 그 점을 적습니다.
"""

FIX_SYSTEM = """당신은 한국어 블로그 편집자입니다. 팩트체크 결과에 따라 글을 고칩니다.
- '틀림' 항목: 해당 문장을 올바른 내용으로 고칩니다.
- '확인 불가' 항목: 단정적인 수치·날짜·금액을 빼거나 "정확한 기준은 관련 기관 누리집에서 확인하세요"처럼 누그러뜨립니다.
- 나머지 문장, 글투, 소제목 구성, HTML 형식(h2, h3, p, ul, ol, li, strong, em, blockquote)은 그대로 둡니다.
- 팩트체크 결과에 없는 새로운 사실을 추가하지 않습니다.
답은 title, html, tags 세 항목을 가진 JSON으로 합니다.
"""


def _text(html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</(p|h[1-6]|li|blockquote)>", "\n", html)
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def extract_claims(engine: str, post: Post) -> list[dict]:
    data = llm.generate_json(engine, CLAIMS_SYSTEM, f"제목: {post.title}\n\n본문:\n{_text(post.html)}", CLAIMS_SCHEMA)
    claims = []
    for item in data.get("claims", [])[:MAX_CLAIMS]:
        claim, query = str(item.get("claim", "")).strip(), str(item.get("query", "")).strip()
        if claim:
            claims.append({"claim": claim, "query": query or claim[:40]})
    return claims


def gather_evidence(claim: dict, references: list[dict], search=web.search_official, fetch=web.fetch_text) -> list[dict]:
    """주장 하나에 대한 근거 자료 [{title, url, text}]. 참고 자료가 먼저, 그다음 정부 사이트 검색 결과."""
    keywords = re.findall(r"[0-9A-Za-z가-힣]{2,}", f"{claim['claim']} {claim['query']}")
    evidence = []
    for ref in references:
        passage = web.relevant_passages(ref["text"], keywords, 2000)
        if passage:
            evidence.append({"title": ref["title"], "url": ref["url"], "text": passage})
    try:
        found = search(claim["query"])
    except Exception:  # noqa: BLE001 - 검색이 막혀도 참고 자료만으로 판정한다
        found = []
    for item in found:
        try:
            title, text = fetch(item["url"])
        except Exception:  # noqa: BLE001
            continue
        passage = web.relevant_passages(text, keywords, 2500)
        if passage:
            evidence.append({"title": title or item.get("title", ""), "url": item["url"], "text": passage})
        if len(evidence) >= 4:
            break
    return evidence


def judge(engine: str, claim: dict, evidence: list[dict]) -> dict:
    if not evidence:
        return {"verdict": "확인 불가", "correct": "", "reason": "관련된 정부·공공기관 자료를 찾지 못했습니다.", "source_url": ""}
    blocks = [f"[자료 {i + 1}] {e['title']}\n주소: {e['url']}\n{e['text']}" for i, e in enumerate(evidence)]
    user = f"주장: {claim['claim']}\n\n공식 자료:\n\n" + "\n\n".join(blocks)
    data = llm.generate_json(engine, JUDGE_SYSTEM, user, VERDICT_SCHEMA)
    verdict = data.get("verdict") if data.get("verdict") in ("맞음", "틀림", "확인 불가") else "확인 불가"
    urls = {e["url"] for e in evidence}
    source = str(data.get("source_url", "")).strip()
    if source not in urls:  # AI가 자료에 없는 주소를 지어내지 않게
        source = evidence[0]["url"] if verdict != "확인 불가" else ""
    return {
        "verdict": verdict,
        "correct": str(data.get("correct", "")).strip() if verdict == "틀림" else "",
        "reason": str(data.get("reason", "")).strip(),
        "source_url": source,
    }


def load_references(text: str, fetch=web.fetch_text) -> list[dict]:
    """참고 자료 칸의 글과 주소를 근거 자료로 바꾼다."""
    urls, rest = web.split_urls(text or "")
    refs = []
    if rest:
        refs.append({"title": "직접 넣은 참고 자료", "url": "", "text": rest})
    for url in urls:
        try:
            title, body = fetch(url)
        except Exception:  # noqa: BLE001
            continue
        refs.append({"title": title or url, "url": url, "text": body})
    return refs


def run(engine: str, post: Post, references_text: str = "", progress=None,
        search=web.search_official, fetch=web.fetch_text) -> dict:
    def step(message, fraction=None):
        if progress:
            progress(message, fraction)

    step("확인할 사실을 찾는 중...")
    claims = extract_claims(engine, post)
    references = load_references(references_text, fetch)
    results = []
    for i, claim in enumerate(claims):
        step(f"공식 자료 확인 중 ({i + 1}/{len(claims)}): {claim['claim'][:30]}", i / max(1, len(claims)))
        evidence = gather_evidence(claim, references, search, fetch)
        verdict = judge(engine, claim, evidence)
        results.append({**claim, **verdict, "checked": [e["url"] for e in evidence if e["url"]]})
    return {"checked_at": time.time(), "engine": engine, "results": results}


def apply_fixes(engine: str, post: Post, report: dict) -> Post:
    targets = [r for r in report.get("results", []) if r["verdict"] in ("틀림", "확인 불가")]
    if not targets:
        raise WriterError("고칠 항목이 없습니다. (틀림·확인 불가 항목이 없어요)")
    lines = []
    for r in targets:
        line = f"- [{r['verdict']}] {r['claim']}"
        if r["verdict"] == "틀림":
            line += f"\n  올바른 내용: {r['correct']} (근거: {r['source_url']})"
        lines.append(line)
    user = "팩트체크 결과:\n" + "\n".join(lines) + f"\n\n제목: {post.title}\n태그: {', '.join(post.tags)}\n본문 HTML:\n{post.html}"
    data = llm.generate_json(engine, FIX_SYSTEM, user, POST_SCHEMA)
    fixed = parse_post(json.dumps(data, ensure_ascii=False))
    html = add_sources(fixed.html or post.html, report)
    return Post(title=fixed.title or post.title, html=html, tags=fixed.tags or post.tags)


def add_sources(html: str, report: dict) -> str:
    """근거가 된 공식 자료 목록을 글 끝에 붙인다 (이미 있으면 바꿔 끼운다)."""
    urls = []
    for r in report.get("results", []):
        if r.get("source_url") and r["verdict"] in ("맞음", "틀림") and r["source_url"] not in urls:
            urls.append(r["source_url"])
    html = re.sub(r'(?s)\s*<h3 data-sources="1">.*?</ul>', "", html)
    if not urls:
        return html
    items = "".join(f'<li><a href="{html_lib.escape(u)}">{html_lib.escape(u)}</a></li>' for u in urls)
    return f'{html}\n<h3 data-sources="1">참고한 공식 자료</h3>\n<ul>{items}</ul>'
