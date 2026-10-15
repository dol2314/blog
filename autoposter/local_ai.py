"""내 PC에서 돌리는 AI (Ollama + Qwen3)로 글을 쓴다. API 키가 필요 없다.

Qwen3는 Apache 2.0 라이선스라 상업적 이용(블로그 수익화 포함)이 가능하다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

from .models import Post
from .textutil import markdown_to_html
from .writer import POST_SCHEMA, SYSTEM_PROMPT, WriterError, build_prompt

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
DOWNLOAD_PAGE = "https://ollama.com/download"

# 그래픽 메모리 6GB 기준: 8B는 대부분 그래픽카드에서, 14B는 일부를 메모리로 넘겨 돌아간다.
MODELS = {
    "qwen3:8b": {"label": "Qwen3 8B", "size": "약 5.2GB", "note": "빠름 · 권장"},
    "qwen3:14b": {"label": "Qwen3 14B", "size": "약 9GB", "note": "더 자연스러움 · 느림"},
}
DEFAULT_MODEL = "qwen3:8b"

LOCAL_RULES = """
반드시 한국어로 씁니다.
답은 title, html, tags 세 항목을 가진 JSON 하나로만 합니다.
html 값에는 마크다운이 아니라 HTML 태그(h2, p, ul, li, strong)를 씁니다.
"""


class LocalAIError(WriterError):
    pass


def _http(session):
    """Ollama는 내 PC 안에 있으므로 PC에 설정된 프록시를 거치지 않고 바로 접속한다."""
    if session is not None:
        return session
    direct = requests.Session()
    direct.trust_env = False
    return direct


def status(session: requests.Session | None = None) -> dict:
    """Ollama 실행 여부와 내려받은 모델 목록."""
    http = _http(session)
    try:
        version = http.get(f"{OLLAMA_URL}/api/version", timeout=5).json().get("version")
        tags = http.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
    except (requests.RequestException, ValueError) as exc:
        return {
            "running": False,
            "installed": _installed_path() is not None,
            "version": None,
            "models": [],
            "reason": f"{type(exc).__name__}: {exc}"[:300],
        }
    names = [m.get("name", "") for m in tags.get("models", [])]
    return {"running": True, "installed": True, "version": version, "models": names}


def has_model(model: str, models: list[str]) -> bool:
    return any(name == model or name == f"{model}:latest" for name in models)


def start_ollama() -> bool:
    """설치돼 있지만 꺼져 있으면 켠다."""
    path = _installed_path()
    if not path:
        return False
    args = [str(path)] if path.name.lower() == "ollama app.exe" else [str(path), "serve"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(  # noqa: S603
        args, creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


def _installed_path() -> Path | None:
    """Ollama 실행 파일 위치 (트레이 앱을 우선)."""
    folders = []
    for env in ("LOCALAPPDATA", "ProgramFiles"):
        if os.environ.get(env):
            folders.append(Path(os.environ[env]) / ("Programs/Ollama" if env == "LOCALAPPDATA" else "Ollama"))
    for folder in folders:
        for name in ("ollama app.exe", "ollama.exe"):
            if (folder / name).exists():
                return folder / name
    found = shutil.which("ollama")
    return Path(found) if found else None


def pull(model: str, on_progress=None, session: requests.Session | None = None) -> None:
    """모델을 내려받는다. on_progress(0~1 비율 또는 None, 상태 글자)."""
    http = _http(session)
    try:
        resp = http.post(f"{OLLAMA_URL}/api/pull", json={"model": model, "stream": True}, stream=True, timeout=60)
    except requests.RequestException as exc:
        raise LocalAIError("내 PC AI(Ollama)에 연결하지 못했습니다. Ollama가 실행 중인지 확인하세요.") from exc
    if resp.status_code != 200:
        raise LocalAIError(f"모델을 내려받지 못했습니다 (HTTP {resp.status_code}).")
    for line in resp.iter_lines():
        if not line:
            continue
        event = json.loads(line)
        if event.get("error"):
            raise LocalAIError(f"모델을 내려받지 못했습니다: {event['error']}")
        total, done = event.get("total"), event.get("completed")
        fraction = done / total if total and done is not None else None
        if on_progress:
            on_progress(fraction, _pull_status_text(event.get("status", ""), fraction))
        if event.get("status") == "success":
            return
    raise LocalAIError("모델 내려받기가 중간에 끊겼습니다. 다시 시도해 주세요.")


def _pull_status_text(status: str, fraction: float | None) -> str:
    if status.startswith("pulling") and fraction is not None:
        return f"내려받는 중 {fraction * 100:.0f}%"
    return {
        "pulling manifest": "모델 정보 확인 중",
        "verifying sha256 digest": "파일 확인 중",
        "writing manifest": "마무리 중",
        "success": "완료",
    }.get(status, "준비 중")


def write_post_local(
    category: str,
    topic: str | None = None,
    tone: str = "친근한 존댓말",
    length: int = 2000,
    extra: str | None = None,
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    attempts: int = 3,
) -> Post:
    http = _http(session)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + LOCAL_RULES},
            {"role": "user", "content": build_prompt(category, topic, tone, length, extra)},
        ],
        "stream": False,
        "think": False,
        "format": POST_SCHEMA,
        "options": {"temperature": 0.7, "num_ctx": 8192},
        "keep_alive": "15m",
    }
    last_error = None
    for _ in range(attempts):
        try:
            resp = http.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=1800)
        except requests.RequestException as exc:
            raise LocalAIError("내 PC AI(Ollama)에 연결하지 못했습니다. Ollama가 실행 중인지 확인하세요.") from exc
        if resp.status_code == 404:
            raise LocalAIError(f"'{model}' 모델이 없습니다. 먼저 모델을 내려받아 주세요.")
        if resp.status_code != 200:
            raise LocalAIError(f"내 PC AI 오류 (HTTP {resp.status_code}): {resp.text[:200]}")
        content = resp.json().get("message", {}).get("content", "")
        try:
            return parse_post(content)
        except (ValueError, KeyError, TypeError) as exc:
            last_error = exc  # 작은 모델은 가끔 형식을 틀린다 → 다시 요청
    raise LocalAIError(f"내 PC AI가 글을 올바른 형식으로 만들지 못했습니다. 다시 시도해 주세요. ({last_error})")


def parse_post(content: str) -> Post:
    content = re.sub(r"(?s)<think>.*?</think>", "", content).strip()
    match = re.search(r"(?s)\{.*\}", content)
    if not match:
        raise ValueError("JSON이 없습니다")
    data = json.loads(match.group(0))
    title = str(data["title"]).strip()
    html = str(data["html"]).strip()
    if not title or not html:
        raise ValueError("제목이나 본문이 비었습니다")
    if not re.search(r"<(p|h2|h3|ul|ol)\b", html):
        _, html = markdown_to_html(html)  # 마크다운으로 쓴 경우 HTML로 바꾼다
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    clean = [str(t).strip().lstrip("#") for t in tags if str(t).strip().lstrip("#")]
    return Post(title=title, html=html, tags=list(dict.fromkeys(clean))[:10])
