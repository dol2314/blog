"""오프라인 테스트: python -m pytest tests -q   (인터넷·API 키 불필요)"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import script_generator as sg  # noqa: E402
from modules import tts_engine as te  # noqa: E402
from modules.script_generator import Scene, VideoScript, generate_script  # noqa: E402
from modules.video_composer import duck_envelope  # noqa: E402
from modules.youtube_uploader import parse_publish_at  # noqa: E402


def test_template_script_structure():
    s = generate_script("전기요금 누진제", "shorts", 30, provider="template")
    assert s.scenes[0].section == "hook" and s.scenes[-1].section == "cta"
    assert all(a.end <= b.start for a, b in zip(s.scenes, s.scenes[1:]))
    assert "00:00 [HOOK]" in s.timestamps()
    again = VideoScript.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again.scenes[1].text == s.scenes[1].text


def test_claude_provider_request_shape(monkeypatch):
    calls = {}
    data = {"title": "t", "description": "d", "tags": ["a"],
            "scenes": [{"section": "hook", "text": "첫 문장입니다", "visual": "v"}]}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(data))])

    class FakeClient:
        def __init__(self):
            self.beta = SimpleNamespace(messages=FakeMessages())
            self.messages = FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    s = generate_script("주제", "shorts", 30, provider="claude")
    assert s.title == "t" and s.provider == "claude"
    assert calls["model"] == "claude-opus-5-5"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["fallbacks"] == "default"


def test_parse_json_strips_fences_and_think():
    assert sg._parse_json('<think>음</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_chunk_words_groups_and_fills_gaps():
    words = [te.Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate("오늘은 날씨가 아주 맑고 바람이 붑니다.".split())]
    chunks = te.chunk_words(words, "", 3.0, max_chars=10)
    assert all(len(c.text) <= 12 for c in chunks)
    assert all(a.end == b.start for a, b in zip(chunks, chunks[1:]))
    assert chunks[-1].end == 3.0


def test_chunk_words_without_timings_uses_char_ratio():
    chunks = te.chunk_words([], "가나다 라마바사 아자차카타", 2.0, max_chars=8)
    assert chunks[0].start == 0 and abs(chunks[-1].end - 2.0) < 1e-9


def test_duck_envelope_levels():
    g = duck_envelope([(2.0, 4.0)], 6.0, base=0.3, duck=0.08)
    assert abs(g(0.5) - 0.3) < 1e-3 and abs(g(3.0) - 0.08) < 1e-3 and abs(g(5.5) - 0.3) < 1e-3
    assert 0.08 < g(1.85) < 0.3  # 부드럽게 내려감


def test_srt(tmp_path):
    te.write_srt([te.Cue(0, 1.5, "안녕"), te.Cue(61.2, 62, "끝")], tmp_path / "a.srt")
    text = (tmp_path / "a.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,500" in text and "00:01:01,200 --> 00:01:02,000" in text


def test_publish_at_kst_to_utc():
    assert parse_publish_at("2099-01-02 18:00") == "2099-01-02T09:00:00.000Z"
    with pytest.raises(ValueError):
        parse_publish_at("2000-01-01 00:00")


@pytest.fixture
def tone_mp3(tmp_path):
    from moviepy import AudioClip

    path = tmp_path / "tone.mp3"
    AudioClip(lambda t: np.stack([0.2 * np.sin(2 * np.pi * 440 * np.asarray(t))] * 2, axis=-1),
              duration=1.0, fps=44100).write_audiofile(str(path), logger=None)
    return path.read_bytes()


def test_edge_engine_with_fake_stream(monkeypatch, tmp_path, tone_mp3):
    class FakeCommunicate:
        def __init__(self, text, voice, rate=None, proxy=None, boundary=None):
            self.words = text.split()

        async def stream(self):
            yield {"type": "audio", "data": tone_mp3}
            for i, w in enumerate(self.words):
                yield {"type": "WordBoundary", "offset": int(i * 0.3 * 1e7), "duration": int(0.25 * 1e7), "text": w}

    import edge_tts
    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    scenes = [Scene("hook", "첫 장면 문장입니다"), Scene("cta", "구독 부탁드립니다")]
    r = te.EdgeTTSEngine().synthesize(scenes, tmp_path)
    assert r.audio_path.exists() and 2.2 < r.duration < 2.8
    assert scenes[1].start > scenes[0].end and r.cues[0].section == "hook"
    assert r.cues[0].start == 0


@pytest.mark.parametrize("vtype,size", [("shorts", (1080, 1920)), ("long", (1920, 1080))])
def test_render_short_clip(tmp_path, vtype, size):
    from moviepy import AudioClip, VideoFileClip

    from modules.video_composer import compose_video

    script = VideoScript("테스트", vtype, "렌더링 테스트 제목", "", [],
                         [Scene("hook", "짧은 훅 문장"), Scene("cta", "구독해 주세요")])
    tts = te.DummyTTSEngine().synthesize(script.scenes, tmp_path / "audio")
    bgm = tmp_path / "bgm.mp3"
    AudioClip(lambda t: np.stack([0.2 * np.sin(2 * np.pi * 220 * np.asarray(t))] * 2, axis=-1),
              duration=1.0, fps=44100).write_audiofile(str(bgm), logger=None)
    out = compose_video(script, tts, tmp_path / "out.mp4", bgm=str(bgm), preset="ultrafast")
    with VideoFileClip(str(out)) as v:
        assert tuple(v.size) == size
        assert abs(v.duration - (tts.duration + 0.4)) < 0.15
        assert v.audio is not None


def test_auto_falls_back_to_template_when_provider_fails(monkeypatch):
    monkeypatch.setattr(sg, "pick_provider", lambda name: "ollama")
    monkeypatch.setattr(sg, "_ollama", lambda p, m: (_ for _ in ()).throw(RuntimeError("down")))
    s = generate_script("주제", "shorts", 30, provider="auto")
    assert s.provider == "template"
    with pytest.raises(RuntimeError):
        generate_script("주제", "shorts", 30, provider="ollama")
