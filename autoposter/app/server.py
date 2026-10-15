"""앱 화면이 쓰는 로컬 서버 (127.0.0.1 전용).

화면(웹 페이지)은 /api/... 로 요청하고, 오래 걸리는 일(로그인, 카테고리, 글쓰기, 발행,
모델 내려받기)은 '작업(job)'으로 만들어 백그라운드에서 돌린 뒤 화면이 진행 상황을 묻는다.
블로그 작업과 AI 작업은 각각 전용 스레드 하나에서 차례로 처리한다
(Playwright 브라우저는 만든 스레드에서만 쓸 수 있기 때문).
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import secrets
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import config, factcheck, local_ai, style, web
from ..cli import PLATFORMS, _has_target, open_platform, parse_tags, post_from_text
from ..models import Category, Post
from ..platforms.base import PlatformError
from ..writer import WriterError, write_post
from .store import PostStore

STATIC_DIR = Path(__file__).parent / "static"
CLAUDE_MODELS = {
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5", "note": "유료 · 빠르고 저렴"},
    "claude-opus-5-5": {"label": "Claude Opus 5.5", "note": "유료 · 최고 품질"},
}
DEFAULT_ENGINE = f"local:{local_ai.DEFAULT_MODEL}"


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind: str, message: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "running"  # running | input | done | error
        self.message = message
        self.progress: float | None = None
        self.prompt: dict | None = None
        self.result = None
        self.error: str | None = None
        self._answer = queue.Queue()
        self._seq = 0
        self.started = time.time()

    def to_json(self) -> dict:
        data = {k: getattr(self, k) for k in ("id", "kind", "state", "message", "progress", "prompt", "result", "error")}
        data["elapsed"] = round(time.time() - self.started, 1)
        return data

    def update(self, message: str | None = None, progress: float | None = None):
        if message is not None:
            self.message = message
        self.progress = progress

    def ask(self, prompt: dict):
        """작업 스레드에서 화면에 질문을 띄우고 답을 기다린다."""
        self._seq += 1
        self.prompt = dict(prompt, seq=self._seq)
        self.state = "input"
        answer = self._answer.get()
        self.prompt = None
        self.state = "running"
        if answer is None:
            raise Cancelled()
        return answer

    def answer(self, value):
        self._answer.put(value)


class Runner:
    """작업을 스레드 하나에서 차례로 처리한다."""

    def __init__(self, name: str):
        self.tasks: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self.thread.start()

    def submit(self, fn):
        self.tasks.put(fn)

    def call(self, fn, timeout: float = 30):
        """작업 스레드에서 fn을 실행하고 끝날 때까지 기다린다."""
        done = threading.Event()
        box = {}

        def run():
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            done.set()

        self.submit(run)
        done.wait(timeout)
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _loop(self):
        while True:
            fn = self.tasks.get()
            if fn is None:
                return
            fn()

    def stop(self):
        self.tasks.put(None)


class App:
    def __init__(self, platform_factory=None, writers=None):
        self.cfg = config.load()
        self.store = PostStore()
        self.token = secrets.token_urlsafe(16)
        self.jobs: dict[str, Job] = {}
        self.platform_runner = Runner("platform")
        self.ai_runner = Runner("ai")
        self.platform_factory = platform_factory or open_platform
        self.writers = writers or {"local": local_ai.write_post_local, "claude": write_post}
        self.refiner = style.refine
        self.style_analyzer = style.analyze
        self.fact_checker = lambda engine, post, refs, progress: factcheck.run(
            engine, post, refs, progress, fetch=self.fetch
        )
        self.platform = None  # platform 스레드에서만 다룬다
        self.platform_key = None
        self.categories: list[Category] = []
        # 앱 창과 열어 둔 연결(/api/events) 수. 0이 된 채로 시간이 지나면 창이 닫힌 것으로 본다.
        self.clients = 0
        self.ever_connected = False
        self.last_disconnect = time.time()
        self.stopping = False
        self._clients_lock = threading.Lock()
        self._load_api_key()
        self.switch_platform(self.cfg.get("last_platform") or "naver")

    def client_connected(self):
        with self._clients_lock:
            self.clients += 1
            self.ever_connected = True
        log(f"앱 창 연결됨 (연결 {self.clients}개)")

    def client_disconnected(self):
        with self._clients_lock:
            self.clients -= 1
            self.last_disconnect = time.time()
        log(f"앱 창 연결 끊김 (연결 {self.clients}개)")

    # ---- 상태 ---------------------------------------------------------------

    def state(self) -> dict:
        key = self.platform_key
        return {
            "platforms": [
                {"key": k, "name": name, "target": _target(self.cfg.get(k, {}))} for k, (name, _, _) in PLATFORMS.items()
            ],
            "platform": key,
            "categories": [_category_json(c) for c in self.categories],
            "engines": self.engines(),
            "engine": self.cfg.get("engine", DEFAULT_ENGINE),
            "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "style": self.cfg.get("style") or {},
            "refine_enabled": bool(self.cfg.get("refine_enabled")),
            "posts": self.store.all(),
        }

    def engines(self) -> list[dict]:
        items = [
            {"id": f"local:{m}", "kind": "local", "label": f"내 PC AI · {info['label']}", "note": f"무료 · {info['note']}",
             "size": info["size"], "model": m}
            for m, info in local_ai.MODELS.items()
        ]
        items += [
            {"id": f"claude:{m}", "kind": "claude", "label": info["label"], "note": info["note"], "model": m}
            for m, info in CLAUDE_MODELS.items()
        ]
        return items

    # ---- 블로그 -------------------------------------------------------------

    def switch_platform(self, key: str):
        if key not in PLATFORMS:
            raise PlatformError("알 수 없는 블로그 종류입니다.")
        self.cfg["last_platform"] = key
        self.platform_key = key
        self.categories = []
        config.save(self.cfg)

        def switch():
            if self.platform is not None:
                self.platform.close()
            self.platform = self.platform_factory(key, self.cfg)

        self.platform_runner.submit(switch)

    def start_job(self, kind: str, message: str, fn, runner: Runner) -> Job:
        job = Job(kind, message)
        self.jobs[job.id] = job

        log(f"작업 시작: {kind} ({job.id})")

        def run():
            job.started = time.time()  # 앞 작업을 기다린 시간은 빼고 잰다
            try:
                job.result = fn(job)
                job.state = "done"
                job.message = "완료"
            except Cancelled:
                job.state, job.error = "error", "취소했습니다."
            except (PlatformError, WriterError) as exc:
                job.state, job.error = "error", str(exc)
            except Exception as exc:  # noqa: BLE001
                log_error(exc)
                job.state = "error"
                job.error = friendly_error(exc)
            job.progress = None
            log(f"작업 끝: {kind} ({job.id}) {job.state} {time.time() - job.started:.1f}초 {job.error or ''}")

        runner.submit(run)
        return job

    def job_login(self, job: Job):
        def prompt(question, secret=False, allow_empty=False, default=None):
            kind = "confirm" if "Enter를 누르세요" in question else "text"
            while True:
                answer = str(job.ask({"question": question, "secret": secret, "kind": kind, "default": default})).strip()
                if answer or allow_empty or kind == "confirm":
                    return answer
                if default is not None:
                    return default

        job.update("접속하는 중... 브라우저 창이 열리면 로그인해 주세요")
        self.platform.login(prompt)
        config.save(self.cfg)
        job.update("카테고리를 불러오는 중...")
        return self._load_categories()

    def job_categories(self, job: Job):
        if not _has_target(self.platform) or not self.platform.is_logged_in():
            raise PlatformError("먼저 [접속하기]를 눌러 블로그에 접속해 주세요.")
        return self._load_categories()

    def _load_categories(self):
        self.categories = self.platform.get_categories()
        if not self.categories:
            raise PlatformError("카테고리를 찾지 못했습니다. 블로그에 카테고리를 먼저 만들어 주세요.")
        return [_category_json(c) for c in self.categories]

    def job_publish(self, job: Job, post_id: str, draft: bool):
        post = self.store.get(post_id)
        if not post:
            raise PlatformError("글을 찾지 못했습니다.")
        if not post.get("category"):
            raise PlatformError("글의 카테고리를 골라 주세요.")
        if post.get("platform") != self.platform_key:
            name = PLATFORMS.get(post.get("platform"), ("다른 블로그",))[0]
            raise PlatformError(f"이 글은 {name}용 카테고리로 만들었습니다. 글 편집 창에서 카테고리를 다시 골라 주세요.")
        if not _has_target(self.platform) or not self.platform.is_logged_in():
            raise PlatformError("먼저 [접속하기]를 눌러 블로그에 접속해 주세요.")
        c = post["category"]
        category = Category(id=c["id"], name=c["name"], parent=c.get("parent"))
        job.update(f"{PLATFORMS[self.platform_key][0]}에 {'임시저장' if draft else '발행'}하는 중...")
        result = self.platform.publish(Post(post["title"], post["html"], post["tags"]), category, draft=draft)
        return self.store.update(post_id, status="saved" if draft else "published", url=result.url,
                                 published_at=time.time())

    # ---- AI -----------------------------------------------------------------

    def check_engine(self, engine: str) -> tuple[str, str]:
        kind, _, model = (engine or "").partition(":")
        if kind == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise WriterError("Claude를 쓰려면 설정에서 API 키를 넣어 주세요. 키 없이 쓰려면 '내 PC AI'를 고르세요.")
        if kind == "local":
            st = local_ai.status()
            if not st["running"]:
                raise WriterError("내 PC AI(Ollama)가 꺼져 있습니다. 왼쪽 AI 엔진 칸의 안내를 따라 켜 주세요.")
            if not local_ai.has_model(model, st["models"]):
                raise WriterError(f"'{model}' 모델이 아직 없습니다. [모델 내려받기]를 먼저 눌러 주세요.")
        if kind not in ("local", "claude"):
            raise WriterError("AI 엔진을 골라 주세요.")
        return kind, model

    def style_for_writing(self) -> dict | None:
        st = self.cfg.get("style") or {}
        return st if st.get("enabled") and st.get("guide") else None

    @staticmethod
    def fetch(url: str):
        return web.fetch_text(url, render=web.render_with_browser)

    def reference_text(self, raw: str) -> str:
        """참고 자료 칸의 글 + 주소에서 읽어 온 글을 하나로 합친다."""
        parts = []
        for ref in factcheck.load_references(raw, self.fetch):
            head = f"[자료: {ref['title']}{' · ' + ref['url'] if ref['url'] else ''}]"
            parts.append(f"{head}\n{ref['text'][:3500]}")
        return "\n\n".join(parts)

    def job_write(self, job: Job, params: dict):
        engine = params.get("engine") or DEFAULT_ENGINE
        category = next((c for c in self.categories if c.label == params.get("category")), None)
        if not category:
            raise PlatformError("카테고리를 먼저 불러와 골라 주세요.")
        kind, model = self.check_engine(engine)
        self.cfg["engine"] = engine
        config.save(self.cfg)
        raw_refs = (params.get("references") or "").strip()
        references = None
        if raw_refs:
            job.update("참고 자료를 읽는 중...")
            references = self.reference_text(raw_refs)
        writing_style = self.style_for_writing()
        job.update("AI가 글을 쓰는 중... (내 PC AI는 몇 분 걸릴 수 있습니다)")
        length = int(params.get("length") or 2000)
        post = self.writers[kind](
            category=category.name, topic=params.get("topic") or None, tone=params.get("tone") or "친근한 존댓말",
            length=length, extra=params.get("extra") or None, model=model,
            style=writing_style, references=references,
        )
        if self.cfg.get("refine_enabled"):
            job.update("AI가 글을 다듬는 중...")
            post = self.refiner(engine, post, writing_style)
        return self.store.add(
            title=post.title, html=post.html, tags=post.tags, category=_category_json(category),
            platform=self.platform_key, engine=engine, topic=params.get("topic") or None,
            references=raw_refs or None, styled=bool(writing_style),
        )

    def _post(self, post_id: str) -> dict:
        post = self.store.get(post_id)
        if not post:
            raise PlatformError("글을 찾지 못했습니다.")
        return post

    def job_style(self, job: Job, params: dict):
        engine = params.get("engine") or self.cfg.get("engine", DEFAULT_ENGINE)
        self.check_engine(engine)
        job.update("내 글을 읽고 글투를 분석하는 중...")
        result = self.style_analyzer(engine, params.get("samples") or "", self.fetch)
        self.cfg["style"] = {**result, "enabled": True, "updated": time.time()}
        config.save(self.cfg)
        return self.cfg["style"]

    def job_refine(self, job: Job, params: dict):
        post = self._post(params.get("post_id", ""))
        engine = params.get("engine") or self.cfg.get("engine", DEFAULT_ENGINE)
        self.check_engine(engine)
        job.update("AI가 글을 다듬는 중...")
        out = self.refiner(engine, Post(post["title"], post["html"], post["tags"]), self.style_for_writing())
        return self.store.update(post["id"], title=out.title, html=out.html, tags=out.tags,
                                 previous={"title": post["title"], "html": post["html"], "tags": post["tags"]})

    def job_factcheck(self, job: Job, params: dict):
        post = self._post(params.get("post_id", ""))
        engine = params.get("engine") or self.cfg.get("engine", DEFAULT_ENGINE)
        self.check_engine(engine)
        report = self.fact_checker(
            engine, Post(post["title"], post["html"], post["tags"]), post.get("references") or "",
            lambda message, fraction=None: job.update(message, fraction),
        )
        return self.store.update(post["id"], factcheck=report)

    def job_fix(self, job: Job, params: dict):
        post = self._post(params.get("post_id", ""))
        if not post.get("factcheck"):
            raise WriterError("먼저 팩트체크를 해 주세요.")
        engine = params.get("engine") or self.cfg.get("engine", DEFAULT_ENGINE)
        self.check_engine(engine)
        job.update("팩트체크 결과대로 글을 고치는 중...")
        out = factcheck.apply_fixes(engine, Post(post["title"], post["html"], post["tags"]), post["factcheck"])
        report = {**post["factcheck"], "fixed_at": time.time()}
        return self.store.update(post["id"], title=out.title, html=out.html, tags=out.tags, factcheck=report,
                                 previous={"title": post["title"], "html": post["html"], "tags": post["tags"]})

    def job_pull(self, job: Job, model: str):
        if model not in local_ai.MODELS:
            raise WriterError("알 수 없는 모델입니다.")
        job.update("모델 내려받기를 시작합니다...")
        local_ai.pull(model, lambda fraction, text: job.update(text, fraction))
        return local_ai.status()

    def ai_status(self) -> dict:
        st = local_ai.status()
        st["download_page"] = local_ai.DOWNLOAD_PAGE
        return st

    # ---- 설정 ---------------------------------------------------------------

    def _load_api_key(self):
        if os.environ.get("ANTHROPIC_API_KEY"):
            return
        key = self.cfg.get("anthropic_api_key")
        legacy = Path(__file__).resolve().parents[2] / "api_key.txt"  # 예전 실행.bat이 저장한 키
        if not key and legacy.exists():
            key = legacy.read_text(encoding="utf-8").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key

    def save_settings(self, data: dict):
        if "anthropic_api_key" in data:
            key = (data["anthropic_api_key"] or "").strip()
            if key:
                os.environ["ANTHROPIC_API_KEY"] = key
                self.cfg["anthropic_api_key"] = key
            else:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                self.cfg.pop("anthropic_api_key", None)
        if data.get("engine"):
            self.cfg["engine"] = data["engine"]
        if "refine_enabled" in data:
            self.cfg["refine_enabled"] = bool(data["refine_enabled"])
        if "style" in data:
            incoming = data["style"] or {}
            if not (incoming.get("guide") or "").strip():
                self.cfg.pop("style", None)  # 글투 지우기
            else:
                current = self.cfg.get("style") or {}
                self.cfg["style"] = {
                    **current,
                    "guide": incoming["guide"].strip(),
                    "enabled": bool(incoming.get("enabled", True)),
                    "updated": time.time(),
                }
        config.save(self.cfg)

    def close(self):
        config.save(self.cfg)

        def shutdown():
            if self.platform is not None:
                self.platform.close()

        try:
            self.platform_runner.call(shutdown, timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self.platform_runner.stop()
        self.ai_runner.stop()


def _target(settings: dict) -> str | None:
    return settings.get("site") or settings.get("blog_id") or settings.get("blog_name")


def _category_json(c: Category) -> dict:
    return {"id": c.id, "name": c.name, "parent": c.parent, "label": c.label}


def log(message: str):
    """작업 기록 (~/.blog-autoposter/app.log). 문제를 찾을 때 이 파일을 본다."""
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + message
    if os.environ.get("AUTOPOSTER_DEBUG"):
        print(line, flush=True)
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        path = config.HOME / "app.log"
        if path.exists() and path.stat().st_size > 2_000_000:
            path.replace(path.with_suffix(".old.log"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def friendly_error(exc: BaseException) -> str:
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    name = type(exc).__name__
    if "Timeout" in name:
        hint = "화면이 제때 열리지 않았습니다. 인터넷 연결을 확인하고 다시 시도해 주세요."
    elif "net::ERR" in text:
        hint = "사이트에 연결하지 못했습니다. 인터넷 연결, 백신·보안 프로그램, 프록시 설정을 확인해 주세요."
    elif "Executable doesn't exist" in text or "playwright install" in text:
        hint = "자동 조작용 브라우저가 없습니다. .venv 폴더를 지우고 실행.bat을 다시 실행해 주세요."
    else:
        hint = "예상하지 못한 오류가 났습니다."
    return f"{hint}\n({name}: {text})\n자세한 기록: {config.HOME / 'error.log'}"


def log_error(exc: BaseException):
    log(f"오류: {type(exc).__name__}: {exc}")
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        with open(config.HOME / "error.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + "".join(traceback.format_exception(exc)) + "\n")
    except OSError:
        pass


# ---- HTTP ---------------------------------------------------------------------


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200):
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def _authorized(self) -> bool:
            # 다른 웹사이트가 이 로컬 서버를 몰래 부르지 못하게 실행할 때마다 바뀌는 토큰을 확인한다.
            return secrets.compare_digest(self.headers.get("X-Token", ""), app.token)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/events":
                return self._events()
            if path.startswith("/api/"):
                if not self._authorized():
                    return self._json({"error": "인증 실패"}, 403)
                return self._api("GET", path, {})
            if path == "/":
                path = "/index.html"
            file = (STATIC_DIR / path.lstrip("/")).resolve()
            if STATIC_DIR.resolve() not in file.parents or not file.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, file.read_bytes(), ctype)

        def _events(self):
            """앱 창이 열려 있는 동안 유지되는 연결. 창을 닫으면 끊긴다.

            (EventSource는 헤더를 못 붙이므로 토큰은 주소로 받는다.)
            """
            if parse_qs(urlparse(self.path).query).get("t", [""])[0] != app.token:
                return self._send(403, b"forbidden", "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            app.client_connected()
            try:
                while not app.stopping:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(3)
            except OSError:
                pass
            finally:
                app.client_disconnected()

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/bye":  # 예전 화면과의 호환용 (이제는 /api/events 연결로 창 닫힘을 안다)
                return self._send(204, b"", "text/plain")
            if not self._authorized():
                return self._json({"error": "인증 실패"}, 403)
            try:
                body = self._body()
            except ValueError:
                return self._json({"error": "잘못된 요청"}, 400)
            self._api("POST", path, body)

        def _api(self, method: str, path: str, body: dict):
            if os.environ.get("AUTOPOSTER_DEBUG") and not path.startswith(("/api/jobs/", "/api/ping", "/api/ai")):
                log(f"요청: {method} {path}")
            try:
                result = route(app, method, path, body)
            except (PlatformError, WriterError) as exc:
                return self._json({"error": str(exc)}, 400)
            except KeyError:
                return self._json({"error": "없는 기능입니다"}, 404)
            except Exception as exc:  # noqa: BLE001
                log_error(exc)
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            self._json(result)

    return Handler


def route(app: App, method: str, path: str, body: dict):
    parts = path.strip("/").split("/")[1:]  # "api" 다음
    match (method, *parts):
        case ("GET", "state"):
            return app.state()
        case ("POST", "ping"):
            return {"ok": True}
        case ("GET", "ai"):
            return app.ai_status()
        case ("POST", "ai", "start"):
            return {"started": local_ai.start_ollama()}
        case ("POST", "platform"):
            app.switch_platform(body.get("key", ""))
            return app.state()
        case ("POST", "settings"):
            app.save_settings(body)
            return app.state()
        case ("POST", "open"):
            url = str(body.get("url", ""))
            if url.startswith(("https://", "http://")):
                webbrowser.open(url)
            return {"ok": True}
        case ("POST", "jobs", "login"):
            return app.start_job("login", "접속 준비 중...", app.job_login, app.platform_runner).to_json()
        case ("POST", "jobs", "categories"):
            return app.start_job("categories", "카테고리를 불러오는 중...", app.job_categories,
                                 app.platform_runner).to_json()
        case ("POST", "jobs", "publish"):
            post_id, draft = body.get("post_id", ""), bool(body.get("draft"))
            return app.start_job("publish", "올리는 중...", lambda job: app.job_publish(job, post_id, draft),
                                 app.platform_runner).to_json()
        case ("POST", "jobs", "write"):
            return app.start_job("write", "글쓰기 준비 중...", lambda job: app.job_write(job, body),
                                 app.ai_runner).to_json()
        case ("POST", "jobs", "style"):
            return app.start_job("style", "글투 분석 준비 중...", lambda job: app.job_style(job, body),
                                 app.ai_runner).to_json()
        case ("POST", "jobs", "refine"):
            return app.start_job("refine", "다듬기 준비 중...", lambda job: app.job_refine(job, body),
                                 app.ai_runner).to_json()
        case ("POST", "jobs", "factcheck"):
            return app.start_job("factcheck", "팩트체크 준비 중...", lambda job: app.job_factcheck(job, body),
                                 app.ai_runner).to_json()
        case ("POST", "jobs", "fix"):
            return app.start_job("fix", "고쳐 쓰기 준비 중...", lambda job: app.job_fix(job, body),
                                 app.ai_runner).to_json()
        case ("POST", "posts", post_id, "restore"):
            post = app.store.get(post_id)
            if not post or not post.get("previous"):
                raise PlatformError("되돌릴 이전 버전이 없습니다.")
            return app.store.update(post_id, **post["previous"], previous=None)
        case ("POST", "jobs", "pull"):
            model = body.get("model", "")
            return app.start_job("pull", "모델 내려받기 준비 중...", lambda job: app.job_pull(job, model),
                                 app.ai_runner).to_json()
        case ("GET", "jobs", job_id):
            return app.jobs[job_id].to_json()
        case ("POST", "jobs", job_id, "answer"):
            job = app.jobs[job_id]
            job.answer(None if body.get("cancel") else body.get("answer", ""))
            return {"ok": True}
        case ("POST", "posts", "import"):
            post = post_from_text(body.get("name", "글.md"), body.get("content", ""), parse_tags(body.get("tags", "")))
            return app.store.add(title=post.title, html=post.html, tags=post.tags, platform=app.platform_key,
                                 engine="file")
        case ("POST", "posts", post_id):
            allowed = {k: body[k] for k in ("title", "html", "tags") if k in body}
            if "tags" in allowed and isinstance(allowed["tags"], str):
                allowed["tags"] = parse_tags(allowed["tags"])
            if "category" in body:
                category = next((c for c in app.categories if c.label == body["category"]), None)
                if category is None:
                    raise PlatformError("카테고리를 다시 불러와 골라 주세요.")
                allowed.update(category=_category_json(category), platform=app.platform_key)
            post = app.store.update(post_id, **allowed)
            if post is None:
                raise KeyError(post_id)
            return post
        case ("POST", "posts", post_id, "delete"):
            app.store.delete(post_id)
            return {"ok": True}
    raise KeyError(path)


def create_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.daemon_threads = True
    return server
