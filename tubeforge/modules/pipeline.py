"""CLI(main.py)와 앱(app/)이 함께 쓰는 제작 단계.

프로젝트 = output/<날짜_주제>/ 폴더 하나.
  script.json  대본(장면·타임스탬프)    project.json  제작 설정과 상태
  audio/voice.mp3 · captions.srt · thumbnail.jpg · final.mp4
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import ROOT, slugify
from .script_generator import VideoScript, generate_script

OUTPUT = ROOT / "output"
Progress = Callable[[str, float | None], None]  # (메시지, 0~1 진행률 또는 None)


def _noop(msg: str, frac: float | None = None) -> None:
    pass


# ──────────────────────────────── 프로젝트 ────────────────────────────────

def new_project_dir(topic: str) -> Path:
    d = OUTPUT / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(topic)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_script(script: VideoScript, out: Path) -> None:
    (out / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "script.md").write_text(script.to_markdown(), encoding="utf-8")


def load_script(out: Path) -> VideoScript:
    return VideoScript.from_dict(json.loads((out / "script.json").read_text(encoding="utf-8")))


def load_meta(out: Path) -> dict:
    p = out / "project.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_meta(out: Path, **changes) -> dict:
    meta = load_meta(out)
    meta.update(changes, updated=time.time())
    meta.setdefault("created", meta["updated"])
    (out / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_projects() -> list[dict]:
    items = []
    if not OUTPUT.exists():
        return items
    for d in sorted(OUTPUT.iterdir(), reverse=True):
        if not (d / "script.json").exists():
            continue
        try:
            s = json.loads((d / "script.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = load_meta(d)
        items.append({
            "id": d.name, "title": s.get("title", d.name), "topic": s.get("topic", ""),
            "type": s.get("video_type", "shorts"), "provider": s.get("provider", ""),
            "scenes": len(s.get("scenes", [])), "created": meta.get("created", d.stat().st_mtime),
            "has_video": (d / "final.mp4").exists(), "has_thumb": (d / "thumbnail.jpg").exists(),
            "youtube": meta.get("youtube"),
        })
    return items


# ──────────────────────────────── 단계 ────────────────────────────────

def make_script(topic: str, video_type: str = "shorts", seconds: int = 30, provider: str = "auto",
                source_text: str | None = None, model: str | None = None, out: Path | None = None,
                progress: Progress = _noop) -> tuple[VideoScript, Path]:
    progress("대본을 쓰는 중…", None)
    script = generate_script(topic, video_type, seconds, provider, source_text, model)
    out = out or new_project_dir(topic)
    save_script(script, out)
    save_meta(out, stage="script", source=bool(source_text))
    return script, out


def make_images(script: VideoScript, out: Path, indices: list[int] | None = None, force: bool = False,
                style: str | None = None, progress: Progress = _noop) -> list[dict]:
    """장면 이미지(Google)를 만들고 대본에 경로를 저장한다. 실패한 장면은 오류 문구와 함께 돌려준다."""
    from .image_generator import generate_scene_images

    results = generate_scene_images(script, out, style=style, indices=indices, force=force, progress=progress)
    save_script(script, out)
    failed = [{"scene": r.index + 1, "error": r.error} for r in results if not r.path]
    save_meta(out, images=sum(1 for sc in script.scenes if sc.image and (out / sc.image).exists()))
    return failed


def render(script: VideoScript, out: Path, tts: str | None = None, voice: str | None = None,
           rate: str | None = None, bg: str | None = None, bgm: str | None = None, preset: str = "veryfast",
           progress: Progress = _noop, cli: bool = False, images: bool | None = None) -> dict:
    """(장면 이미지) → 음성 → 자막 → 영상 → 썸네일. 결과 파일 경로를 돌려준다.
    images=None 이면 Google API 키가 있을 때만 빠진 장면 이미지를 먼저 만든다."""
    from .image_generator import image_available
    from .tts_engine import get_engine, write_srt
    from .video_composer import compose_video, make_thumbnail

    image_errors: list[dict] = []
    if images or (images is None and image_available() and not bg):
        image_errors = make_images(script, out, progress=lambda m, f=None: progress(m, None if f is None else 0.02 + 0.2 * f))
        if image_errors:
            progress(f"이미지 {len(image_errors)}장은 만들지 못해 기본 배경으로 대신합니다.", None)
    engine = get_engine(tts, voice, rate)
    progress(f"음성 만드는 중… ({engine.name})", 0.24)
    voice_res = engine.synthesize(script.scenes, out / "audio",
                                  max_chars=16 if script.video_type == "shorts" else 28)
    write_srt(voice_res.cues, out / "captions.srt")
    save_script(script, out)  # 실제 음성 길이로 타임스탬프 갱신
    progress(f"영상 렌더링 중… (길이 {voice_res.duration:.0f}초)", 0.32)
    logger = "bar" if cli else _RenderLogger(lambda f: progress("영상 렌더링 중…", 0.32 + 0.65 * f))
    video = compose_video(script, voice_res, out / "final.mp4", bg=bg, bgm=bgm, preset=preset, logger=logger,
                          project_dir=out)
    thumb = make_thumbnail(script, out / "thumbnail.jpg", bg=bg, project_dir=out)
    save_meta(out, stage="rendered", duration=round(voice_res.duration, 1), tts=engine.name,
              voice=getattr(engine, "voice", None), bg=bg, bgm=bgm)
    progress("완성!", 1.0)
    return {"video": video, "thumbnail": thumb, "captions": out / "captions.srt", "duration": voice_res.duration,
            "image_errors": image_errors}


def upload(script: VideoScript, out: Path, privacy: str = "private", publish_at: str | None = None,
           progress: Progress = _noop) -> str:
    from .youtube_uploader import upload_video

    progress("유튜브에 올리는 중…", None)
    desc = script.description
    if script.video_type == "long":
        desc += "\n\n" + script.timestamps()
    vid = upload_video(out / "final.mp4", script.title, desc, script.tags, privacy, publish_at,
                       thumbnail=out / "thumbnail.jpg", captions=out / "captions.srt",
                       shorts=script.video_type == "shorts")
    save_meta(out, youtube={"id": vid, "privacy": privacy, "publish_at": publish_at, "at": time.time()})
    progress("업로드 완료", 1.0)
    return vid


def _RenderLogger(callback: Callable[[float], None]):
    """moviepy 의 프레임 진행률(0~1)을 콜백으로 넘기는 proglog 로거."""
    from proglog import ProgressBarLogger

    class L(ProgressBarLogger):
        def bars_callback(self, bar, attr, value, old_value=None):
            if bar == "frame_index" and attr == "index":
                total = self.bars[bar].get("total") or 0
                if total:
                    callback(min(1.0, value / total))

    return L()
