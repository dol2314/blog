"""워프 글쓰기 공식 (워드프레스 수익형 글).

사용자가 가져온 '워프스킬'의 글쓰기 규칙을 프로그램으로 옮긴 것이다.
  1. 네이버 자동검색어를 2단계까지 모은다 (keywords.py)
  2. 제목 = 메인 키워드(맨 앞) + 연관어, 30~35자, 명사형으로 끝
  3. H2 5~7개, 모두 메인 키워드 포함, 첫 H2 = 메인 키워드
  4. 첫 H2 바로 아래에 CTA 요약 박스(2문단) + 전폭 버튼 + 34px 공백
  5. 자동검색어는 '구문 그대로' 하나도 빠짐없이 → 프로그램이 전수 검사하고 빠진 건 AI가 채운다
  6. 본문 공백 제외 1,800~2,500자, 마지막에 출처·기준일
"""

from __future__ import annotations

import html as html_lib
import re

from . import llm
from .models import Post
from .writer import WriterError

# 버튼 색 (워프스킬 palette.py와 같은 값)
PALETTE = {
    "coral": ("#f0372f", "#d61a12", "선명한 빨강 — 클릭률이 가장 높다 (기본)"),
    "tangelo": ("#ff7a18", "#ee5103", "주황 — 빨강보다 부드럽고 눈에 띈다"),
    "royal": ("#3b6cff", "#1438c4", "파랑 — 금융·공공 주제"),
    "forest": ("#17b86a", "#0a8f4f", "초록 — 건강·환경·생활 주제"),
    "grape": ("#8b5cf6", "#6321d9", "보라 — 교육·IT·뷰티"),
    "rosa": ("#ff4d8d", "#e01a62", "분홍 — 육아·반려·패션"),
    "teal": ("#12b5b0", "#0a8280", "청록 — 여행·레저"),
    "onyx": ("#4a4a4a", "#141414", "검정 — 고급스럽고 차분한 주제"),
}

CSS_TPL = """.entry-content .mk-cta a.mk-go.mk-go.mk-go.mk-go,.mk-cta a.mk-go{{display:flex!important;align-items:center!important;justify-content:center!important;gap:12px!important;width:100%!important;box-sizing:border-box!important;padding:20px 18px!important;background-image:linear-gradient(135deg,{c1} 0%,{c2} 100%)!important;background-size:100% 100%!important;background-position:0 0!important;background-repeat:no-repeat!important;background-color:{c2}!important;color:#fff!important;text-decoration:none!important;border:0!important;font-size:19px!important;font-weight:800!important;letter-spacing:-.4px!important;line-height:1.35!important;text-align:center!important;border-radius:{radius}px!important;box-shadow:0 5px 16px {s33};animation:mkpulse 2.4s ease-in-out infinite;transition:transform .15s ease,box-shadow .15s ease,filter .15s ease}}
.entry-content .mk-cta a.mk-go.mk-go.mk-go.mk-go:hover,.entry-content .mk-cta a.mk-go.mk-go.mk-go.mk-go:focus{{filter:brightness(1.09)!important;transform:translateY(-2px)!important;box-shadow:0 9px 24px {s46}!important;animation:none!important;color:#fff!important}}
.mk-cta .mk-arw{{font-size:22px!important;line-height:1!important;transition:transform .2s ease}}
.entry-content .mk-cta a.mk-go:hover .mk-arw{{transform:translateX(6px)}}
@keyframes mkpulse{{0%,100%{{box-shadow:0 5px 16px {s33}}}50%{{box-shadow:0 5px 24px {s58}}}}}
@media(max-width:600px){{.entry-content .mk-cta a.mk-go.mk-go.mk-go.mk-go,.mk-cta a.mk-go{{padding:17px 13px!important;font-size:17px!important;gap:9px!important}}.mk-cta .mk-arw{{font-size:19px!important}}}}
@media(prefers-reduced-motion:reduce){{.entry-content .mk-cta a.mk-go{{animation:none}}}}
.mk-sum{{border-left:5px solid {c2};background:{tint};padding:17px 19px;margin:0 0 16px;border-radius:0 8px 8px 0}}
.mk-sum p{{margin:0 0 9px;line-height:1.75}}.mk-sum p:last-child{{margin:0}}.mk-sum strong{{color:{c2}}}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "30~35자, 메인 키워드로 시작, 명사형으로 끝"},
        "focus_keyword": {"type": "string", "description": "Rank Math 포커스 키워드 (보통 메인 키워드)"},
        "slug": {"type": "string", "description": "영문 소문자와 하이픈만, 짧게"},
        "intro": {"type": "array", "items": {"type": "string"}, "description": "도입 문단 2~3개 (각 2~3문장)"},
        "cta": {"type": "array", "items": {"type": "string"}, "description": "CTA 박스 문단 2개. <strong>은 문단당 1~2개"},
        "button_text": {"type": "string", "description": "버튼 문구 (예: 내 위약금 바로 확인하기)"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "h2": {"type": "string"},
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["h2", "paragraphs"],
                "additionalProperties": False,
            },
        },
        "source_note": {"type": "string", "description": "출처·기준일 한 문장 (예: 2026년 10월 기준, ○○ 공식 안내)"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "focus_keyword", "slug", "intro", "cta", "button_text", "sections", "source_note", "tags"],
    "additionalProperties": False,
}

SYSTEM = """당신은 워드프레스 애드센스 수익형 블로그 글을 쓰는 한국어 작가입니다. 아래 공식을 그대로 따릅니다.

