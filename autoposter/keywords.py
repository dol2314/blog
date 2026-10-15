"""네이버 자동검색어 수집과 앱스토어 링크 찾기.

네이버 자동검색어에 뜨는 말은 사람들이 실제로 치는 말이다. 2단계까지 모아 글 한 편에 전부 담는다.
(공식 API가 아니므로 요청 사이에 간격을 두고, 실패하면 빈 목록을 돌려준다.)
"""

from __future__ import annotations

import time
from urllib.parse import quote

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
AC_URL = (
    "https://ac.search.naver.com/nx/ac?q={q}&st=100&r_format=json&r_enh=0&r_lt=0"
    "&q_enc=UTF-8&r_unicode=0&t_koreng=1&ans=2&run=2&rev=4&con=1"
)


class KeywordError(RuntimeError):
    pass


def autocomplete(query: str, http=requests) -> list[str]:
    """네이버 자동검색어 한 번 조회. 띄어쓰기는 실제 검색어 그대로 보존한다."""
    try:
        resp = http.get(
            AC_URL.format(q=quote(query)),
            headers={"User-Agent": UA, "Referer": "https://search.naver.com/"},
            timeout=12,
        )
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for group in data.get("items", []) or []:
        for item in group or []:
            if isinstance(item, list) and item and isinstance(item[0], str) and item[0].strip():
                out.append(item[0].strip())
    return out


def collect(base: str, expand: int = 8, pause: float = 0.35, fetch=autocomplete, sleep=time.sleep) -> list[str]:
    """2단계까지 자동검색어를 모은다. 첫 단계 결과 중 앞의 `expand`개를 한 번 더 판다."""
    base = base.strip()
    if not base:
        raise KeywordError("메인 키워드를 넣어 주세요.")
    first = fetch(base)
    found: list[str] = []
    for kw in first:
        if kw not in found:
            found.append(kw)
    for kw in first[:expand]:
        sleep(pause)
        for more in fetch(kw + " "):
            if more not in found:
                found.append(more)
    return [kw for kw in found if kw != base]


def find_apps(name: str, http=requests) -> list[dict]:
    """앱 이름으로 iOS 앱스토어를 찾고, 같은 패키지명의 플레이스토어 페이지가 있는지 확인한다."""
    try:
        resp = http.get(
            "https://itunes.apple.com/search",
            params={"term": name, "country": "kr", "entity": "software", "limit": 6},
            timeout=12,
        )
        results = resp.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        raise KeywordError("앱스토어 검색에 실패했습니다. 인터넷 연결을 확인해 주세요.") from exc
    apps = []
    for r in results:
        bundle = r.get("bundleId", "")
        play = f"https://play.google.com/store/apps/details?id={bundle}&hl=ko&gl=KR" if bundle else ""
        play_ok = False
        if play:
            try:
                play_ok = http.get(play, headers={"User-Agent": UA}, timeout=10).status_code == 200
            except requests.RequestException:
                play_ok = False
        apps.append({
            "name": r.get("trackName", ""),
            "seller": r.get("sellerName", ""),
            "ios": f"https://apps.apple.com/kr/app/id{r['trackId']}" if r.get("trackId") else "",
            "android": play if play_ok else "",
            "description": (r.get("description") or "")[:600],
        })
    return apps
