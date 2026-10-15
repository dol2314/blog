"""설정 파일 (~/.blog-autoposter/config.json) 읽기/쓰기."""

from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("AUTOPOSTER_HOME", Path.home() / ".blog-autoposter"))
CONFIG_PATH = HOME / "config.json"
PROFILES_DIR = HOME / "profiles"


def load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save(config: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)  # 워드프레스 앱 비밀번호가 들어가므로 본인만 읽게
    except OSError:
        pass


def section(config: dict, name: str) -> dict:
    return config.setdefault(name, {})


def profile_dir(platform: str) -> Path:
    """브라우저 로그인 상태를 보관하는 플랫폼별 폴더."""
    path = PROFILES_DIR / platform
    path.mkdir(parents=True, exist_ok=True)
    return path
