import pytest

from autoposter import factcheck, llm, style, web
from autoposter.models import Post
from autoposter.writer import WriterError, build_prompt


class FakeLLM:
    """llm.generate_json 대신 미리 정한 답을 돌려주고, 받은 요청을 기록한다."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, engine, system, user, schema, max_tokens=12000):
        self.calls.append({"engine": engine, "system": system, "user": user, "schema": schema})
        answer = self.answers.pop(0)
        return answer(user) if callable(answer) else answer


def test_build_prompt_uses_style_and_references():
    prompt = build_prompt("일상", "산책", "친근한 존댓말", 2000, None,
                          style={"guide": "- 말투: ~해요체", "examples": ["오늘은 산책했어요 😊"]},
                          references="2026년 3월부터 시행")
    assert "글투 설명서" in prompt and "~해요체" in prompt and "오늘은 산책했어요" in prompt
    assert "말투: 친근한 존댓말" not in prompt
    assert "[참고 자료]" in prompt and "2026년 3월부터 시행" in prompt


def test_style_analyze_from_text_and_url(monkeypatch):
    fake = FakeLLM({"guide": "- 말투: ~해요체", "examples": ["안녕하세요!", " "]})
    monkeypatch.setattr(llm, "generate_json", fake)
    pasted = "첫 번째 글입니다. " * 10 + "\n---\n" + "두 번째 글이에요. " * 10 + "\nhttps://blog.example/1"
    result = style.analyze("local:qwen3:8b", pasted, fetch=lambda url: ("제목", "주소에서 읽은 세 번째 글 " * 10))
    assert result == {"guide": "- 말투: ~해요체", "examples": ["안녕하세요!"], "samples": 3}
    assert "[글 3]" in fake.calls[0]["user"] and "주소에서 읽은" in fake.calls[0]["user"]


def test_style_analyze_needs_samples():
    with pytest.raises(WriterError, match="분석할 글이 없습니다"):
        style.analyze("local:qwen3:8b", "짧음")


def test_refine_keeps_fields_and_converts_markdown(monkeypatch):
    fake = FakeLLM({"title": "다듬은 제목", "html": "## 소제목\n\n문장", "tags": []})
    monkeypatch.setattr(llm, "generate_json", fake)
    out = style.refine("local:qwen3:8b", Post("원래 제목", "<p>원문</p>", ["태그"]), {"guide": "- 해요체"})
    assert out.title == "다듬은 제목" and "<h2>소제목</h2>" in out.html and out.tags == ["태그"]
    assert "해요체" in fake.calls[0]["user"]


def test_factcheck_run_and_fix(monkeypatch):
    claims = {"claims": [
        {"claim": "신호 위반 벌점은 15점이다", "query": "신호위반 벌점"},
        {"claim": "과속 과태료는 100만원이다", "query": "과속 과태료"},
        {"claim": "근거 없는 주장", "query": "아무거나"},
    ]}
    fake = FakeLLM(
        claims,
        {"verdict": "맞음", "correct": "", "reason": "자료와 같음", "source_url": "https://www.law.go.kr/a"},
        {"verdict": "틀림", "correct": "과속 과태료는 최대 13만원", "reason": "자료와 다름", "source_url": "https://지어낸주소"},
        # 세 번째 주장은 자료가 없어 AI를 부르지 않고 '확인 불가'
        {"title": "고친 제목", "html": "<p>고친 본문</p>", "tags": ["교통"]},
    )
    monkeypatch.setattr(llm, "generate_json", fake)

    def search(query):
        return [] if query == "아무거나" else [{"url": "https://www.law.go.kr/a", "title": "법령"}]

    def fetch(url):
        return "도로교통법", "신호위반 벌점 15점\n과속 과태료 13만원\n관련 없는 줄"

    progress = []
    report = factcheck.run("local:qwen3:8b", Post("교통 법규", "<p>본문</p>"), "", lambda m, f: progress.append(m),
                           search=search, fetch=fetch)
    verdicts = [(r["verdict"], r["source_url"]) for r in report["results"]]
    assert verdicts == [("맞음", "https://www.law.go.kr/a"), ("틀림", "https://www.law.go.kr/a"), ("확인 불가", "")]
    assert report["results"][1]["correct"] == "과속 과태료는 최대 13만원"
    assert any("2/3" in m for m in progress)
    judge_prompt = fake.calls[1]["user"]
    assert "신호위반 벌점 15점" in judge_prompt and "https://www.law.go.kr/a" in judge_prompt

    fixed = factcheck.apply_fixes("local:qwen3:8b", Post("교통 법규", "<p>본문</p>"), report)
    assert "고친 본문" in fixed.html and "참고한 공식 자료" in fixed.html and "law.go.kr/a" in fixed.html
    fix_prompt = fake.calls[-1]["user"]
    assert "[틀림] 과속 과태료는 100만원이다" in fix_prompt and "[확인 불가] 근거 없는 주장" in fix_prompt
    # 다시 고쳐도 출처 목록이 두 번 붙지 않는다
    assert factcheck.add_sources(fixed.html, report).count("참고한 공식 자료") == 1


def test_references_used_as_evidence_even_without_search(monkeypatch):
    fake = FakeLLM({"claims": [{"claim": "시행일은 3월 1일", "query": "시행일"}]},
                   {"verdict": "맞음", "correct": "", "reason": "", "source_url": ""})
    monkeypatch.setattr(llm, "generate_json", fake)
    report = factcheck.run("local:qwen3:8b", Post("t", "<p>b</p>"), "개정안 시행일은 3월 1일입니다.",
                           search=lambda q: (_ for _ in ()).throw(RuntimeError("검색 막힘")), fetch=None)
    assert report["results"][0]["verdict"] == "맞음"
    assert "직접 넣은 참고 자료" in fake.calls[1]["user"]


def test_fix_requires_something_to_fix():
    with pytest.raises(WriterError, match="고칠 항목이 없습니다"):
        factcheck.apply_fixes("local:qwen3:8b", Post("t", "<p>b</p>"), {"results": [{"verdict": "맞음"}]})


def test_web_helpers():
    assert web.is_official("https://www.law.go.kr/법령") and web.is_official("https://www.korea.kr/x")
    assert web.is_official("https://koroad.or.kr/") and not web.is_official("https://blog.naver.com/x")
    assert not web.is_official("https://evilgo.kr/")
    assert web.normalize_url("https://blog.naver.com/me/22334455") == "https://m.blog.naver.com/me/22334455"
    assert web.normalize_url("https://blog.naver.com/PostView.naver?blogId=me&logNo=9") == "https://m.blog.naver.com/me/9"
    title, text = web.html_to_text("<html><head><title>제목 &amp; 부제</title><script>x()</script></head>"
                                   "<body><nav>메뉴</nav><p>첫 줄</p><p>둘째&nbsp;줄</p></body></html>")
    assert title == "제목 & 부제" and text == "첫 줄\n둘째 줄"
    assert web.split_urls("https://a.go.kr/1\n본문 글\n") == (["https://a.go.kr/1"], "본문 글")
    passage = web.relevant_passages("무관한 줄입니다\n신호위반 벌점은 15점입니다\n또 무관한 줄", ["벌점"])
    assert "벌점은 15점" in passage


def test_search_parses_duckduckgo_and_filters_official(monkeypatch):
    page = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.law.go.kr%2Fx&rut=1">도로교통법</a>'
        '<a class="result__a" href="https://blog.naver.com/y">블로그</a>'
    )

    class Resp:
        text = page

    monkeypatch.setattr(web.requests, "get", lambda *a, **k: Resp())
    assert web.search_official("벌점") == [{"url": "https://www.law.go.kr/x", "title": "도로교통법"}]
