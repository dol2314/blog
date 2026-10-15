from types import SimpleNamespace

import pytest

from autoposter import formula, keywords, llm
from autoposter.writer import WriterError

MAIN = "정수기 렌탈 해지"
KWS = ["정수기 렌탈 해지 방법", "정수기 렌탈 해지 위약금", "정수기렌탈 해지 철거", "정수기 렌탈 해지 시간"]


def para(text, n=70):
    return (text + " ") + "가" * max(0, n - len(text))


def answer(missing_time=True):
    sections = [
        {"h2": f"{MAIN} 방법", "paragraphs": [para(f"{MAIN} 방법은 앱에서 시작합니다."), para("두 번째 문단입니다."), para("세 번째.")]},
        {"h2": f"{MAIN} 위약금과 산정 기준", "paragraphs": [para(f"{MAIN} 위약금은 남은 약정에 따라 다릅니다.")] * 3},
        {"h2": f"{MAIN} 철거 예약과 방문 시간", "paragraphs": [para("정수기렌탈 해지 철거는 날짜를 고릅니다.")] * 3},
        {"h2": f"{MAIN} 당일 처리", "paragraphs": [para("당일 처리 여부는 신청 화면에서 확인하세요.")] * 3},
        {"h2": f"{MAIN} 환불과 정산", "paragraphs": [para("정산은 다음 달에 반영됩니다.")] * 3},
    ]
    if not missing_time:
        sections[2]["paragraphs"][0] = para(f"{MAIN} 시간은 기사 방문 일정에 묶입니다.")
    return {
        "title": f"{MAIN} 방법 위약금 수수료 철거 환불 총정리",
        "focus_keyword": MAIN, "slug": "Water Purifier_Rental cancel!",
        "intro": [para(f"{MAIN}를 생각 중이라면 먼저 위약금을 봐야 합니다.")],
        "cta": ["약정이 남았다면 <strong>위약금</strong>이 한 번에 청구됩니다.", "지금 앱에서 금액부터 확인하세요."],
        "button_text": "내 위약금 바로 확인하기", "sections": sections,
        "source_note": "2026년 10월 기준, 각 렌탈사 공식 안내", "tags": ["#정수기", "렌탈"],
    }


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, engine, system, user, schema, max_tokens=12000):
        self.calls.append(SimpleNamespace(system=system, user=user, schema=schema))
        return self.answers.pop(0)


def test_collect_two_levels_and_keeps_spacing():
    table = {
        MAIN: ["정수기 렌탈 해지 방법", "정수기렌탈 해지 철거"],
        "정수기 렌탈 해지 방법 ": ["정수기 렌탈 해지 방법", "정수기 렌탈 해지 시간"],
        "정수기렌탈 해지 철거 ": [],
    }
    found = keywords.collect(MAIN, fetch=lambda q: table.get(q, []), sleep=lambda s: None)
    assert found == ["정수기 렌탈 해지 방법", "정수기렌탈 해지 철거", "정수기 렌탈 해지 시간"]
    with pytest.raises(keywords.KeywordError):
        keywords.collect("  ")


def test_autocomplete_parses_naver_format():
    class Resp:
        def json(self):
            return {"items": [[["정수기 렌탈 해지 방법", "0"], ["정수기렌탈 해지", "0"]], []]}

    http = SimpleNamespace(get=lambda *a, **k: Resp())
    assert keywords.autocomplete(MAIN, http=http) == ["정수기 렌탈 해지 방법", "정수기렌탈 해지"]


def test_find_apps(monkeypatch):
    class Resp:
        def __init__(self, data=None, status=200):
            self.data, self.status_code = data, status

        def json(self):
            return self.data

    def get(url, **kw):
        if "itunes" in url:
            return Resp({"results": [{"trackName": "코웨이", "bundleId": "com.coway.app", "trackId": 123, "description": "계약 정보 확인"}]})
        return Resp(status=200)

    apps = keywords.find_apps("코웨이", http=SimpleNamespace(get=get))
    assert apps[0]["ios"] == "https://apps.apple.com/kr/app/id123"
    assert apps[0]["android"].startswith("https://play.google.com/store/apps/details?id=com.coway.app")


def test_write_fills_missing_keyword_and_assembles_blocks(monkeypatch):
    first = answer(missing_time=True)
    fixed = answer(missing_time=False)
    fake = FakeLLM(first, {"sections": fixed["sections"]})
    monkeypatch.setattr(llm, "generate_json", fake)
    steps = []
    post, info = formula.write("local:qwen3:8b", MAIN, KWS, button_url="https://example.com/cancel",
                               color="forest", progress=steps.append)
    assert "정수기 렌탈 해지 시간" in fake.calls[1].user and len(fake.calls) == 2
    assert any("빠진 자동검색어 1개" in s for s in steps)
    # 블록 순서: 스타일 → 도입 → 첫 H2 → CTA 박스 → 버튼 → 공백 → 본문 … 하단 버튼 → 출처
    html = post.html
    order = [html.index(x) for x in ("<style>", "<p>", "<h2", 'class="mk-sum"', 'class="mk-cta"', "wp:spacer")]
    assert order == sorted(order)
    assert html.count('class="mk-cta"') == 2 and html.count("<h2") == 5
    assert "#17b86a" in html  # forest 색
    assert 'href="https://example.com/cancel"' in html and "target=" not in html
    assert html.rstrip().endswith("<!-- /wp:paragraph -->") and "2026년 10월 기준" in html
    assert info["slug"] == "water-purifier-rental-cancel"
    assert info["button_text"] == "내 위약금 바로 확인하기"
    checks = {c["name"]: c for c in info["checks"]}
    assert checks["자동검색어 전부 포함"]["ok"], checks["자동검색어 전부 포함"]
    assert checks["첫 H2 = 메인 키워드"]["ok"] and checks["모든 H2에 메인 키워드"]["ok"]
    assert checks["H2 5~7개"]["ok"] and checks["버튼 링크 있음"]["ok"] and checks["영문 슬러그"]["ok"]
    assert checks["H1 없음"]["ok"] and checks["출처·기준일"]["ok"]
    assert post.tags == ["정수기", "렌탈"]


def test_checks_report_problems():
    info = {"main": MAIN, "keywords": ["없는 검색어"], "focus_keyword": MAIN, "slug": "", "button_url": ""}
    checks = {c["name"]: c for c in formula.check("제목이 너무 짧습니다", "<h1>x</h1><h2>다른 소제목</h2><p>짧음</p>", info)}
    assert not checks["자동검색어 전부 포함"]["ok"] and "없는 검색어" in checks["자동검색어 전부 포함"]["detail"]
    assert not checks["제목이 메인 키워드로 시작"]["ok"]
    assert not checks["제목이 명사형으로 끝남"]["ok"]
    assert not checks["첫 H2 = 메인 키워드"]["ok"] and not checks["H1 없음"]["ok"]
    assert not checks["버튼 링크 있음"]["ok"] and not checks["영문 슬러그"]["ok"]


def test_inline_strips_unsafe_tags_and_requires_main():
    assert formula._inline('<strong>굵게</strong> <a href="x">링크</a><script>x</script> & 기호') == "<strong>굵게</strong> 링크x &amp; 기호"
    with pytest.raises(WriterError):
        formula.write("local:qwen3:8b", " ", [])
