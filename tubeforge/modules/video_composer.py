"""영상 합성·렌더링 모듈 (moviepy 2 + FFmpeg).

- 해상도: shorts 1080x1920(9:16), long 1920x1080(16:9)
- 배경: 이미지/영상 파일 또는 폴더(장면마다 돌아가며). 없으면 그라데이션 배경 자동 생성
- 이미지 배경은 천천히 확대(켄 번스)해서 정지 화면처럼 보이지 않게 함
- 자막: 음성 단어 타이밍에 맞춘 덩어리 자막(굵은 흰 글씨 + 검은 테두리), 훅은 노란색
- 상단 제목 바(쇼츠), 진행 막대
- BGM: 영상 길이만큼 반복, 말하는 구간에서 자동으로 줄였다가(덕킹) 쉬는 구간에서 다시 올림
"""
from __future__ import annotations

import colorsys
import random
import textwrap
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import env_float, find_font
from .script_generator import VideoScript
from .tts_engine import TTSResult

SIZES = {"shorts": (1080, 1920), "long": (1920, 1080)}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
FPS = 30


# ──────────────────────────────── 배경 ────────────────────────────────

def gradient_background(size: tuple[int, int], seed: int) -> Image.Image:
    """장면마다 색이 다른 세로 그라데이션 + 부드러운 원형 빛."""
    w, h = size
    rnd = random.Random(seed)
    hue = rnd.random()
    top = np.array(colorsys.hsv_to_rgb(hue, 0.65, 0.35)) * 255
    bottom = np.array(colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.75, 0.12)) * 255
    ramp = np.linspace(0, 1, h)[:, None, None]
    arr = (top * (1 - ramp) + bottom * ramp).repeat(w, axis=1).astype(np.uint8)
    img = Image.fromarray(arr)
    glow = Image.new("RGB", size, 0)
    d = ImageDraw.Draw(glow)
    for _ in range(3):
        r = rnd.randint(w // 4, w // 2)
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        color = tuple(int(c * 255) for c in colorsys.hsv_to_rgb((hue + rnd.random() * 0.2) % 1, 0.6, 0.6))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(w // 6))
    return Image.blend(img, glow, 0.35)


def list_backgrounds(bg: str | None) -> list[Path]:
    if not bg:
        return []
    p = Path(bg)
    if p.is_dir():
        return sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT | VIDEO_EXT)
    if p.exists():
        return [p]
    raise FileNotFoundError(f"배경 파일을 찾을 수 없습니다: {bg}")


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """비율을 유지한 채 화면을 꽉 채우도록 잘라낸다."""
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s + 0.5), int(img.height * s + 0.5)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


MOTIONS = ["in", "pan_right", "out", "pan_left", "up"]


def image_clip_kenburns(img: Image.Image, size: tuple[int, int], duration: float, zoom: float = 0.08,
                        motion: str = "in"):
    """정지 이미지에 천천히 움직이는 카메라 효과를 준다 (줌인·줌아웃·좌우·위로 이동).
    프레임마다 numpy 로 잘라 크기만 바꾸므로 빠르다."""
    from moviepy import VideoClip

    w, h = size
    big = np.asarray(cover(img, (int(w * (1 + zoom)), int(h * (1 + zoom)))).convert("RGB"))
    bh, bw = big.shape[:2]
    full = (0.0, 0.0, float(bw), float(bh))                       # 전체 (가장 넓게)
    cw, ch = bw / (1 + zoom), bh / (1 + zoom)                      # 화면 크기만큼
    center = ((bw - cw) / 2, (bh - ch) / 2, cw, ch)
    plans = {
        "in": (full, center),
        "out": (center, full),
        "pan_right": ((0.0, (bh - ch) / 2, cw, ch), (bw - cw, (bh - ch) / 2, cw, ch)),
        "pan_left": ((bw - cw, (bh - ch) / 2, cw, ch), (0.0, (bh - ch) / 2, cw, ch)),
        "up": (((bw - cw) / 2, bh - ch, cw, ch), ((bw - cw) / 2, 0.0, cw, ch)),
    }
    a, b = plans.get(motion, plans["in"])

    def frame(t):
        u = min(1.0, max(0.0, t / max(duration, 0.01)))
        u = u * u * (3 - 2 * u)  # 부드럽게 시작·끝
        x, y, cw_, ch_ = (a[k] + (b[k] - a[k]) * u for k in range(4))
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = min(bw, x0 + int(round(cw_))), min(bh, y0 + int(round(ch_)))
        crop = Image.fromarray(big[y0:y1, x0:x1])
        return np.asarray(crop.resize((w, h), Image.BILINEAR))

    return VideoClip(frame, duration=duration)


