"""장면 이미지 테스트: Google 클라이언트를 흉내 내서 오프라인으로 확인한다."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import image_generator as ig  # noqa: E402
from modules import pipeline  # noqa: E402
from modules.script_generator import Scene, VideoScript, generate_script  # noqa: E402


def png(color=(200, 50, 50), size=(90, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeModels:
    def __init__(self, missing=(), blocked=False):
        self.calls, self.missing, self.blocked = [], set(missing), blocked

    def generate_content(self, model, contents, config):
        self.calls.append(("content", model, contents[0], config.image_config.aspect_ratio))
        if model in self.missing:
            raise RuntimeError(f"404 NOT_FOUND models/{model} is not found")
        if self.blocked:
            return SimpleNamespace(parts=[], prompt_feedback=SimpleNamespace(block_reason="SAFETY"), candidates=[])
        return SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=png()))])

    def generate_images(self, model, prompt, config):
        self.calls.append(("images", model, prompt, config.aspect_ratio))
        img = SimpleNamespace(image=SimpleNamespace(image_bytes=png((0, 120, 200))), rai_filtered_reason=None)
        return SimpleNamespace(generated_images=[img])

    def list(self):
        return [SimpleNamespace(name="models/gemini-9-flash-image"), SimpleNamespace(name="models/imagen-5.0-generate")]


def engine_with(models, model="gemini-2.5-flash-image"):
    e = ig.GoogleImageEngine.__new__(ig.GoogleImageEngine)
    e.api_key, e.model, e._checked = "k", model, False
    e.client = SimpleNamespace(models=models)
    return e


def script(vtype="shorts"):
    return VideoScript("난방비", vtype, "제목", "", [], [
        Scene("hook", "첫 장면", image_prompt="wide shot of a cozy Korean living room"),
        Scene("body", "둘째 장면", visual="보일러"),
    ])


def test_prompt_has_style_aspect_and_guard():
    p = ig.build_prompt("a cozy room", "photo", "9:16", "난방비")
    assert "photorealistic" in p and "vertical 9:16" in p and "No text" in p and "famous person" in p


def test_generate_scene_images_gemini_path(tmp_path):
    models = FakeModels()
    sc = script()
    res = ig.generate_scene_images(sc, tmp_path, engine=engine_with(models), workers=1)
    assert all(r.path for r in res) and len(res) == 2
    assert all(c[3] == "9:16" for c in models.calls)
    assert "보일러" in models.calls[1][2]  # image_prompt 가 없으면 visual 로 대신
    assert sc.scenes[0].image.startswith("images/") and (tmp_path / sc.scenes[0].image).exists()
    # 이미 있으면 건너뛰고, force 면 다시 만들며 예전 파일은 지운다
    assert ig.generate_scene_images(sc, tmp_path, engine=engine_with(models)) == []
    old = sc.scenes[0].image
    import time
    time.sleep(0.002)
    ig.generate_scene_images(sc, tmp_path, indices=[0], force=True, engine=engine_with(models))
    assert sc.scenes[0].image != old and not (tmp_path / old).exists()


def test_imagen_path_and_landscape(tmp_path):
    models = FakeModels()
    res = ig.generate_scene_images(script("long"), tmp_path, engine=engine_with(models, "imagen-4.0-generate-001"))
    assert all(r.path for r in res)
    assert models.calls[0][0] == "images" and models.calls[0][3] == "16:9"


def test_missing_model_falls_back_to_listed_model(tmp_path):
    models = FakeModels(missing={"gemini-2.5-flash-image"})
    eng = engine_with(models)
    res = ig.generate_scene_images(script(), tmp_path, engine=eng, workers=1)
    assert all(r.path for r in res) and eng.model == "gemini-9-flash-image"


def test_blocked_scene_reports_error_and_keeps_going(tmp_path):
    res = ig.generate_scene_images(script(), tmp_path, engine=engine_with(FakeModels(blocked=True)))
    assert all(r.path is None and "SAFETY" in r.error for r in res)


def test_no_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ig.ImageError, match="API 키"):
        ig.GoogleImageEngine()


def test_template_script_has_image_prompts_and_old_scripts_load():
    s = generate_script("난방비", "shorts", 30, provider="template")
    assert all(sc.image_prompt for sc in s.scenes)
    old = {"topic": "t", "video_type": "shorts", "title": "x", "description": "", "tags": [],
           "scenes": [{"section": "hook", "text": "a", "visual": "", "start": 0, "end": 1, "unknown": 1}]}
    assert VideoScript.from_dict(old).scenes[0].image == ""


def test_render_uses_dummy_scene_images(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_ENGINE", "dummy")
    monkeypatch.setenv("TTS_ENGINE", "dummy")
    sc = script()
    out = tmp_path / "p"
    out.mkdir()
    pipeline.save_script(sc, out)
    r = pipeline.render(sc, out, preset="ultrafast")
    assert r["image_errors"] == [] and all(s.image for s in sc.scenes)
    assert (out / "final.mp4").exists() and (out / "thumbnail.jpg").exists()
    assert pipeline.load_script(out).scenes[1].image == sc.scenes[1].image
