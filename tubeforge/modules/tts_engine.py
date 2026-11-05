"""음성 합성 모듈.

장면마다 음성을 따로 만들고 짧은 쉼(gap)을 넣어 하나로 이어 붙인다.
장면별 실제 길이와 단어 단위 타이밍(자막 싱크용)을 함께 돌려준다.

엔진:
- edge      : Microsoft Edge 온라인 TTS (무료, API 키 불필요, 인터넷 필요) — 기본
- elevenlabs: ElevenLabs API (유료, ELEVENLABS_API_KEY 필요)
- dummy     : 무음 + 글자 수로 추정한 타이밍 (인터넷 없이 영상 렌더링만 시험할 때)
"""
from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import env
from .script_generator import CHARS_PER_SEC, Scene

SAMPLE_RATE = 44100


@dataclass
class Word:
    text: str
    start: float  # 장면 음성 안에서의 초
    end: float


@dataclass
class SceneAudio:
    path: Path | None  # None 이면 무음
    duration: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    section: str = "body"


@dataclass
class TTSResult:
    audio_path: Path
    duration: float
    cues: list[Cue]  # 자막 한 덩어리씩
    speech: list[tuple[float, float]]  # 말하는 구간 (BGM 덕킹용)


class TTSEngine(ABC):
    name = "base"

    @abstractmethod
    def synthesize_scene(self, text: str, out_path: Path) -> SceneAudio:
        """한 장면을 음성 파일로 만든다."""

    def synthesize(self, scenes: list[Scene], out_dir: Path, gap: float = 0.25,
                   max_chars: int = 16) -> TTSResult:
        from moviepy import AudioFileClip, concatenate_audioclips

        out_dir.mkdir(parents=True, exist_ok=True)
        parts, cues, speech, t = [], [], [], 0.0
        for i, scene in enumerate(scenes):
            sa = self.synthesize_scene(scene.text, out_dir / f"scene_{i:02d}.mp3")
            clip = AudioFileClip(str(sa.path)) if sa.path else _silence(sa.duration)
            dur = clip.duration
            parts.append(clip)
            parts.append(_silence(gap))
            scene.start, scene.end = round(t, 3), round(t + dur, 3)
            speech.append((t, t + dur))
            for c in chunk_words(sa.words, scene.text, dur, max_chars):
                cues.append(Cue(t + c.start, t + c.end, c.text, scene.section))
            t += dur + gap
        voice = concatenate_audioclips(parts)
        path = out_dir / "voice.mp3"
        voice.write_audiofile(str(path), fps=SAMPLE_RATE, logger=None)
        duration = voice.duration
        for p in parts:
            p.close()
        return TTSResult(path, duration, cues, speech)


def _silence(seconds: float):
    from moviepy import AudioClip

    # t 가 숫자 하나면 (2,), 배열이면 (n, 2) 를 돌려줘야 moviepy 가 스테레오로 인식한다
    def frame(t):
        return np.zeros(2) if np.isscalar(t) else np.zeros((len(t), 2))

    return AudioClip(frame, duration=max(0.01, seconds), fps=SAMPLE_RATE)


def chunk_words(words: list[Word], text: str, duration: float, max_chars: int) -> list[Word]:
    """단어 타이밍을 화면 자막 덩어리(최대 max_chars 글자)로 묶는다.
    단어 타이밍이 없으면 글자 수 비율로 나눈다."""
    if not words:
        tokens = text.split()
        total = sum(len(w) for w in tokens) or 1
        t, words = 0.0, []
        for w in tokens:
            d = duration * len(w) / total
            words.append(Word(w, t, t + d))
            t += d
    chunks: list[Word] = []
    cur: list[Word] = []
    for w in words:
        if cur and (len(" ".join(x.text for x in cur + [w])) > max_chars):
            chunks.append(Word(" ".join(x.text for x in cur), cur[0].start, w.start))
            cur = []
        cur.append(w)
        if w.text.endswith((".", "?", "!", ",")):  # 문장부호에서 끊기
            chunks.append(Word(" ".join(x.text for x in cur), cur[0].start, w.end))
            cur = []
    if cur:
        chunks.append(Word(" ".join(x.text for x in cur), cur[0].start, duration))
    # 덩어리 사이 빈틈 없이 다음 덩어리 시작까지 보이게
    for a, b in zip(chunks, chunks[1:]):
        a.end = b.start
    if chunks:
        chunks[-1].end = duration
    return [c for c in chunks if c.end - c.start > 0.05]