def background_clip(path: Path | None, size: tuple[int, int], duration: float, seed: int, motion: str = "in"):
    from moviepy import VideoFileClip, vfx

    if path is None:
        return image_clip_kenburns(gradient_background(size, seed), size, duration, motion=motion)
    if path.suffix.lower() in IMAGE_EXT:
        with Image.open(path) as im:
            return image_clip_kenburns(im.convert("RGB"), size, duration, motion=motion)
    clip = VideoFileClip(str(path), audio=False)
    w, h = size
    s = max(w / clip.w, h / clip.h)
    clip = clip.resized(s)
    clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=w, height=h)
    if clip.duration < duration:
        clip = clip.with_effects([vfx.Loop(duration=duration)])
    return clip.subclipped(0, duration)


# ──────────────────────────────── 글자 ────────────────────────────────

def text_image(text: str, font_path: str, size: int, max_width: int, fill=(255, 255, 255),
               stroke=8, stroke_fill=(0, 0, 0), box: tuple | None = None, line_gap: float = 1.25) -> Image.Image:
    """한글 자막 이미지(RGBA). 폭에 맞춰 줄바꿈하고 테두리를 그린다."""
    font = ImageFont.truetype(font_path, size)
    avg = font.getlength("가")
    wrap = max(4, int(max_width / avg))
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width=wrap, break_long_words=True) or [""]
    widths = [font.getlength(line) for line in lines]
    lh = int(size * line_gap)
    pad = stroke + (24 if box else 0)
    W, H = int(max(widths)) + pad * 2, lh * len(lines) + pad * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if box:
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=24, fill=box)
    for i, (line, lw) in enumerate(zip(lines, widths)):
        d.text(((W - lw) / 2, pad + i * lh), line, font=font, fill=fill,
               stroke_width=stroke, stroke_fill=stroke_fill)
    return img


# ──────────────────────────────── 오디오 ────────────────────────────────

