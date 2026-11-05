"""TubeForge 앱 서버 (127.0.0.1 전용, 실행할 때마다 새 토큰).

화면(static/)은 이 서버의 /api/* 를 부르고, 오래 걸리는 일(대본·렌더링·업로드)은
작업(job)으로 한 줄씩 차례대로 처리한다. 화면은 /api/jobs/<id> 를 주기적으로 물어 진행률을 그린다.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from modules import pipeline
from modules.config import ROOT, env

STATIC = Path(__file__).resolve().parent / "static"
ASSETS = ROOT / "assets"
ENV_FILE = ROOT / ".env"

# 한국어 edge-tts 음성 (이름, 설명)
VOICES = [
    ("ko-KR-SunHiNeural", "선희 · 여성 · 밝고 또렷함"),
    ("ko-KR-InJoonNeural", "인준 · 남성 · 차분함"),
    ("ko-KR-HyunsuMultilingualNeural", "현수 · 남성 · 자연스러운 대화체"),
]

# 설정 화면에서 고칠 수 있는 .env 항목 (키 값은 화면에 다시 보내지 않는다)
SETTINGS = [
    ("SCRIPT_PROVIDER", "대본 AI", "auto"),
    ("ANTHROPIC_API_KEY", "Claude API 키", ""),
    ("CLAUDE_MODEL", "Claude 모델", "claude-opus-5-5"),
    ("OPENAI_API_KEY", "OpenAI API 키", ""),
    ("OPENAI_MODEL", "OpenAI 모델", "gpt-4o-mini"),
    ("OLLAMA_HOST", "Ollama 주소", "http://127.0.0.1:11434"),
    ("OLLAMA_MODEL", "Ollama 모델", "qwen3:8b"),
    ("GEMINI_API_KEY", "Google(Gemini) API 키", ""),
    ("GEMINI_IMAGE_MODEL", "이미지 모델", "gemini-2.5-flash-image"),
    ("IMAGE_STYLE", "그림체", "photo"),
    ("TTS_ENGINE", "음성 엔진", "edge"),
    ("EDGE_VOICE", "기본 목소리", "ko-KR-SunHiNeural"),
    ("EDGE_RATE", "말하기 속도", "+10%"),
    ("ELEVENLABS_API_KEY", "ElevenLabs API 키", ""),
    ("ELEVENLABS_VOICE_ID", "ElevenLabs 목소리 ID", ""),
    ("BGM_VOLUME", "BGM 볼륨(말 없을 때)", "0.30"),
    ("BGM_DUCK_VOLUME", "BGM 볼륨(말할 때)", "0.08"),
    ("FONT_PATH", "자막 폰트 경로", ""),
]
SECRET_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY"}


class Job:
    def __init__(self, kind: str, project: str | None):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.project = kind, project
        self.status, self.message, self.progress = "queued", "대기 중", None
        self.result, self.error, self.started = None, None, time.time()

    def update(self, message: str, progress: float | None = None):
        self.message = message
        if progress is not None:
            self.progress = round(progress, 3)

    def to_json(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project": self.project, "status": self.status,
                "message": self.message, "progress": self.progress, "result": self.result, "error": self.error,
                "elapsed": round(time.time() - self.started, 1)}


class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(16)
        self.jobs: dict[str, Job] = {}
        self.queue: queue.Queue = queue.Queue()
        self.last_ping = 0.0
        threading.Thread(target=self._worker, daemon=True).start()

    # ── 작업 ──
    def submit(self, kind: str, project: str | None, fn) -> Job:
        job = Job(kind, project)
        self.jobs[job.id] = job
        self.queue.put((job, fn))
        return job

    def _worker(self):
        while True:
            job, fn = self.queue.get()
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as e:  # noqa: BLE001 — 화면에 알려 주고 계속 돈다
                traceback.print_exc()
                job.status, job.error = "error", friendly(e)
                job.message = "실패"

    def busy_project(self, pid: str) -> Job | None:
        return next((j for j in self.jobs.values() if j.project == pid and j.status in ("queued", "running")), None)

    # ── 상태 ──
    def state(self) -> dict:
        from modules.image_generator import STYLE_LABELS, image_available
        from modules.script_generator import pick_provider

        return {
            "provider": env("SCRIPT_PROVIDER", "auto"),
            "provider_auto": pick_provider("auto"),
            "voices": [{"id": v, "label": label} for v, label in VOICES],
            "default_voice": env("EDGE_VOICE", "ko-KR-SunHiNeural"),
            "default_rate": env("EDGE_RATE", "+10%"),
            "tts": env("TTS_ENGINE", "edge"),
            "images_ready": image_available(),
            "image_style": env("IMAGE_STYLE", "photo"),
            "image_styles": STYLE_LABELS,
            "assets": list_assets(),
            "youtube_ready": (ROOT / env("YOUTUBE_CLIENT_SECRETS", "client_secret.json")).exists(),
            "jobs": [j.to_json() for j in self.jobs.values() if j.status in ("queued", "running")],
        }


def friendly(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    if "speech.platform.bing.com" in msg or "edge-tts" in msg.lower():
        return "음성 서버(Microsoft)에 연결하지 못했습니다. 인터넷 연결을 확인하세요 (회사망이면 설정의 EDGE_PROXY)."
    if "11434" in msg:
        return "Ollama 에 연결하지 못했습니다. Ollama 를 켜거나 설정에서 다른 대본 AI 를 고르세요."
    return msg[:500]


def list_assets() -> dict:
    out = {}
    for kind, exts in (("backgrounds", {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}),
                       ("bgm", {".mp3", ".wav", ".m4a", ".ogg"})):
        d = ASSETS / kind
        out[kind] = sorted(f.name for f in d.iterdir() if f.suffix.lower() in exts) if d.exists() else []
    return out


def read_env() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)", line)
            if m:
                values[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip()
    return values


def write_env(changes: dict) -> None:
    """.env 의 해당 줄만 바꾸고(없으면 추가) 나머지 줄과 주석은 그대로 둔다."""
    import os

    if not ENV_FILE.exists() and (ROOT / ".env.example").exists():
        shutil.copy(ROOT / ".env.example", ENV_FILE)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in changes:
            lines[i] = f"{m.group(1)}={changes[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in changes.items() if k not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in changes.items():  # 다시 켜지 않아도 바로 적용
        os.environ[k] = v


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[\w\-가-힣]+", pid or ""):
        raise ValueError("잘못된 프로젝트 이름")
    d = pipeline.OUTPUT / pid
    if not (d / "script.json").exists():
        raise FileNotFoundError("프로젝트를 찾을 수 없습니다")
    return d


def project_json(pid: str) -> dict:
    d = project_dir(pid)
    script = pipeline.load_script(d)
    files = {name: (d / name).exists() for name in ("final.mp4", "thumbnail.jpg", "captions.srt")}
    return {"id": pid, "script": script.to_dict(), "meta": pipeline.load_meta(d), "files": files,
            "timestamps": script.timestamps()}


def asset_path(kind: str, name: str | None) -> str | None:
    if not name:
        return None
    p = (ASSETS / kind / Path(name).name)
    if not p.exists():
        raise FileNotFoundError(f"소재 파일이 없습니다: {name}")
    return str(p)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # 조용히
            pass

        # ── 응답 도우미 ──
        def send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def json(self, data, status: int = 200):
            self.send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def authed(self, query: dict) -> bool:
            return self.headers.get("X-Token") == app.token or query.get("t", [""])[0] == app.token

        # ── GET ──
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = unquote(u.path)
            if not path.startswith("/api/") and not path.startswith("/files/"):
                return self.static(path)
            if not self.authed(q):
                return self.json({"error": "인증 실패 — 앱을 다시 실행하세요."}, 403)
            try:
                if path == "/api/state":
                    app.last_ping = time.time()
                    return self.json(app.state())
                if path == "/api/projects":
                    return self.json(pipeline.list_projects())
                m = re.fullmatch(r"/api/projects/([^/]+)", path)
                if m:
                    return self.json(project_json(m.group(1)))
                m = re.fullmatch(r"/api/jobs/(\w+)", path)
                if m:
                    job = app.jobs.get(m.group(1))
                    return self.json(job.to_json() if job else {"error": "작업 없음"}, 200 if job else 404)
                if path == "/api/settings":
                    cur = read_env()
                    return self.json([{"key": k, "label": label,
                                       "value": "" if k in SECRET_KEYS else cur.get(k, default),
                                       "secret": k in SECRET_KEYS, "set": bool(cur.get(k))}
                                      for k, label, default in SETTINGS])
                m = re.fullmatch(r"/files/(?!preview/)([^/]+)/(.+)", path)
                if m:
                    return self.file(project_dir(m.group(1)) / m.group(2), project_dir(m.group(1)))
                m = re.fullmatch(r"/files/preview/(\w+\.mp3)", path)
                if m:  # 목소리 미리듣기 (output/_preview)
                    return self.file(pipeline.OUTPUT / "_preview" / m.group(1), pipeline.OUTPUT / "_preview")
                return self.json({"error": "없는 주소"}, 404)
            except (FileNotFoundError, ValueError) as e:
                return self.json({"error": str(e)}, 404)

        def static(self, path: str):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (STATIC / name).resolve()
            if STATIC not in f.parents or not f.is_file():
                return self.send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self.send(200, f.read_bytes(), ctype)

        def file(self, f: Path, root: Path):
            """영상 탐색(seek)이 되도록 Range 요청을 지원한다."""
            f = f.resolve()
            if root.resolve() not in f.parents or not f.is_file():
                return self.json({"error": "파일 없음"}, 404)
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if f.suffix == ".srt":
                ctype = "text/plain; charset=utf-8"
            rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            start, end = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = int(rng.group(2)) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                end = min(end, size - 1)
            length = end - start + 1
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        # ── POST / PUT / DELETE ──
        def do_POST(self):
            self.write("POST")

        def do_PUT(self):
            self.write("PUT")

        def do_DELETE(self):
            self.write("DELETE")

        def write(self, method: str):
            u = urlparse(self.path)
            path = unquote(u.path)
            if not self.authed(parse_qs(u.query)):
                return self.json({"error": "인증 실패 — 앱을 다시 실행하세요."}, 403)
            try:
                if method == "POST" and path.startswith("/api/assets/"):
                    return self.upload_asset(path.rsplit("/", 1)[-1])
                data = json.loads(self.body() or b"{}")
                return self.route(method, path, data)
            except (FileNotFoundError, ValueError, KeyError) as e:
                return self.json({"error": str(e)}, 400)

        def route(self, method: str, path: str, d: dict):
            if method == "POST" and path == "/api/projects":
                topic = (d.get("topic") or "").strip()
                if not topic:
                    raise ValueError("주제를 입력하세요.")
                vtype = d.get("type") if d.get("type") in ("shorts", "long") else "shorts"
                seconds = int(d.get("seconds") or (30 if vtype == "shorts" else 300))
                provider = d.get("provider") or "auto"
                source = (d.get("source") or "").strip() or None

                def run(job: Job):
                    script, out = pipeline.make_script(topic, vtype, seconds, provider, source, None, None,
                                                       job.update)
                    job.project = out.name
                    return {"project": out.name, "provider": script.provider}

                return self.json(app.submit("script", None, run).to_json())

            if method == "PUT" and (m := re.fullmatch(r"/api/projects/([^/]+)/script", path)):
                d0 = project_dir(m.group(1))
                script = pipeline.load_script(d0)
                script.title = (d.get("title") or script.title).strip()
                script.description = d.get("description", script.description)
                script.tags = [t.strip() for t in d.get("tags", script.tags) if t.strip()]
                if "scenes" in d:
                    from modules.script_generator import Scene

                    def image_of(v):  # 프로젝트 안 images/ 의 실제 파일만 인정
                        v = (v or "").strip()
                        ok = re.fullmatch(r"images/[\w.\-]+\.png", v) and (d0 / v).exists()
                        return v if ok else ""

                    script.scenes = [Scene(section=s.get("section", "body"), text=s["text"].strip(),
                                           visual=s.get("visual", ""), image_prompt=(s.get("image_prompt") or "").strip(),
                                           image=image_of(s.get("image")))
                                     for s in d["scenes"] if s.get("text", "").strip()]
                    if not script.scenes:
                        raise ValueError("장면이 하나 이상 있어야 합니다.")
                    script.estimate_timings()
                pipeline.save_script(script, d0)
                return self.json(project_json(m.group(1)))

            if method == "POST" and (m := re.fullmatch(r"/api/projects/([^/]+)/images", path)):
                pid = m.group(1)
                d0 = project_dir(pid)
                if app.busy_project(pid):
                    raise ValueError("이 프로젝트는 이미 작업 중입니다.")
                indices = d.get("indices")
                if indices is not None:
                    indices = [int(i) for i in indices]
                force = bool(d.get("force"))

                def run(job: Job):
                    script = pipeline.load_script(d0)
                    failed = pipeline.make_images(script, d0, indices=indices, force=force, progress=job.update)
                    return {"project": pid, "failed": failed}

                return self.json(app.submit("images", pid, run).to_json())

            if method == "POST" and (m := re.fullmatch(r"/api/projects/([^/]+)/render", path)):
                pid = m.group(1)
                d0 = project_dir(pid)
                if app.busy_project(pid):
                    raise ValueError("이 프로젝트는 이미 작업 중입니다.")
                bg = asset_path("backgrounds", d.get("bg"))
                bgm = asset_path("bgm", d.get("bgm"))
                opts = dict(tts=d.get("tts") or None, voice=d.get("voice") or None, rate=d.get("rate") or None,
                            bg=bg, bgm=bgm, preset=d.get("preset") or "veryfast",
                            images=d.get("images") if isinstance(d.get("images"), bool) else None)

                def run(job: Job):
                    script = pipeline.load_script(d0)
                    r = pipeline.render(script, d0, progress=job.update, **opts)
                    return {"project": pid, "duration": round(r["duration"], 1), "image_errors": r["image_errors"]}

                return self.json(app.submit("render", pid, run).to_json())

            if method == "POST" and (m := re.fullmatch(r"/api/projects/([^/]+)/upload", path)):
                pid = m.group(1)
                d0 = project_dir(pid)
                if not (d0 / "final.mp4").exists():
                    raise ValueError("먼저 영상을 만드세요.")
                privacy = d.get("privacy") if d.get("privacy") in ("private", "unlisted", "public") else "private"
                publish_at = (d.get("publish_at") or "").strip() or None

                def run(job: Job):
                    vid = pipeline.upload(pipeline.load_script(d0), d0, privacy, publish_at, job.update)
                    return {"project": pid, "video_id": vid, "url": f"https://youtu.be/{vid}"}

                return self.json(app.submit("upload", pid, run).to_json())

            if method == "DELETE" and (m := re.fullmatch(r"/api/projects/([^/]+)", path)):
                pid = m.group(1)
                if app.busy_project(pid):
                    raise ValueError("작업 중인 프로젝트는 지울 수 없습니다.")
                shutil.rmtree(project_dir(pid))
                return self.json({"ok": True})

            if method == "POST" and path == "/api/voice-preview":
                text = (d.get("text") or "안녕하세요. 이 목소리로 영상을 만들어 드릴게요.")[:120]

                def run(job: Job):
                    from modules.tts_engine import get_engine

                    folder = pipeline.OUTPUT / "_preview"
                    folder.mkdir(parents=True, exist_ok=True)
                    name = f"{uuid.uuid4().hex[:8]}.mp3"
                    eng = get_engine(d.get("tts") or None, d.get("voice") or None, d.get("rate") or None)
                    sa = eng.synthesize_scene(text, folder / name)
                    if not sa.path:
                        raise ValueError("이 음성 엔진은 미리듣기를 지원하지 않습니다.")
                    return {"url": f"/files/preview/{name}"}

                return self.json(app.submit("preview", None, run).to_json())

            if method == "PUT" and path == "/api/settings":
                allowed = {k for k, _, _ in SETTINGS}
                changes = {k: str(v).strip() for k, v in d.items() if k in allowed}
                changes = {k: v for k, v in changes.items() if not (k in SECRET_KEYS and v == "")}  # 빈칸 = 그대로
                for k, v in changes.items():
                    if "\n" in v:
                        raise ValueError(f"{k} 값에 줄바꿈이 있습니다.")
                write_env(changes)
                return self.json({"ok": True, "saved": sorted(changes)})

            return self.json({"error": "없는 주소"}, 404)

        def upload_asset(self, kind: str):
            if kind not in ("backgrounds", "bgm"):
                raise ValueError("잘못된 소재 종류")
            name = Path(unquote(self.headers.get("X-Filename", ""))).name
            if not name or not re.search(r"\.(jpe?g|png|webp|mp4|mov|webm|mp3|wav|m4a|ogg)$", name, re.I):
                raise ValueError("이미지(jpg/png/webp), 영상(mp4/mov/webm), 음악(mp3/wav/m4a/ogg)만 올릴 수 있습니다.")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 500 * 1024 * 1024:
                raise ValueError("500MB 이하 파일만 올릴 수 있습니다.")
            d = ASSETS / kind
            d.mkdir(parents=True, exist_ok=True)
            with open(d / name, "wb") as fh:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            return self.json({"ok": True, "name": name, "assets": list_assets()})

    return Handler


def create_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.daemon_threads = True
    return server
