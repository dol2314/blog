"""대본 생성 모듈.

키워드(또는 기사 본문)를 받아 쇼츠(9:16, 30~60초)나 롱폼 대본을 만든다.
구조는 훅(첫 3초) → 본문 → CTA 이고, 장면마다 화면 문구용 키워드와 예상 타임스탬프가 붙는다.
실제 타임스탬프는 음성 합성 뒤 tts_engine 이 측정한 값으로 다시 채운다.

공급자: claude(Anthropic) · openai · ollama(로컬, 무료) · template(키 없이 파이프라인 시험용)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .config import env

# 한국어 TTS(edge-tts, +10%)가 1초에 읽는 글자 수(공백 제외) 근사치
CHARS_PER_SEC = 6.8


@dataclass
class Scene:
    section: str  # hook | body | cta
    text: str  # 읽을 문장 (1~2문장)
    visual: str = ""  # 화면 키워드/배경 검색어
    start: float = 0.0
    end: float = 0.0


@dataclass
class VideoScript:
    topic: str
    video_type: str  # shorts | long
    title: str
    description: str
    tags: list[str]
    scenes: list[Scene]
    provider: str = ""
    target_seconds: int = 30
    extra: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.scenes)

    def estimate_timings(self) -> None:
        """글자 수로 예상 시작·끝 시각을 채운다 (음성 합성 전 미리보기용)."""
        t = 0.0
        for s in self.scenes:
            dur = max(1.2, len(s.text.replace(" ", "")) / CHARS_PER_SEC)
            s.start, s.end = round(t, 2), round(t + dur, 2)
            t += dur + 0.25

    def timestamps(self) -> str:
        lines = []
        for s in self.scenes:
            m, sec = divmod(int(s.start), 60)
            lines.append(f"{m:02d}:{sec:02d} [{s.section.upper()}] {s.text}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        tags = " ".join("#" + t.replace(" ", "") for t in self.tags)
        return (f"# {self.title}\n\n- 유형: {self.video_type} · 목표 {self.target_seconds}초 · 생성: {self.provider}\n\n"
                f"## 타임라인\n\n```\n{self.timestamps()}\n```\n\n## 설명란\n\n{self.description}\n\n{tags}\n")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VideoScript":
        d = dict(d)
        d["scenes"] = [Scene(**s) for s in d.get("scenes", [])]
        return cls(**d)


# ──────────────────────────────── 프롬프트 ────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": ["hook", "body", "cta"]},
                    "text": {"type": "string"},
                    "visual": {"type": "string"},
                },
                "required": ["section", "text", "visual"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "tags", "scenes"],
    "additionalProperties": False,
}

SYSTEM = """당신은 한국어 유튜브 대본 작가입니다. 시청 지속률이 높은 대본을 씁니다.
규칙:
- 구조: hook(첫 장면, 3초 안에 궁금증·반전·숫자로 붙잡기) → body(핵심 정보, 한 장면에 한 가지) → cta(마지막 장면, 구독·댓글 유도 한 문장).
- 장면 text 는 소리 내어 읽기 좋은 구어체 1~2문장. 한 장면 15~45자. 이모지·괄호·특수기호·영문 약어 남발 금지(TTS가 읽음).
- visual 은 그 장면 배경으로 쓸 화면 키워드(한국어 2~4단어).
- 확인되지 않은 사실·루머·실명 비방·선정적 표현은 쓰지 않습니다. 원문(기사)이 주어지면 그 안의 사실만 씁니다.
- title 은 40자 이내, 클릭하고 싶지만 낚시가 아닌 제목. description 은 2~3문장 요약. tags 는 5~10개.
- 반드시 JSON 만 출력합니다."""


def build_prompt(topic: str, video_type: str, seconds: int, source_text: str | None) -> str:
    chars = int(seconds * CHARS_PER_SEC)
    if video_type == "shorts":
        n = max(5, min(12, seconds // 5))
        shape = f"세로형 쇼츠, 총 {seconds}초 분량(공백 제외 약 {chars}자), 장면 {n}개 안팎."
    else:
        n = max(12, seconds // 20)
        shape = (f"가로형 롱폼, 총 약 {seconds // 60}분 분량(공백 제외 약 {chars}자), 장면 {n}개 안팎. "
                 "body 는 소제목 단위로 묶이게 3~5개 파트로 전개하고 파트가 바뀌는 장면 visual 에 '파트: 소제목' 을 넣으세요.")
    src = f"\n\n[참고 원문]\n{source_text[:6000]}" if source_text else ""
    return (f"주제: {topic}\n형식: {shape}\n아래 JSON 스키마로 대본을 작성하세요.\n"
            f"{json.dumps(SCHEMA, ensure_ascii=False)}{src}")


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # Qwen3 사고 출력 제거
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("AI 응답에서 JSON 을 찾지 못했습니다:\n" + text[:500])
    return json.loads(m.group(0))


# ──────────────────────────────── 공급자 ────────────────────────────────

def _claude(prompt: str, model: str | None) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = dict(
        model=model or env("CLAUDE_MODEL", "claude-opus-5-5"),
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # 안전 분류기가 거절하면 서버가 다른 모델로 다시 돌리도록 fallback 을 켠다
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        response = client.messages.create(**kwargs)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude 가 이 주제의 대본 작성을 거절했습니다. 주제를 바꿔 보세요.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("대본이 너무 길어 잘렸습니다. --duration 을 줄여 보세요.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _openai(prompt: str, model: str | None) -> dict:
    from openai import OpenAI

    client = OpenAI()
    r = client.chat.completions.create(
        model=model or env("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "video_script", "schema": SCHEMA, "strict": True}},
    )
    return json.loads(r.choices[0].message.content)


def _ollama(prompt: str, model: str | None) -> dict:
    import requests

    host = env("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    model = model or _ollama_model(host)
    print(f"  Ollama 모델: {model} (처음엔 몇 분 걸릴 수 있습니다)")
    r = requests.post(f"{host}/api/chat", timeout=900, json={
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt + " /no_think"}],
        "format": SCHEMA, "stream": False, "options": {"temperature": 0.7},
    })
    r.raise_for_status()
    return _parse_json(r.json()["message"]["content"])


def _ollama_model(host: str) -> str:
    """설정한 모델이 없으면 설치된 qwen3 → 아무 모델 순으로 고른다."""
    import requests

    want = env("OLLAMA_MODEL", "qwen3:8b")
    names = [m["name"] for m in requests.get(f"{host}/api/tags", timeout=5).json().get("models", [])]
    if not names:
        raise RuntimeError("Ollama 에 설치된 모델이 없습니다. 명령 프롬프트에서: ollama pull qwen3:8b")
    for n in [want, want + ":latest"]:
        if n in names:
            return n
    return next((n for n in names if n.startswith("qwen3")), names[0])


def _template(topic: str, video_type: str, seconds: int, source_text: str | None) -> dict:
    """API 키 없이 파이프라인을 시험하기 위한 정형 대본. 내용은 일반적인 안내 문장뿐이다."""
    first = ""
    if source_text:
        sents = [s.strip() for s in re.split(r"(?<=[.!?다요])\s+", source_text) if len(s.strip()) > 8]
        first = sents[:6]
    body = first or [
        f"{topic}, 요즘 왜 이렇게 화제일까요?",
        "첫 번째, 지금 사람들이 가장 많이 찾는 이유부터 보겠습니다.",
        "두 번째, 알고 보면 놓치기 쉬운 포인트가 하나 있습니다.",
        "세 번째, 실제로 확인할 때는 공식 발표를 먼저 보세요.",
        "마지막으로, 앞으로 어떻게 될지는 조금 더 지켜봐야 합니다.",
    ]
    scenes = [{"section": "hook", "text": f"{topic}, {seconds}초 만에 핵심만 정리해 드립니다.", "visual": topic}]
    scenes += [{"section": "body", "text": t, "visual": topic} for t in body]
    scenes.append({"section": "cta", "text": "도움이 됐다면 구독하고, 궁금한 점은 댓글로 남겨 주세요.", "visual": "구독"})
    return {"title": f"{topic} {seconds}초 핵심 정리", "description": f"{topic}에 대해 꼭 알아야 할 내용을 짧게 정리했습니다.",
            "tags": [topic, "쇼츠", "이슈정리", f"{seconds}초정리"], "scenes": scenes}


def pick_provider(name: str) -> str:
    if name != "auto":
        return name
    if env("ANTHROPIC_API_KEY"):
        return "claude"
    if env("OPENAI_API_KEY"):
        return "openai"
    try:
        import requests

        requests.get(env("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/tags", timeout=1.5).raise_for_status()
        return "ollama"
    except Exception:
        return "template"


def generate_script(topic: str, video_type: str = "shorts", seconds: int = 30, provider: str = "auto",
                    source_text: str | None = None, model: str | None = None) -> VideoScript:
    requested = provider if provider and provider != "auto" else env("SCRIPT_PROVIDER", "auto")
    auto = requested == "auto"
    provider = pick_provider(requested)
    if provider == "template":
        data = _template(topic, video_type, seconds, source_text)
    else:
        prompt = build_prompt(topic, video_type, seconds, source_text)
        fn = {"claude": _claude, "openai": _openai, "ollama": _ollama}.get(provider)
        if fn is None:
            raise ValueError(f"알 수 없는 대본 공급자: {provider}")
        try:
            data = fn(prompt, model)
        except Exception as e:
            if not auto:
                raise
            print(f"  ※ {provider} 대본 생성 실패 → 예시 대본으로 계속합니다: {e}")
            provider, data = "template", _template(topic, video_type, seconds, source_text)
    scenes = [Scene(section=s.get("section", "body"), text=s["text"].strip(), visual=s.get("visual", ""))
              for s in data["scenes"] if s.get("text", "").strip()]
    if not scenes:
        raise ValueError("대본 장면이 비어 있습니다.")
    script = VideoScript(topic=topic, video_type=video_type, title=data["title"].strip(),
                         description=data.get("description", "").strip(), tags=data.get("tags", [])[:15],
                         scenes=scenes, provider=provider, target_seconds=seconds)
    script.estimate_timings()
    return script