[제목]
- 메인 키워드를 토씨까지 그대로 맨 앞에 쓰고, 자동검색어에서 연관어 4~6개를 골라 붙입니다.
- 공백 포함 30~35자. 쉼표·괄호로 메인 키워드를 끊지 않습니다.
- '~입니다', '~하나요', '~세요' 같은 서술형으로 끝내지 않고 명사·명사구로 끝냅니다.

[소제목 H2]
- 5~7개. 모든 H2에 메인 키워드를 통째로 넣습니다.
- 첫 H2는 메인 키워드 그 자체(보통 '<메인 키워드> 방법')입니다. '신청 바로가기' 같은 제목을 첫 H2로 쓰지 않습니다.
- 성격이 비슷한 자동검색어 둘은 한 H2에 묶습니다.

[자동검색어 — 가장 중요]
- 주어진 자동검색어는 하나도 빠짐없이, 띄어쓰기까지 '구문 그대로' 제목·H2·본문 어딘가에 들어가야 합니다.
- H2에서 단어 사이에 다른 말이 끼어 구문이 끊기면, 그 섹션 본문 문장의 주어 자리에 구문을 통째로 한 번 더 씁니다.
  예) '정수기 렌탈 해지 철거는 신청할 때 날짜를 직접 고릅니다.'

[CTA — 첫 H2 바로 아래]
- 설명하는 자리가 아니라 버튼을 누르게 만드는 자리입니다. 2문단.
- 1문단: 지금 왜 급한지 + 안 하면 무엇을 손해 보는지 + 핵심 답 한 줄.
- 2문단: 그것이 어디서 해결되는지 + '지금'으로 버튼에 연결.
- 급함의 근거는 확인된 사실로만 만듭니다. 몇 분 단축, 몇 % 절감 같은 수치를 지어내지 않습니다.

[본문]
- 도입 2~3문단, 섹션마다 문단 3개 안팎. 문단은 2~3문장, 평균 60자 이상. 한 줄 문단을 연달아 쓰지 않습니다.
- 본문 전체 공백 제외 1,800~2,500자.
- 각 항목에는 '왜 그런지'와 '안 지키면 생기는 일'을 한 문장씩 씁니다.
- 문단 안에서는 <strong>, <em>만 씁니다. H1, 다른 태그는 쓰지 않습니다.
- 바뀌는 숫자(요금·금리·지급일 등)에는 기준 날짜를 붙이고, 확인하지 못한 절차·수치는 쓰지 말고 '신청 화면에서 확인하세요'로 안내합니다.
- 금융·의료·법률은 '상황에 따라 다르다'를 빼지 않습니다. 승인·수익·효과를 단정하지 않습니다.

