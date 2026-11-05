"""장면 이미지 생성 모듈 (Google Gemini / Imagen).

대본의 장면마다 image_prompt(영어 묘사)에 영상 전체 공통 그림체를 붙여 9:16 또는 16:9 이미지를 만든다.
결과는 프로젝트 폴더 images/scene_XX.png 에 저장하고 scene.image 에 경로를 적는다.

모델:
- gemini-*-image (기본)  : client.models.generate_content + response_modalities=["IMAGE"]
- imagen-*               : client.models.generate_images
설정한 모델이 없으면(이름이 바뀌었으면) 계정에서 쓸 수 있는 이미지 모델을 찾아 자동으로 바꾼다.
"""
from __future__ import annotations

import concurrent.futures as cf
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import env
from .script_generator import VideoScript

DEFAULT_MODEL = "gemini-2.5-flash-image"

# 영상 전체에 같은 그림체를 적용하는 공통 꼬리말
STYLES = {
    "photo": ("photorealistic photograph, shot on a full-frame camera with a 35mm lens, natural soft lighting, "
              "realistic skin and materials, subtle film grain, high detail, editorial documentary style"),
    "cinematic": ("cinematic film still, anamorphic lens, dramatic lighting, shallow depth of field, "
                  "color graded, photorealistic, high detail"),
    "webtoon": "Korean webtoon illustration style, clean line art, soft cel shading, vibrant colors",
    "3d": "3D rendered illustration, soft studio lighting, Pixar-like stylized characters, clean background",
}
STYLE_LABELS = {"photo": "실사 사진", "cinematic": "영화 장면", "webtoon": "웹툰 일러스트", "3d": "3D 일러스트"}
GUARD = ("No text, no letters, no captions, no watermark, no logos, no brand names. "
         "Do not depict any real, identifiable or famous person; all people are fictional.")

Progress = Callable[[str, float | None], None]


@dataclass
class ImageResult:
    index: int
    path: Path | None
    error: str = ""


class ImageError(RuntimeError):
    pass


def build_prompt(scene_prompt: str, style: str, aspect: str, topic: str) -> str:
    style_text = STYLES.get(style, style or STYLES["photo"])
    frame = "vertical 9:16 composition, subject centered with space at top and bottom" if aspect == "9:16" \
        else "horizontal 16:9 composition"
    return f"{scene_prompt.strip().rstrip('.')}. Context: a video about '{topic}'. {style_text}, {frame}. {GUARD}"


class GoogleImageEngine:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or env("GEMINI_API_KEY") or env("GOOGLE_API_KEY")
        if not self.api_key:
            raise ImageError("Google API 키가 없습니다. 설정 화면에서 「Google(Gemini) API 키」를 넣으세요 "
                             "(aistudio.google.com 에서 무료로 발급).")
        self.model = model or env("GEMINI_IMAGE_MODEL", DEFAULT_MODEL)
        from google import genai

        self.client = genai.Client(api_key=self.api_key)
        self._checked = False

    # 모델 이름이 바뀌었을 때를 대비해 쓸 수 있는 이미지 모델을 고른다
    def _pick_available(self) -> str | None:
        try:
            names = [m.name.split("/")[-1] for m in self.client.models.list()]
        except Exception:
            return None
        image = [n for n in names if "image" in n and "gemini" in n and "preview" not in n] or \
                [n for n in names if "image" in n and "gemini" in n] or [n for n in names if n.startswith("imagen")]
        return sorted(image)[-1] if image else None

    def generate(self, prompt: str, aspect: str) -> bytes:
        try:
            return self._generate(self.model, prompt, aspect)
        except Exception as e:
            if self._checked or not _looks_like_missing_model(e):
                raise
            self._checked = True
            alt = self._pick_available()
            if not alt or alt == self.model:
                raise
            self.model = alt
            return self._generate(alt, prompt, aspect)

    def _generate(self, model: str, prompt: str, aspect: str) -> bytes:
        from google.genai import types

        if model.startswith("imagen"):
            r = self.client.models.generate_images(model=model, prompt=prompt, config=types.GenerateImagesConfig(
                number_of_images=1, aspect_ratio=aspect, person_generation="ALLOW_ADULT"))
            imgs = r.generated_images or []
            if not imgs or not imgs[0].image or not imgs[0].image.image_bytes:
                reason = imgs[0].rai_filtered_reason if imgs else ""
                raise ImageError(f"이미지가 안전 필터에 걸렸습니다. 장면 묘사를 바꿔 보세요. {reason or ''}".strip())
            return imgs[0].image.image_bytes
        r = self.client.models.generate_content(model=model, contents=[prompt], config=types.GenerateContentConfig(
            response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio=aspect)))
        for part in (r.parts or []):
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
        fb = getattr(r, "prompt_feedback", None)
        why = getattr(fb, "block_reason", None) if fb else None
        if not why and r.candidates:
            why = r.candidates[0].finish_reason
        raise ImageError(f"이미지를 받지 못했습니다 ({why or '사유 없음'}). 장면 묘사를 바꿔 보세요.")