class EdgeTTSEngine(TTSEngine):
    name = "edge"

    def __init__(self, voice: str | None = None, rate: str | None = None):
        self.voice = voice or env("EDGE_VOICE", "ko-KR-SunHiNeural")
        self.rate = rate or env("EDGE_RATE", "+10%")
        self.proxy = env("EDGE_PROXY") or None  # 회사망 등에서 프록시가 필요할 때

    def synthesize_scene(self, text: str, out_path: Path) -> SceneAudio:
        return asyncio.run(self._run(text, out_path))

    async def _run(self, text: str, out_path: Path) -> SceneAudio:
        import edge_tts

        try:
            com = edge_tts.Communicate(text, self.voice, rate=self.rate, proxy=self.proxy, boundary="WordBoundary")
        except TypeError:  # edge-tts 6.x 는 boundary 인자가 없고 기본이 WordBoundary
            com = edge_tts.Communicate(text, self.voice, rate=self.rate, proxy=self.proxy)
        words: list[Word] = []
        with open(out_path, "wb") as f:
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    s = chunk["offset"] / 1e7  # 100ns 단위
                    words.append(Word(chunk["text"], s, s + chunk["duration"] / 1e7))
        if out_path.stat().st_size == 0:
            raise RuntimeError("edge-tts 가 음성을 돌려주지 않았습니다 (인터넷 연결 또는 음성 이름 확인).")
        from moviepy import AudioFileClip

        with AudioFileClip(str(out_path)) as c:
            dur = c.duration
        return SceneAudio(out_path, dur, words)


class ElevenLabsEngine(TTSEngine):
    """ElevenLabs /with-timestamps 엔드포인트로 음성과 글자 타이밍을 함께 받는다."""
    name = "elevenlabs"

    def __init__(self, voice_id: str | None = None):
        self.key = env("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or env("ELEVENLABS_VOICE_ID")
        self.model = env("ELEVENLABS_MODEL", "eleven_multilingual_v2")
        if not self.key or not self.voice_id:
            raise RuntimeError("ELEVENLABS_API_KEY 와 ELEVENLABS_VOICE_ID 를 .env 에 넣으세요.")

    def synthesize_scene(self, text: str, out_path: Path) -> SceneAudio:
        import requests

        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps",
            headers={"xi-api-key": self.key}, timeout=120,
            json={"text": text, "model_id": self.model, "output_format": "mp3_44100_128"})
        r.raise_for_status()
        data = r.json()
        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        al = data.get("alignment") or {}
        chars, starts, ends = al.get("characters", []), al.get("character_start_times_seconds", []), \
            al.get("character_end_times_seconds", [])
        words, cur, ws, last_end = [], "", None, 0.0
        for ch, s, e in zip(chars, starts, ends):
            if ch.isspace():
                if cur:
                    words.append(Word(cur, ws, e))
                cur, ws = "", None
            else:
                ws = s if ws is None else ws
                cur += ch
                last_end = e
        if cur:
            words.append(Word(cur, ws, last_end))
        from moviepy import AudioFileClip

        with AudioFileClip(str(out_path)) as c:
            dur = c.duration
        return SceneAudio(out_path, dur, words)


class DummyTTSEngine(TTSEngine):
    """인터넷 없이 렌더링을 시험하는 무음 엔진 (실제 음성 아님)."""
    name = "dummy"

    def synthesize_scene(self, text: str, out_path: Path) -> SceneAudio:
        return SceneAudio(None, max(1.2, len(text.replace(" ", "")) / CHARS_PER_SEC))


def get_engine(name: str | None = None, voice: str | None = None, rate: str | None = None) -> TTSEngine:
    name = (name or env("TTS_ENGINE", "edge")).lower()
    if name == "edge":
        return EdgeTTSEngine(voice, rate)
    if name == "elevenlabs":
        return ElevenLabsEngine(voice)
    if name == "dummy":
        return DummyTTSEngine()
    raise ValueError(f"알 수 없는 TTS 엔진: {name} (edge | elevenlabs | dummy)")


def write_srt(cues: list[Cue], path: Path) -> None:
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    path.write_text("\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)),
                    encoding="utf-8")
