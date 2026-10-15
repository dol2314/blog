"""웹 페이지 글 읽기와 정부·공공기관 자료 검색."""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# 공식 자료로 인정하는 사이트: 정부(go.kr), 정책브리핑, 국회, 법원, 주요 공공기관
OFFICIAL_SUFFIXES = (".go.kr", "korea.kr", ".assembly.go.kr", "scourt.go.kr")
OFFICIAL_HOSTS = {
    "korea.kr", "www.korea.kr", "law.go.kr", "www.law.go.kr", "kosis.kr", "www.kosis.kr",
    "www.koroad.or.kr", "koroad.or.kr", "www.nhis.or.kr", "www.nps.or.kr", "www.hira.or.kr",
    "www.kdca.go.kr", "www.bok.or.kr", "www.fss.or.kr", "www.kca.go.kr", "www.lh.or.kr",
    "www.kepco.co.kr", "www.kosaf.go.kr", "www.easylaw.go.kr", "easylaw.go.kr",
}


class WebError(RuntimeError):
    pass


def is_official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in OFFICIAL_HOSTS or any(host == s.lstrip(".") or host.endswith(s) for s in OFFICIAL_SUFFIXES)


def normalize_url(url: str) -> str:
    """본문이 iframe 안에 있는 네이버 블로그는 모바일 주소로 바꿔 읽는다."""
    parsed = urlparse(url.strip())
    if parsed.hostname in ("blog.naver.com", "www.blog.naver.com"):
        qs = parse_qs(parsed.query)
        if "blogId" in qs and "logNo" in qs:
            return f"https://m.blog.naver.com/{qs['blogId'][0]}/{qs['logNo'][0]}"
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 2 and parts[1].isdigit():
            return f"https://m.blog.naver.com/{parts[0]}/{parts[1]}"
    return url.strip()


def html_to_text(html: str) -> tuple[str, str]:
    """HTML에서 제목과 읽을 글자만 뽑는다."""
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    title = html_lib.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    body = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html_lib.unescape(body)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in body.splitlines()]
    return title, "\n".join(line for line in lines if len(line) > 1)


def fetch_text(url: str, render=None, timeout: int = 20) -> tuple[str, str]:
    """페이지의 (제목, 본문 글자)를 돌려준다. 글자가 거의 없으면 브라우저로 열어 다시 읽는다."""
    url = normalize_url(url)
    title, text = "", ""
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=timeout)
        if resp.ok:
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding
            title, text = html_to_text(resp.text)
    except requests.RequestException:
        pass
    if len(text) < 300 and render is not None:
        try:
            title2, text2 = render(url)
            if len(text2) > len(text):
                title, text = title2 or title, text2
        except Exception:  # noqa: BLE001 - 브라우저로도 못 읽으면 있는 것만 쓴다
            pass
    if not text:
        raise WebError(f"페이지를 읽지 못했습니다: {url}")
    return title, text


def render_with_browser(url: str) -> tuple[str, str]:
    """자바스크립트로 그려지는 페이지(정부 사이트에 많음)를 화면 없는 브라우저로 읽는다.

    호출한 스레드에서 브라우저를 새로 열고 닫는다.
    """
    from .platforms.browser import Browser

    browser = Browser("reader", headless=True)
    try:
        page = browser.page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1500)
        parts = []
        for frame in page.frames:
            try:
                parts.append(frame.inner_text("body", timeout=3000))
            except Exception:  # noqa: BLE001
                continue
        return page.title(), "\n".join(parts)
    finally:
        browser.close()


def search_official(query: str, limit: int = 3) -> list[dict]:
    """정부·공공기관 사이트에서 검색어로 찾은 페이지 목록 [{title, url}]."""
    q = f"{query} (site:go.kr OR site:korea.kr OR site:law.go.kr)"
    results: list[dict] = []
    for search in (_duckduckgo, _bing):
        try:
            for item in search(q):
                if is_official(item["url"]) and all(r["url"] != item["url"] for r in results):
                    results.append(item)
        except requests.RequestException:
            continue
        if len(results) >= limit:
            break
    return results[:limit]


def _duckduckgo(q: str) -> list[dict]:
    resp = requests.get(
        f"https://html.duckduckgo.com/html/?q={quote_plus(q)}&kl=kr-kr",
        headers={"User-Agent": UA}, timeout=15,
    )
    items = []
    for href, title in re.findall(r'(?s)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', resp.text):
        href = html_lib.unescape(href)
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        items.append({"url": href, "title": html_lib.unescape(re.sub(r"<[^>]+>", "", title)).strip()})
    return items


def _bing(q: str) -> list[dict]:
    resp = requests.get(
        f"https://www.bing.com/search?q={quote_plus(q)}&setlang=ko&cc=KR",
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=15,
    )
    items = []
    for block in re.findall(r'(?s)<li class="b_algo".*?</li>', resp.text):
        m = re.search(r'(?s)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if m:
            items.append({"url": html_lib.unescape(m.group(1)), "title": html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()})
    return items


def relevant_passages(text: str, keywords: list[str], limit: int = 2500) -> str:
    """긴 페이지에서 검색어와 관련된 줄만 골라 AI에게 보낼 분량으로 줄인다."""
    words = [w for w in {k.strip() for k in keywords} if len(w) >= 2]
    lines = [line for line in text.splitlines() if len(line) >= 8]
    if not words:
        return "\n".join(lines)[:limit]
    scored = [(sum(line.count(w) for w in words), i, line) for i, line in enumerate(lines)]
    keep = sorted(i for score, i, _ in sorted(scored, reverse=True)[:40] if score > 0)
    picked, total = [], 0
    for i in keep:
        chunk = " ".join(lines[max(0, i - 1): i + 2])
        if total + len(chunk) > limit:
            break
        picked.append(chunk)
        total += len(chunk)
    return "\n".join(picked) if picked else "\n".join(lines)[:limit]


def split_urls(text: str) -> tuple[list[str], str]:
    """붙여넣은 참고 자료에서 주소(URL) 줄과 나머지 글을 나눈다."""
    urls, rest = [], []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.fullmatch(r"https?://\S+", stripped):
            urls.append(stripped)
        else:
            rest.append(line)
    return urls, "\n".join(rest).strip()