def _looks_like_missing_model(e: Exception) -> bool:
    text = str(e).lower()
    return "not found" in text or "404" in text or "is not supported" in text


class DummyImageEngine:
    """인터넷·키 없이 흐름을 시험하는 가짜 엔진: 묘사 글을 적은 그라데이션 그림을 돌려준다 (실제 AI 그림 아님)."""
    model = "dummy"

    def generate(self, prompt: str, aspect: str) -> bytes:
        import io
        import zlib

        from .config import find_font
        from .video_composer import gradient_background, text_image

        size = (720, 1280) if aspect == "9:16" else (1280, 720)
        img = gradient_background(size, zlib.crc32(prompt.encode())).convert("RGBA")
        label = text_image("테스트 이미지\n" + prompt.split(".")[0][:80], find_font(), 34, int(size[0] * 0.8),
                           stroke=0, box=(0, 0, 0, 120))
        img.alpha_composite(label, ((size[0] - label.width) // 2, (size[1] - label.height) // 2))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        return buf.getvalue()


def get_engine(model: str | None = None):
    if env("IMAGE_ENGINE", "google").lower() == "dummy":
        return DummyImageEngine()
    return GoogleImageEngine(model=model)


def image_available() -> bool:
    return env("IMAGE_ENGINE", "google").lower() == "dummy" or bool(env("GEMINI_API_KEY") or env("GOOGLE_API_KEY"))


def generate_scene_images(script: VideoScript, out: Path, style: str | None = None,
                          indices: list[int] | None = None, force: bool = False,
                          engine=None, progress: Progress | None = None,
                          workers: int = 3) -> list[ImageResult]:
    """장면 이미지를 만든다. indices 를 주면 그 장면만, force=False 면 이미 있는 장면은 건너뛴다."""
    progress = progress or (lambda m, f=None: None)
    style = style or env("IMAGE_STYLE", "photo")
    aspect = "9:16" if script.video_type == "shorts" else "16:9"
    folder = out / "images"
    folder.mkdir(parents=True, exist_ok=True)
    todo = []
    for i, sc in enumerate(script.scenes):
        if indices is not None and i not in indices:
            continue
        if not force and sc.image and (out / sc.image).exists():
            continue
        todo.append(i)
    if not todo:
        return []
    engine = engine or get_engine()
    results: list[ImageResult] = []
    done = 0
    progress(f"장면 이미지 만드는 중… (0/{len(todo)})", 0.0)

    def one(i: int) -> ImageResult:
        sc = script.scenes[i]
        base = sc.image_prompt or f"a scene illustrating: {sc.visual or sc.text}"
        prompt = build_prompt(base, style, aspect, script.topic)
        last = None
        for attempt in range(3):  # 일시적인 서버 오류만 다시 시도
            try:
                data = engine.generate(prompt, aspect)
                path = folder / f"scene_{i:02d}_{int(time.time() * 1000) % 100000}.png"
                _save_png(data, path)
                return ImageResult(i, path)
            except ImageError as e:
                return ImageResult(i, None, str(e))
            except Exception as e:  # noqa: BLE001
                last = e
                if not _retryable(e):
                    break
                time.sleep(2 * (attempt + 1))
        return ImageResult(i, None, _friendly(last))

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for res in pool.map(one, todo):
            done += 1
            results.append(res)
            if res.path:
                old = script.scenes[res.index].image
                script.scenes[res.index].image = res.path.relative_to(out).as_posix()
                if old and old != script.scenes[res.index].image:
                    (out / old).unlink(missing_ok=True)  # 다시 만든 장면의 예전 그림 지우기
            progress(f"장면 이미지 만드는 중… ({done}/{len(todo)})", done / len(todo))
    return results


def _save_png(data: bytes, path: Path) -> None:
    """받은 바이트(PNG/JPEG/WEBP)를 PNG 로 저장한다."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im.convert("RGB").save(path, "PNG")


def _retryable(e: Exception) -> bool:
    text = str(e).lower()
    return any(k in text for k in ("500", "502", "503", "504", "unavailable", "deadline", "timeout", "429", "resource_exhausted"))


def _friendly(e: Exception | None) -> str:
    text = str(e or "알 수 없는 오류")
    low = text.lower()
    if "api key not valid" in low or "api_key_invalid" in low or "permission" in low:
        return "Google API 키가 맞지 않거나 권한이 없습니다. 설정에서 키를 확인하세요."
    if "429" in low or "resource_exhausted" in low or "quota" in low:
        return "Google 이미지 사용 한도에 걸렸습니다. 잠시 뒤 다시 시도하거나 결제(요금제)를 확인하세요."
    if "billing" in low:
        return "이 이미지 모델은 Google 결제 설정이 필요합니다 (AI Studio → 결제)."
    return text[:300]
