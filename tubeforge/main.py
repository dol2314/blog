"""TubeForge — 주제 한 줄로 쇼츠/롱폼 영상 만들기.

    python main.py --topic "오늘의 연예 이슈" --type shorts
    python main.py --topic "전기요금 누진제" --type shorts --duration 60 --bgm assets/bgm/calm.mp3
    python main.py --topic "AI 반도체 전쟁" --type long --duration 300 --bg assets/backgrounds
    python main.py --topic "..." --upload --publish-at "2026-11-07 18:00"   # 유튜브 예약 발행
    python main.py --from-script output/<폴더>/script.json                   # 손본 대본으로 다시 렌더링

결과물: output/<날짜_주제>/ 에 script.json · script.md(타임스탬프) · voice.mp3 · captions.srt · thumbnail.jpg · final.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from modules.config import ROOT, slugify


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="AI 유튜브 쇼츠/롱폼 자동 제작")
    p.add_argument("--topic", help="영상 주제/키워드")
    p.add_argument("--type", choices=["shorts", "long"], default="shorts")
    p.add_argument("--duration", type=int, help="목표 길이(초). 기본: 쇼츠 30, 롱폼 300")
    p.add_argument("--source", help="참고할 기사/원문 텍스트 파일 (그 안의 사실로만 대본 작성)")
    p.add_argument("--provider", default=None, help="auto | claude | openai | ollama | template")
    p.add_argument("--model", help="대본 모델 이름 (공급자 기본값 대신)")
    p.add_argument("--from-script", help="이미 만든 script.json 으로 음성·영상만 다시 만들기")
    p.add_argument("--tts", default=None, help="edge | elevenlabs | dummy(무음 테스트)")
    p.add_argument("--voice", help="edge-tts 음성 (예: ko-KR-InJoonNeural) 또는 ElevenLabs voice id")
    p.add_argument("--rate", help="말하기 속도 (예: +15%%, -5%%)")
    p.add_argument("--bg", help="배경 이미지/영상 파일 또는 폴더 (없으면 그라데이션 자동)")
    p.add_argument("--bgm", help="배경음악 파일 (말할 때 자동으로 작아짐)")
    p.add_argument("--out", help="결과 폴더 (기본 output/<날짜_주제>)")
    p.add_argument("--script-only", action="store_true", help="대본만 만들고 멈추기")
    p.add_argument("--preset", default="veryfast", help="x264 프리셋 (ultrafast~slow)")
    p.add_argument("--upload", action="store_true", help="렌더링 후 유튜브에 업로드")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--publish-at", help="예약 발행 시각, 한국 시간 'YYYY-MM-DD HH:MM'")
    a = p.parse_args(argv)
    if not a.topic and not a.from_script:
        p.error("--topic 또는 --from-script 중 하나는 꼭 넣어야 합니다.")
    a.duration = a.duration or (30 if a.type == "shorts" else 300)
    if a.type == "shorts" and a.duration > 60:
        print("※ 쇼츠는 60초 이하를 권장합니다 (유튜브는 3분까지 허용).", file=sys.stderr)
    return a


def step(msg: str):
    print(f"\n▶ {msg}", flush=True)
    return time.time()


def main(argv=None) -> Path:
    a = parse_args(argv)
    from modules.script_generator import VideoScript, generate_script

    # 1) 대본
    t0 = step("대본 생성")
    if a.from_script:
        src = Path(a.from_script)
        script = VideoScript.from_dict(json.loads(src.read_text(encoding="utf-8")))
        out = Path(a.out) if a.out else src.parent
    else:
        source_text = Path(a.source).read_text(encoding="utf-8") if a.source else None
        script = generate_script(a.topic, a.type, a.duration, a.provider or "auto", source_text, a.model)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(a.out) if a.out else ROOT / "output" / f"{stamp}_{slugify(a.topic)}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"  공급자: {script.provider} · 제목: {script.title} · 장면 {len(script.scenes)}개")
    if script.provider == "template":
        print("  ※ API 키/Ollama 가 없어 예시 대본(template)으로 만들었습니다. .env 에 키를 넣으면 AI 대본으로 바뀝니다.")
    (out / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {time.time() - t0:.1f}초")
    if a.script_only:
        (out / "script.md").write_text(script.to_markdown(), encoding="utf-8")
        print(f"\n대본: {out / 'script.md'}")
        return out

    # 2) 음성
    from modules.tts_engine import get_engine, write_srt

    t0 = step("음성 합성")
    engine = get_engine(a.tts, a.voice, a.rate)
    tts = engine.synthesize(script.scenes, out / "audio", max_chars=16 if script.video_type == "shorts" else 28)
    write_srt(tts.cues, out / "captions.srt")
    # 실제 음성 길이로 맞춘 타임스탬프 저장
    (out / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "script.md").write_text(script.to_markdown(), encoding="utf-8")
    print(f"  엔진: {engine.name} · 길이 {tts.duration:.1f}초 · 자막 {len(tts.cues)}개 · {time.time() - t0:.1f}초")

    # 3) 영상
    from modules.video_composer import compose_video, make_thumbnail

    t0 = step("영상 렌더링")
    video = compose_video(script, tts, out / "final.mp4", bg=a.bg, bgm=a.bgm, preset=a.preset)
    thumb = make_thumbnail(script, out / "thumbnail.jpg", bg=a.bg)
    print(f"  {time.time() - t0:.1f}초")

    # 4) 업로드
    if a.upload:
        from modules.youtube_uploader import upload_video

        t0 = step("유튜브 업로드")
        desc = script.description + "\n\n" + script.timestamps() if script.video_type == "long" else script.description
        vid = upload_video(video, script.title, desc, script.tags, a.privacy, a.publish_at,
                           thumbnail=thumb, captions=out / "captions.srt", shorts=script.video_type == "shorts")
        print(f"  https://youtu.be/{vid} ({'예약 ' + a.publish_at if a.publish_at else a.privacy})")

    print(f"\n완료: {video}")
    return out


if __name__ == "__main__":
    main()
