"""환경변수(.env) 설정과 공용 도우미."""
from __future__ import annotations

import os
import platform
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv 가 없어도 동작
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value.strip() if value.strip() else default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


FONT_CANDIDATES = {
    "Windows": ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"],
    "Darwin": ["/System/Library/Fonts/AppleSDGothicNeo.ttc", "/Library/Fonts/AppleGothic.ttf"],
    "Linux": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ],
}


def find_font() -> str:
    """한글이 나오는 굵은 폰트 경로. FONT_PATH → assets/fonts → 운영체제 기본 순서."""
    custom = env("FONT_PATH")
    if custom and Path(custom).exists():
        return custom
    for f in sorted((ROOT / "assets" / "fonts").glob("*.[ot]t[fc]")):
        return str(f)
    for f in FONT_CANDIDATES.get(platform.system(), []) + sum(FONT_CANDIDATES.values(), []):
        if Path(f).exists():
            return f
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. .env 의 FONT_PATH 에 .ttf 경로를 넣거나 assets/fonts/ 에 폰트를 넣으세요 "
        "(예: 나눔고딕, Noto Sans KR)."
    )


def slugify(text: str, limit: int = 40) -> str:
    text = re.sub(r"[^\w가-힣]+", "-", text).strip("-")
    return text[:limit] or "video"