def duck_envelope(speech: list[tuple[float, float]], duration: float, base: float, duck: float,
                  attack: float = 0.12, release: float = 0.35, rate: int = 100):
    """말하는 구간은 duck, 쉬는 구간은 base 볼륨. 부드럽게 오르내리는 게인 곡선을 돌려준다."""
    n = int(duration * rate) + 2
    g = np.full(n, base, dtype=np.float32)
    for s, e in speech:
        g[max(0, int((s - attack) * rate)):min(n, int((e + release) * rate))] = duck
    # 이동 평균으로 갑작스러운 볼륨 변화를 없앤다
    k = max(1, int(0.2 * rate))
    g = np.convolve(np.pad(g, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    times = np.arange(len(g)) / rate
    return lambda t: np.interp(t, times, g)


def build_audio(tts: TTSResult, duration: float, bgm: str | None):
    from moviepy import AudioFileClip, CompositeAudioClip, afx

    voice = AudioFileClip(str(tts.audio_path))
    if not bgm:
        return voice, [voice]
    music = AudioFileClip(bgm)
    if music.duration < duration:
        music = music.with_effects([afx.AudioLoop(duration=duration)])
    music = music.subclipped(0, duration)
    gain = duck_envelope(tts.speech, duration, env_float("BGM_VOLUME", 0.30), env_float("BGM_DUCK_VOLUME", 0.08))

    def ducked(get_frame, t):
        frame = get_frame(t)
        g = gain(t)
        return frame * (g[:, None] if np.ndim(g) else g)

    music = music.transform(ducked, keep_duration=True)
    fade = min(1.5, duration / 4)
    music = music.with_effects([afx.AudioFadeIn(0.5), afx.AudioFadeOut(fade)])
    return CompositeAudioClip([music, voice]), [voice, music]


# ──────────────────────────────── 합성 ────────────────────────────────

class Layer:
    """미리 그려 둔 RGBA 이미지 한 장과 화면 위치. 필요한 영역만 섞어서 빠르다."""

    def __init__(self, img: Image.Image, x: int, y: int, size: tuple[int, int]):
        w, h = size
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + img.width), min(h, y + img.height)
        arr = np.asarray(img.convert("RGBA"))[y0 - y:y1 - y, x0 - x:x1 - x]
        self.box = (y0, y1, x0, x1)
        self.alpha = arr[..., 3:4].astype(np.uint16)
        self.rgb_a = arr[..., :3].astype(np.uint16) * self.alpha  # 미리 곱해 둔 색

    def blend(self, frame: np.ndarray) -> None:
        y0, y1, x0, x1 = self.box
        region = frame[y0:y1, x0:x1].astype(np.uint16)
        frame[y0:y1, x0:x1] = ((region * (255 - self.alpha) + self.rgb_a) // 255).astype(np.uint8)


def compose_video(script: VideoScript, tts: TTSResult, out_path: Path, bg: str | None = None,
                  bgm: str | None = None, preset: str = "veryfast", show_title: bool = True,
                  logger="bar", project_dir: Path | None = None) -> Path:
    """logger: moviepy(proglog) 진행 표시. "bar"=터미널 막대, None=조용히, 또는 ProgressBarLogger 객체."""
    from bisect import bisect_right

    from moviepy import VideoClip, concatenate_videoclips

    size = SIZES.get(script.video_type, SIZES["shorts"])
    w, h = size
    vertical = h > w
    font = find_font()
    duration = tts.duration + 0.4  # 마지막 숨 고르기
    backgrounds = list_backgrounds(bg)

    # 1) 장면별 배경 (장면 경계는 실제 음성 타이밍)
    bg_clips = []
    for i, sc in enumerate(script.scenes):
        end = script.scenes[i + 1].start if i + 1 < len(script.scenes) else duration
        scene_img = project_dir / sc.image if project_dir and sc.image else None
        if scene_img and scene_img.exists():  # AI 장면 이미지가 1순위
            src = scene_img
        else:
            src = backgrounds[i % len(backgrounds)] if backgrounds else None
        bg_clips.append(background_clip(src, size, max(0.1, end - sc.start),
                                        seed=zlib.crc32(f"{script.topic}-{i}".encode()),
                                        motion=MOTIONS[i % len(MOTIONS)]))
    base = concatenate_videoclips(bg_clips, method="chain")

    # 2) 고정 레이어: 아래쪽 어둡게(자막 가독성) + 상단 제목(쇼츠)
    static: list[Layer] = []
    shade_h = h // 2
    ramp = (np.linspace(0, 150, shade_h)[:, None, None] * np.ones((1, w, 1))).astype(np.uint8)
    shade = np.concatenate([np.zeros((shade_h, w, 3), np.uint8), ramp], axis=2)
    static.append(Layer(Image.fromarray(shade), 0, h - shade_h, size))
    if show_title and vertical:
        title = text_image(script.title, font, 70, int(w * 0.86), stroke=0, box=(0, 0, 0, 170))
        static.append(Layer(title, (w - title.width) // 2, int(h * 0.08), size))

    # 3) 자막 레이어 (음성 단어 타이밍에 맞춘 덩어리)
    cap_size = 84 if vertical else 64
    cap_y = int(h * (0.60 if vertical else 0.80))
    cues, starts = [], []
    for c in tts.cues:
        color = (255, 230, 0) if c.section == "hook" else (255, 255, 255)
        img = text_image(c.text, font, cap_size, int(w * 0.84), fill=color, stroke=10 if vertical else 7)
        cues.append((c.start, min(c.end, duration), Layer(img, (w - img.width) // 2, cap_y - img.height // 2, size)))
        starts.append(c.start)

    bar_h = 10 if vertical else 6

    def frame(t):
        f = np.array(base.get_frame(min(t, base.duration - 1e-3)), dtype=np.uint8)
        for layer in static:
            layer.blend(f)
        i = bisect_right(starts, t) - 1
        if i >= 0 and t < cues[i][1]:
            cues[i][2].blend(f)
        f[h - bar_h:, : int(w * min(1.0, t / duration))] = (255, 0, 64)  # 진행 막대
        return f

    video = VideoClip(frame, duration=duration)
    audio, to_close = build_audio(tts, duration, bgm)
    video = video.with_audio(audio)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(str(out_path), fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="192k",
                          preset=preset, threads=4, pixel_format="yuv420p",
                          ffmpeg_params=["-movflags", "+faststart"], logger=logger)
    for c in to_close + bg_clips:
        try:
            c.close()
        except Exception:
            pass
    return out_path


def make_thumbnail(script: VideoScript, out_path: Path, bg: str | None = None,
                   project_dir: Path | None = None) -> Path:
    """첫 장면 그림(AI 이미지 → 고른 배경 → 그라데이션) + 큰 제목으로 썸네일(JPG). 롱폼은 1280x720."""
    size = (1080, 1920) if script.video_type == "shorts" else (1280, 720)
    scene_imgs = [project_dir / sc.image for sc in script.scenes if project_dir and sc.image] if project_dir else []
    src = next((p for p in scene_imgs if p.exists()), None)
    if src is None:
        src = next((p for p in list_backgrounds(bg) if p.suffix.lower() in IMAGE_EXT), None)
    img = cover(Image.open(src), size) if src else gradient_background(size, 7)
    img = img.convert("RGBA")
    font = find_font()
    t = text_image(script.title, font, 120 if size[0] > size[1] else 110, int(size[0] * 0.9),
                   fill=(255, 230, 0), stroke=12)
    img.alpha_composite(t, ((size[0] - t.width) // 2, (size[1] - t.height) // 2))
    img.convert("RGB").save(out_path, quality=92)
    return out_path