[기타]
- slug: 포커스 키워드를 뜻하는 짧은 영문 (소문자, 하이픈). 예: water-purifier-rental-cancel
- source_note: 출처와 기준일 한 문장.
"""

FILL_SYSTEM = """당신은 워드프레스 글 편집자입니다. 빠진 자동검색어를 글에 자연스럽게 넣습니다.
- 빠진 구문마다, 가장 관련 있는 섹션의 문단 하나를 골라 그 구문을 띄어쓰기까지 그대로 문장의 주어 자리에 넣어 고칩니다.
- 구문을 바꾸거나 띄어쓰기를 고치지 않습니다. 따옴표로 감싸지 않습니다.
- 나머지 문장, 소제목, 사실 내용은 그대로 둡니다. 새로운 사실·수치를 추가하지 않습니다.
답은 sections 하나만 가진 JSON으로, 모든 섹션을 원래 순서대로 돌려줍니다.
"""

FILL_SCHEMA = {
    "type": "object",
    "properties": {"sections": SCHEMA["properties"]["sections"]},
    "required": ["sections"],
    "additionalProperties": False,
}


# ---- 글쓰기 ------------------------------------------------------------------------


def build_user_prompt(main: str, keywords: list[str], button_hint: str | None, extra: str | None,
                      style: dict | None, references: str | None, app_info: str | None) -> str:
    lines = [f"메인 키워드: {main}", "자동검색어 (전부 구문 그대로 넣을 것):"]
    lines += [f"- {k}" for k in keywords] or ["- (없음)"]
    if button_hint:
        lines.append(f"버튼이 연결되는 곳: {button_hint}")
    if app_info:
        lines.append(f"관련 앱 공식 설명 (앱 안 메뉴·기능 이름은 여기 적힌 것만 씀):\n{app_info}")
    if extra:
        lines.append(f"추가 요청: {extra}")
    if style and style.get("guide"):
        lines += ["", "[글투 설명서] 말투와 문장 끝맺음만 따르고 내용은 베끼지 마세요.", style["guide"]]
    if references:
        lines += ["", "[참고 자료] 구체적인 사실·수치·날짜는 이 자료에 있는 것만 씁니다.", references[:8000]]
    return "\n".join(lines)


def write(engine: str, main: str, keywords: list[str], button_url: str | None = None,
          button_text: str | None = None, extra: str | None = None, style: dict | None = None,
          references: str | None = None, app_info: str | None = None, color: str = "coral",
          progress=None, max_fill: int = 2) -> tuple[Post, dict]:
    """공식대로 글을 쓰고, 빠진 자동검색어를 채운 뒤 (Post, 공식 정보)를 돌려준다."""
    main = main.strip()
    if not main:
        raise WriterError("메인 키워드를 넣어 주세요.")
    step = progress or (lambda message: None)
    step("워프 공식으로 글을 쓰는 중...")
    data = llm.generate_json(
        engine, SYSTEM,
        build_user_prompt(main, keywords, button_url, extra, style, references, app_info),
        SCHEMA, max_tokens=16000,
    )
    data = normalize(data, main)
    for attempt in range(max_fill):
        missing = missing_keywords(data, keywords)
        if not missing:
            break
        step(f"빠진 자동검색어 {len(missing)}개를 채우는 중... ({attempt + 1}/{max_fill})")
        data["sections"] = fill_missing(engine, data, missing)
    info = {
        "main": main,
        "keywords": keywords,
        "focus_keyword": data["focus_keyword"],
        "slug": data["slug"],
        "button_url": button_url or "",
        "button_text": (button_text or data["button_text"] or f"{main} 바로가기").strip(),
        "color": color if color in PALETTE else "coral",
        "data": data,
    }
    post = Post(title=data["title"], html=assemble(data, info), tags=data["tags"])
    info["checks"] = check(post.title, post.html, info)
    return post, info


def normalize(data: dict, main: str) -> dict:
    sections = []
    for sec in data.get("sections") or []:
        h2 = str(sec.get("h2", "")).strip()
        paras = [p.strip() for p in sec.get("paragraphs") or [] if str(p).strip()]
        if h2 and paras:
            sections.append({"h2": h2, "paragraphs": paras})
    if not sections:
        raise WriterError("AI가 소제목을 만들지 못했습니다. 다시 시도해 주세요.")
    slug = re.sub(r"[^a-z0-9-]+", "-", str(data.get("slug", "")).lower()).strip("-")[:60]
    tags = [str(t).strip().lstrip("#") for t in data.get("tags") or [] if str(t).strip()]
    return {
        "title": str(data.get("title", "")).strip() or main,
        "focus_keyword": str(data.get("focus_keyword", "")).strip() or main,
        "slug": slug,
        "intro": [p.strip() for p in data.get("intro") or [] if str(p).strip()],
        "cta": [p.strip() for p in data.get("cta") or [] if str(p).strip()][:2],
        "button_text": str(data.get("button_text", "")).strip(),
        "sections": sections,
        "source_note": str(data.get("source_note", "")).strip(),
        "tags": list(dict.fromkeys(tags))[:10],
    }


def fill_missing(engine: str, data: dict, missing: list[str]) -> list[dict]:
    import json

    user = "빠진 구문:\n" + "\n".join(f"- {m}" for m in missing) + "\n\n현재 섹션(JSON):\n" + json.dumps(
        {"sections": data["sections"]}, ensure_ascii=False
    )
    out = llm.generate_json(engine, FILL_SYSTEM, user, FILL_SCHEMA, max_tokens=16000)
    fixed = normalize({**data, "sections": out.get("sections") or []}, data["focus_keyword"])["sections"]
    # 소제목 수가 바뀌었으면 AI가 구조를 망친 것 → 원래 것을 유지
    return fixed if len(fixed) == len(data["sections"]) else data["sections"]


# ---- 조립 (구텐베르크 블록) ------------------------------------------------------------


def _inline(text: str) -> str:
    """문단 안에는 strong/em만 남기고 나머지 태그는 글자로 바꾼다."""
    safe = html_lib.escape(re.sub(r"<(?!/?(?:strong|em|b|i)\b)[^>]*>", "", text), quote=False)
    return re.sub(r"&lt;(/?)(strong|em|b|i)&gt;", r"<\1\2>", safe)


def _p(text: str) -> str:
    return f"<!-- wp:paragraph -->\n<p>{_inline(text)}</p>\n<!-- /wp:paragraph -->"


def _h2(text: str) -> str:
    return f'<!-- wp:heading -->\n<h2 class="wp-block-heading">{html_lib.escape(text, quote=False)}</h2>\n<!-- /wp:heading -->'


def _button(url: str, text: str) -> str:
    href = html_lib.escape(url or "#", quote=True)
    return (
        "<!-- wp:html -->\n"
        f'<div class="mk-cta"><a class="mk-go wp-element-button" href="{href}" rel="nofollow noopener">'
        f'<span>{html_lib.escape(text, quote=False)}</span><span class="mk-arw">&#10132;</span></a></div>\n'
        "<!-- /wp:html -->\n"
        '<!-- wp:spacer {"height":"34px"} -->\n<div style="height:34px" aria-hidden="true" class="wp-block-spacer"></div>\n'
        "<!-- /wp:spacer -->"
    )


def css(color: str = "coral", radius: int = 12) -> str:
    c1, c2, _ = PALETTE.get(color, PALETTE["coral"])

    def rgba(h, a):
        r, g, b = (int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r},{g},{b},{a})"

    r, g, b = (int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    tint = "#%02x%02x%02x" % (255 - (255 - r) // 12, 255 - (255 - g) // 12, 255 - (255 - b) // 12)
    return CSS_TPL.format(c1=c1, c2=c2, radius=radius, tint=tint, s33=rgba(c2, .33), s46=rgba(c2, .46), s58=rgba(c2, .58))


def assemble(data: dict, info: dict) -> str:
    blocks = [f"<!-- wp:html -->\n<style>\n{css(info['color'])}\n</style>\n<!-- /wp:html -->"]
    blocks += [_p(p) for p in data["intro"]]
    for i, sec in enumerate(data["sections"]):
        blocks.append(_h2(sec["h2"]))
        if i == 0:
            if data["cta"]:
                inner = "".join(f"<p>{_inline(p)}</p>" for p in data["cta"])
                blocks.append(f'<!-- wp:html -->\n<div class="mk-sum">{inner}</div>\n<!-- /wp:html -->')
            blocks.append(_button(info["button_url"], info["button_text"]))
        blocks += [_p(p) for p in sec["paragraphs"]]
    blocks.append(_button(info["button_url"], info["button_text"]))
    if data["source_note"]:
        blocks.append(_p(f"<em>{data['source_note']}</em>"))
    return "\n\n".join(blocks)


# ---- 검사 ----------------------------------------------------------------------------


def plain(html: str) -> str:
    text = re.sub(r"(?is)<style.*?</style>", " ", html)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def missing_keywords(data: dict, keywords: list[str]) -> list[str]:
    text = _squash(" ".join(
        [data["title"]] + data["intro"] + data["cta"]
        + [s["h2"] for s in data["sections"]] + [p for s in data["sections"] for p in s["paragraphs"]]
    ))
    text = re.sub(r"<[^>]+>", "", text)
    return [k for k in keywords if _squash(k) not in text]


def check(title: str, html: str, info: dict) -> list[dict]:
    """워프 공식 점검표. 각 항목 {name, ok, detail}."""
    text = plain(html)
    h2s = [plain(h) for h in re.findall(r"(?is)<h2[^>]*>(.*?)</h2>", html)]
    main = info["main"]
    focus = info.get("focus_keyword") or main
    paras = [plain(p) for p in re.findall(r"(?is)<p>(.*?)</p>", html)]
    first_para = next((p for p in paras if p), "")
    missing = [k for k in info.get("keywords", []) if _squash(k) not in _squash(f"{title} {text}")]
    body_len = len(re.sub(r"\s", "", text))
    avg = sum(len(p) for p in paras) / len(paras) if paras else 0
    url = info.get("button_url", "")

    items = [
        ("자동검색어 전부 포함", not missing,
         "모두 들어 있음" if not missing else "빠짐: " + ", ".join(missing)),
        ("제목이 메인 키워드로 시작", title.startswith(main), title),
        ("제목 길이 30~35자", 30 <= len(title) <= 35, f"{len(title)}자"),
        ("제목이 명사형으로 끝남", not re.search(r"(니다|나요|세요|어요|아요|해요|까요)[.?!]?$", title), title[-8:]),
        ("첫 H2 = 메인 키워드", bool(h2s) and h2s[0].startswith(main), h2s[0] if h2s else "H2 없음"),
        ("모든 H2에 메인 키워드", bool(h2s) and all(main in h for h in h2s),
         ", ".join(h for h in h2s if main not in h) or f"{len(h2s)}개 모두 포함"),
        ("H2 5~7개", 5 <= len(h2s) <= 7, f"{len(h2s)}개"),
        ("첫 문단에 포커스 키워드", focus in first_para, focus),
        ("본문 1,800~2,500자 (공백 제외)", 1800 <= body_len <= 2500, f"{body_len:,}자"),
        ("문단 평균 60자 이상", avg >= 60, f"평균 {avg:.0f}자"),
        ("H1 없음", not re.search(r"(?i)<h1\b", html), ""),
        ("버튼 링크 있음", bool(url) and url != "#", url or "버튼 링크를 넣어 주세요"),
        ("출처·기준일", bool(re.search(r"기준|출처", text[-200:])), ""),
        ("영문 슬러그", bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", info.get("slug") or "")), info.get("slug") or "없음"),
    ]
    return [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in items]

